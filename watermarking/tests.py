import io

import numpy as np
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from . import utils


def _make_image(size=(128, 96), seed=0, mode="RGB"):
    rng = np.random.default_rng(seed)
    if mode == "RGB":
        arr = rng.integers(0, 256, size=(size[1], size[0], 3), dtype=np.uint8)
    else:
        arr = rng.integers(0, 256, size=(size[1], size[0]), dtype=np.uint8)
    return Image.fromarray(arr, mode=mode)


def _to_png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


class HaarTransformTests(TestCase):
    """The transform itself must be exactly invertible."""

    def test_round_trip_even_size(self):
        arr = np.random.default_rng(1).uniform(0, 255, size=(64, 48))
        coeffs = utils._haar_dwt2(arr)
        reconstructed = utils._haar_idwt2(coeffs)
        np.testing.assert_allclose(reconstructed, arr, atol=1e-8)

    def test_subbands_are_quarter_size(self):
        arr = np.zeros((64, 32))
        ll, (lh, hl, hh) = utils._haar_dwt2(arr)
        for band in (ll, lh, hl, hh):
            self.assertEqual(band.shape, (32, 16))


class WatermarkAlgorithmTests(TestCase):
    """End-to-end embed/extract behaviour, independent of Django views."""

    def test_embed_returns_same_size_rgb_image(self):
        cover = _make_image((100, 80))
        watermark = _make_image((20, 20), mode="L")
        watermarked = utils.embed_watermark(cover, watermark)
        self.assertEqual(watermarked.size, cover.size)
        self.assertEqual(watermarked.mode, "RGB")

    def test_odd_sized_cover_image_round_trips(self):
        # Deliberately odd width/height to exercise the padding logic.
        cover = _make_image((101, 77))
        watermark = _make_image((16, 16), mode="L")
        watermarked = utils.embed_watermark(cover, watermark, alpha=12.0, subband="HL")
        self.assertEqual(watermarked.size, cover.size)
        recovered = utils.extract_watermark(watermarked, cover, alpha=12.0, subband="HL")
        self.assertIsNotNone(recovered)

    def test_recovered_watermark_correlates_with_original(self):
        cover = _make_image((256, 256), seed=2)
        watermark_arr = np.zeros((64, 64), dtype=np.uint8)
        watermark_arr[16:48, 16:48] = 255
        watermark = Image.fromarray(watermark_arr, mode="L")

        watermarked = utils.embed_watermark(cover, watermark, alpha=15.0, subband="HL")
        # Round-trip through PNG bytes, like a real upload/download would.
        reloaded = Image.open(io.BytesIO(_to_png_bytes(watermarked)))

        recovered = utils.extract_watermark(reloaded, cover, alpha=15.0, subband="HL")
        recovered_arr = np.asarray(recovered, dtype=np.float64)
        wm_resized = np.asarray(
            watermark.resize(recovered.size, Image.LANCZOS), dtype=np.float64
        )
        correlation = np.corrcoef(recovered_arr.flatten(), wm_resized.flatten())[0, 1]
        self.assertGreater(correlation, 0.85)

    def test_watermarking_is_nearly_invisible(self):
        cover = _make_image((200, 150), seed=3)
        watermark = _make_image((40, 40), mode="L", seed=4)
        watermarked = utils.embed_watermark(cover, watermark, alpha=10.0, subband="HL")

        cover_arr = np.asarray(cover, dtype=np.float64)
        watermarked_arr = np.asarray(watermarked, dtype=np.float64)
        mse = np.mean((cover_arr - watermarked_arr) ** 2)
        psnr = 20 * np.log10(255.0 / np.sqrt(mse)) if mse > 0 else float("inf")
        # 30+ dB is generally considered visually close to lossless.
        self.assertGreater(psnr, 30.0)

    def test_mismatched_alpha_does_not_crash_but_degrades_badly(self):
        cover = _make_image((128, 128), seed=5)
        watermark_arr = np.zeros((32, 32), dtype=np.uint8)
        watermark_arr[8:24, 8:24] = 255
        watermark = Image.fromarray(watermark_arr, mode="L")

        watermarked = utils.embed_watermark(cover, watermark, alpha=10.0, subband="HL")
        recovered_right_alpha = utils.extract_watermark(watermarked, cover, alpha=10.0, subband="HL")
        recovered_wrong_alpha = utils.extract_watermark(watermarked, cover, alpha=90.0, subband="HL")

        right_arr = np.asarray(recovered_right_alpha, dtype=np.float64)
        wrong_arr = np.asarray(recovered_wrong_alpha, dtype=np.float64)
        wm_resized = np.asarray(
            watermark.resize(recovered_right_alpha.size, Image.LANCZOS), dtype=np.float64
        )
        right_corr = np.corrcoef(right_arr.flatten(), wm_resized.flatten())[0, 1]
        wrong_corr = np.corrcoef(wrong_arr.flatten(), wm_resized.flatten())[0, 1]
        self.assertGreater(right_corr, wrong_corr)

    def test_invalid_subband_raises(self):
        cover = _make_image((64, 64))
        watermark = _make_image((16, 16), mode="L")
        with self.assertRaises(utils.WatermarkError):
            utils.embed_watermark(cover, watermark, subband="NOPE")

    def test_non_positive_alpha_raises(self):
        cover = _make_image((64, 64))
        watermark = _make_image((16, 16), mode="L")
        with self.assertRaises(utils.WatermarkError):
            utils.embed_watermark(cover, watermark, alpha=0)


class ViewTests(TestCase):
    """Smoke tests for the Django views that wrap the algorithm."""

    def test_embed_page_loads(self):
        response = self.client.get(reverse("watermarking:embed"))
        self.assertEqual(response.status_code, 200)

    def test_extract_page_loads(self):
        response = self.client.get(reverse("watermarking:extract"))
        self.assertEqual(response.status_code, 200)

    def test_embed_post_returns_result_image(self):
        cover_bytes = _to_png_bytes(_make_image((80, 60), seed=10))
        watermark_bytes = _to_png_bytes(_make_image((16, 16), mode="L", seed=11))

        response = self.client.post(
            reverse("watermarking:embed"),
            {
                "cover_image": SimpleUploadedFile("cover.png", cover_bytes, "image/png"),
                "watermark_image": SimpleUploadedFile("wm.png", watermark_bytes, "image/png"),
                "alpha": 10.0,
                "subband": "HL",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context["result_url"])
        self.assertIsNone(response.context["error"])

    def test_embed_rejects_non_image_upload(self):
        bogus = SimpleUploadedFile("not_an_image.txt", b"hello world", "text/plain")
        watermark_bytes = _to_png_bytes(_make_image((16, 16), mode="L", seed=12))
        response = self.client.post(
            reverse("watermarking:embed"),
            {
                "cover_image": bogus,
                "watermark_image": SimpleUploadedFile("wm.png", watermark_bytes, "image/png"),
                "alpha": 10.0,
                "subband": "HL",
            },
        )
        self.assertEqual(response.status_code, 200)
        # Django's ImageField validates this at the form level.
        self.assertFalse(response.context["form"].is_valid())
