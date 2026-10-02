"""
Haar wavelet image watermarking.

This module contains the actual image-processing logic and has no
Django dependency at all (it only needs numpy and Pillow), so it can
be imported and tested completely on its own — see the bottom of this
file for a self-test you can run with ``python utils.py``.

The single-level 2D Haar Discrete Wavelet Transform (DWT) itself is
implemented directly with numpy below (see ``_haar_dwt2`` /
``_haar_idwt2``) instead of depending on an external wavelet library.
The Haar transform is simple enough — one averaging/differencing step
per pixel pair, in each direction — that writing it out directly keeps
the whole pipeline inspectable in one file, with no "black box" step.

How the watermarking scheme works
----------------------------------
This is a classic, *non-blind* transform-domain watermarking scheme:

1. The cover image is converted to the YCbCr color space and only the
   luminance (Y) channel is touched, so the embedded watermark barely
   affects perceived color.
2. A single-level 2D Haar DWT is applied to the Y channel, splitting
   it into four sub-bands, each a quarter of the size of the input:

       LL  (approximation)       - coarse overall brightness
       LH  (horizontal detail)
       HL  (vertical detail)
       HH  (diagonal detail)

3. The watermark image is converted to grayscale, resized to exactly
   match the chosen sub-band's dimensions, normalized to the 0..1
   range, and added into that sub-band, scaled by a strength factor
   ``alpha``:

       watermarked_band = original_band + alpha * watermark

4. The inverse DWT reconstructs a watermarked Y channel, which is
   merged back with the untouched Cb/Cr channels to produce the final
   watermarked RGB image.

Because the watermark is added in, recovering it is just algebra: if
you still have the *original, unwatermarked* cover image, redo the
same DWT on both images and subtract:

       watermark ≈ (watermarked_band - original_band) / alpha

This is why the scheme is "non-blind" — extraction needs the original
cover image, not just the watermarked one. That is a deliberate choice
for this project: it is far simpler and far more robust to explain and
verify than a blind scheme, at the cost of requiring the original
image again at extraction time. See README.md for more on this
trade-off and how you might move to a blind scheme later.

Important: the watermarked image must be saved and shared losslessly
(PNG), not as JPEG. JPEG's lossy compression perturbs exactly the
high-frequency coefficients this scheme relies on, and will corrupt or
destroy the watermark.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

#: The four sub-bands produced by a single-level 2D Haar DWT.
SUPPORTED_SUBBANDS = ("LL", "LH", "HL", "HH")

DEFAULT_ALPHA = 10.0
DEFAULT_SUBBAND = "HL"

_SQRT2 = np.sqrt(2.0)


class WatermarkError(ValueError):
    """Raised for invalid inputs to the embed/extract functions."""


# --------------------------------------------------------------------------
# Single-level 2D Haar DWT, implemented directly with numpy.
#
# This is a separable transform: a 1D Haar step (average/difference of
# neighboring pairs, orthonormal thanks to the 1/sqrt(2) factor) is applied
# along the rows, then again along the columns of the result. It is exactly
# invertible (up to floating-point rounding) for any even-sized input.
# --------------------------------------------------------------------------

def _haar_dwt2(arr: np.ndarray) -> tuple[np.ndarray, tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Forward single-level 2D Haar DWT. ``arr`` must have even height/width."""
    top, bottom = arr[0::2, :], arr[1::2, :]
    low_rows = (top + bottom) / _SQRT2
    high_rows = (top - bottom) / _SQRT2

    def split_cols(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        left, right = x[:, 0::2], x[:, 1::2]
        return (left + right) / _SQRT2, (left - right) / _SQRT2

    ll, lh = split_cols(low_rows)   # LL: approximation; LH: horizontal detail
    hl, hh = split_cols(high_rows)  # HL: vertical detail; HH: diagonal detail
    return ll, (lh, hl, hh)


def _haar_idwt2(coeffs: tuple[np.ndarray, tuple[np.ndarray, np.ndarray, np.ndarray]]) -> np.ndarray:
    """Inverse of :func:`_haar_dwt2`."""
    ll, (lh, hl, hh) = coeffs

    def merge_cols(low: np.ndarray, high: np.ndarray) -> np.ndarray:
        left, right = (low + high) / _SQRT2, (low - high) / _SQRT2
        h, w = low.shape
        out = np.empty((h, w * 2), dtype=low.dtype)
        out[:, 0::2], out[:, 1::2] = left, right
        return out

    low_rows = merge_cols(ll, lh)
    high_rows = merge_cols(hl, hh)
    h, w = low_rows.shape
    out = np.empty((h * 2, w), dtype=low_rows.dtype)
    top, bottom = (low_rows + high_rows) / _SQRT2, (low_rows - high_rows) / _SQRT2
    out[0::2, :], out[1::2, :] = top, bottom
    return out


def _validate_subband(subband: str) -> None:
    if subband not in SUPPORTED_SUBBANDS:
        raise WatermarkError(
            f"Unknown subband {subband!r}; must be one of {SUPPORTED_SUBBANDS}"
        )


def _pad_to_even(arr: np.ndarray) -> tuple[np.ndarray, tuple[int, int]]:
    """Pad a 2D array by one row/column (edge replication) if needed.

    The Haar DWT above requires even height and width. Odd-sized images
    are padded before the transform and cropped back to their original
    size afterwards, so the embed/extract round trip is transparent to
    the caller regardless of the input image's dimensions.
    """
    original_shape = arr.shape
    pad_h = arr.shape[0] % 2
    pad_w = arr.shape[1] % 2
    if pad_h or pad_w:
        arr = np.pad(arr, ((0, pad_h), (0, pad_w)), mode="edge")
    return arr, original_shape


def _crop_to(arr: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    h, w = shape
    return arr[:h, :w]


def _get_subband(coeffs, name: str) -> np.ndarray:
    ll, (lh, hl, hh) = coeffs
    return {"LL": ll, "LH": lh, "HL": hl, "HH": hh}[name]


def _replace_subband(coeffs, name: str, new_band: np.ndarray):
    ll, (lh, hl, hh) = coeffs
    bands = {"LL": ll, "LH": lh, "HL": hl, "HH": hh}
    bands[name] = new_band
    return bands["LL"], (bands["LH"], bands["HL"], bands["HH"])


def _y_channel_array(image: Image.Image) -> tuple[np.ndarray, tuple[int, int], Image.Image, Image.Image]:
    """Split an image into (padded Y array, original shape, Cb image, Cr image)."""
    ycbcr = image.convert("RGB").convert("YCbCr")
    y, cb, cr = ycbcr.split()
    y_arr = np.asarray(y, dtype=np.float64)
    y_arr, original_shape = _pad_to_even(y_arr)
    return y_arr, original_shape, cb, cr


def embed_watermark(
    cover_image: Image.Image,
    watermark_image: Image.Image,
    alpha: float = DEFAULT_ALPHA,
    subband: str = DEFAULT_SUBBAND,
) -> Image.Image:
    """Embed ``watermark_image`` into ``cover_image`` using a Haar DWT.

    Parameters
    ----------
    cover_image:
        The "host" image that will carry the watermark. Any mode/size
        is accepted; it is converted to RGB internally.
    watermark_image:
        The image to hide. It is converted to grayscale and resized to
        fit the chosen sub-band, so it can be any size or aspect ratio
        (a simple, bold image — e.g. a logo or high-contrast text —
        survives the resize-down and recovery better than a highly
        detailed photo).
    alpha:
        Embedding strength. Larger values make the watermark easier to
        recover but more visible/damaging to the cover image. Must
        match the value passed to :func:`extract_watermark` later.
    subband:
        Which DWT sub-band to embed into: one of ``"LL"``, ``"LH"``,
        ``"HL"``, ``"HH"``. Must match the value used at extraction
        time. ``"HL"`` (the default) is a reasonable middle ground
        between invisibility and ease of recovery.

    Returns
    -------
    PIL.Image.Image
        The watermarked image, in RGB mode. Save this losslessly
        (PNG) — see the module docstring for why.
    """
    _validate_subband(subband)
    if alpha <= 0:
        raise WatermarkError("alpha must be a positive number")

    y_arr, original_shape, cb, cr = _y_channel_array(cover_image)

    coeffs = _haar_dwt2(y_arr)
    target_band = _get_subband(coeffs, subband)
    band_h, band_w = target_band.shape

    watermark_gray = watermark_image.convert("L").resize(
        (band_w, band_h), Image.LANCZOS
    )
    watermark_arr = np.asarray(watermark_gray, dtype=np.float64) / 255.0

    new_band = target_band + alpha * watermark_arr
    new_coeffs = _replace_subband(coeffs, subband, new_band)

    y_watermarked = _haar_idwt2(new_coeffs)
    y_watermarked = _crop_to(y_watermarked, original_shape)
    y_watermarked = np.clip(np.round(y_watermarked), 0, 255).astype(np.uint8)

    y_out = Image.fromarray(y_watermarked, mode="L")
    watermarked_ycbcr = Image.merge("YCbCr", (y_out, cb, cr))
    return watermarked_ycbcr.convert("RGB")


def extract_watermark(
    watermarked_image: Image.Image,
    original_image: Image.Image,
    alpha: float = DEFAULT_ALPHA,
    subband: str = DEFAULT_SUBBAND,
) -> Image.Image:
    """Recover a watermark previously embedded with :func:`embed_watermark`.

    Parameters
    ----------
    watermarked_image:
        The watermarked image produced by :func:`embed_watermark` (or
        a copy of it — ideally untouched by lossy recompression or
        resizing, which will degrade the recovered watermark).
    original_image:
        The original cover image, *before* the watermark was embedded.
        This non-blind scheme needs it to isolate what changed.
    alpha, subband:
        Must exactly match the values used when the watermark was
        embedded, or the recovered watermark will come out as noise,
        inverted, or at the wrong intensity.

    Returns
    -------
    PIL.Image.Image
        The recovered watermark as a grayscale ("L" mode) image, at
        the resolution of the chosen sub-band (roughly half the cover
        image's width and height, since a single-level DWT halves
        each dimension).
    """
    _validate_subband(subband)
    if alpha <= 0:
        raise WatermarkError("alpha must be a positive number")

    if watermarked_image.size != original_image.size:
        # Best-effort recovery even if the original was saved/resized
        # differently; exact-size inputs always give the cleanest result.
        original_image = original_image.resize(watermarked_image.size, Image.LANCZOS)

    wm_y_arr, _, _, _ = _y_channel_array(watermarked_image)
    orig_y_arr, _, _, _ = _y_channel_array(original_image)

    wm_coeffs = _haar_dwt2(wm_y_arr)
    orig_coeffs = _haar_dwt2(orig_y_arr)

    wm_band = _get_subband(wm_coeffs, subband)
    orig_band = _get_subband(orig_coeffs, subband)

    recovered = (wm_band - orig_band) / alpha
    recovered = np.clip(recovered, 0.0, 1.0) * 255.0
    recovered = np.round(recovered).astype(np.uint8)

    return Image.fromarray(recovered, mode="L")


if __name__ == "__main__":
    # A small smoke test you can run directly with `python utils.py`,
    # without Django, to sanity-check the algorithm end to end.
    import io

    rng = np.random.default_rng(0)
    cover_arr = rng.integers(0, 256, size=(256, 256, 3), dtype=np.uint8)
    cover = Image.fromarray(cover_arr, mode="RGB")

    watermark_arr = np.zeros((64, 64), dtype=np.uint8)
    watermark_arr[16:48, 16:48] = 255  # a simple white square on black
    watermark = Image.fromarray(watermark_arr, mode="L")

    watermarked = embed_watermark(cover, watermark, alpha=15.0, subband="HL")

    # Round-trip through PNG bytes to mimic saving/reloading the file.
    buf = io.BytesIO()
    watermarked.save(buf, format="PNG")
    buf.seek(0)
    watermarked_reloaded = Image.open(buf)

    recovered = extract_watermark(watermarked_reloaded, cover, alpha=15.0, subband="HL")
    recovered.save("self_test_recovered_watermark.png")
    print("Self-test complete. See self_test_recovered_watermark.png")
    print("It should show a light square on a dark background.")
