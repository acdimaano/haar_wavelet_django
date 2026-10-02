# Haar Wavelet Image Watermarking (Django)

A small Django web app that embeds an invisible watermark into an image
using a **2D Haar Discrete Wavelet Transform (DWT)**, and can extract that
watermark back out again.

- **Embed** page: upload a cover image + a watermark image → get back a
  watermarked PNG that looks (almost) identical to the cover image.
- **Extract** page: upload the watermarked image + the original cover image
  → get back the recovered watermark.

The wavelet math itself is implemented from scratch in
[`watermarking/utils.py`](watermarking/utils.py) using only NumPy — no
external wavelet library — so the whole algorithm is readable in one file
and has no Django dependency (you can `import` and use it on its own).

---

## How it works, briefly

1. The cover image is converted to **YCbCr** color space. Only the
   luminance (**Y**) channel is modified, so colors stay essentially
   unchanged.
2. A single-level **2D Haar DWT** splits the Y channel into four
   same-size sub-bands:

   | Sub-band | What it holds |
   |---|---|
   | `LL` | approximation (coarse brightness) |
   | `LH` | horizontal detail |
   | `HL` | vertical detail |
   | `HH` | diagonal detail |

3. The watermark image is grayscaled, resized to exactly match the chosen
   sub-band, and **added into it**, scaled by a strength factor `alpha`:

   ```
   watermarked_band = original_band + alpha * watermark
   ```

4. The inverse DWT reconstructs the Y channel, which is merged back with
   the untouched color channels to produce the final watermarked image.

### This is a *non-blind* scheme

Extraction needs **the original, unwatermarked cover image** — not just the
watermarked one. Recovery is just algebra: run the same DWT on both images
and subtract:

```
recovered_watermark ≈ (watermarked_band - original_band) / alpha
```

This is a deliberate choice: it's far simpler to implement, explain, and
verify correct than a *blind* scheme (which embeds detectable patterns that
don't require the original at all), at the cost of needing to keep the
original cover image around. See [Limitations](#limitations--things-to-know)
below.

---

## Prerequisites

- **Python 3.10+**
- `pip` (and ideally a virtual environment tool — `venv` ships with Python)
- No GPU, database server, or external services required. The project uses
  SQLite (a single local file) purely for Django's built-in admin/session
  machinery — the watermarking feature itself doesn't touch the database.

Dependencies (see [`requirements.txt`](requirements.txt)):

```
Django>=4.2,<5.1
numpy>=1.24
Pillow>=10.0
```

---

## Setup

```bash
# 1. Get the code into a folder, then move into it
cd haar_watermark_django

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Apply Django's built-in migrations (admin/auth/session tables)
python manage.py migrate

# 5. Run the development server
python manage.py runserver
```

Then open **http://127.0.0.1:8000/** in your browser — it redirects
straight to the Embed page. (Full paths: `/watermark/embed/` and
`/watermark/extract/`.)

To stop the server, press `Ctrl+C`.

---

## Usage

### Embed a watermark

1. Go to **Embed watermark**.
2. Upload a **cover image** (the photo/image that will carry the hidden
   watermark) and a **watermark image** (a logo, a bit of bold text, or any
   image — simple, high-contrast watermarks survive best).
3. Pick an **alpha** (embedding strength) and a **sub-band** — the defaults
   (`alpha = 10`, sub-band `HL`) are a reasonable starting point.
4. Click **Embed watermark**. Download the resulting PNG.
5. **Keep your original cover image** — you'll need it, plus the same
   alpha and sub-band, to extract the watermark later.

### Extract a watermark

1. Go to **Extract watermark**.
2. Upload the **watermarked image** and the **original cover image** from
   step above.
3. Enter the **same alpha and sub-band** used when embedding.
4. Click **Extract watermark** to see and download the recovered watermark
   (grayscale, roughly half the width/height of the cover image).

> **Important:** always download/keep the watermarked image as **PNG**.
> JPEG re-compression perturbs exactly the high-frequency coefficients this
> scheme relies on and will corrupt or destroy the watermark. Likewise,
> resizing or cropping the watermarked image before extraction will hurt
> (or ruin) recovery.

---

## Using the algorithm without Django

`watermarking/utils.py` has no Django dependency, so you can use it
directly from a Python shell or script:

```python
from PIL import Image
from watermarking.utils import embed_watermark, extract_watermark

cover = Image.open("cover.png")
watermark = Image.open("logo.png")

watermarked = embed_watermark(cover, watermark, alpha=10.0, subband="HL")
watermarked.save("watermarked.png")  # must stay PNG (lossless)

# ... later, to recover it ...
watermarked = Image.open("watermarked.png")
cover = Image.open("cover.png")
recovered = extract_watermark(watermarked, cover, alpha=10.0, subband="HL")
recovered.save("recovered_watermark.png")
```

You can also run a quick, self-contained smoke test (no Django, no test
runner needed) straight from the file:

```bash
cd watermarking
python utils.py
# -> writes self_test_recovered_watermark.png
```

---

## Running the automated tests

The project includes Django `TestCase`s covering the wavelet transform
itself, the embed/extract algorithm (round-tripping, odd-sized images,
invisibility via PSNR, mismatched-parameter behavior, input validation),
and the views (page loads, a full embed POST, rejecting non-image uploads):

```bash
python manage.py test
```

---

## Project structure

```
haar_watermark_django/
├── manage.py
├── requirements.txt
├── README.md
├── db.sqlite3                      # created by `migrate`, Django admin/auth only
├── media/
│   └── outputs/                    # generated watermarked images / recovered watermarks
├── watermark_project/              # Django project (settings, URLs)
│   ├── settings.py
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
└── watermarking/                   # the actual app
    ├── utils.py                    # ← the Haar DWT algorithm (no Django dependency)
    ├── forms.py                    # upload forms (image, alpha, sub-band)
    ├── views.py                    # embed_view / extract_view
    ├── urls.py
    ├── models.py                   # intentionally empty — app is stateless
    ├── tests.py                    # unit tests for utils.py and the views
    └── templates/watermarking/
        ├── base.html
        ├── embed.html
        └── extract.html
```

---

## Limitations & things to know

- **Non-blind**: extraction requires the original cover image. If you need
  a scheme that can detect/extract a watermark from *only* the watermarked
  image (no original needed), that's a materially different algorithm
  (e.g. a blind spread-spectrum or quantization-index-modulation scheme) —
  out of scope here, but `utils.py` is a reasonable place to start from if
  you want to extend it.
- **Not robust against most real-world edits.** This implementation favors
  clarity over robustness. It will *not* reliably survive JPEG
  re-compression, resizing, cropping, rotation, or screenshotting. It is
  meant as a clear, working demonstration of DWT-domain watermarking, not
  a production anti-piracy tool.
- **Alpha and sub-band must match exactly** between embedding and
  extraction, or the recovered watermark will come out as noise.
- **Single-level transform only.** The recovered watermark's resolution is
  roughly half the cover image's width and height (a single-level 2D Haar
  DWT halves each dimension). Multi-level (recursive) decomposition is a
  natural next step if you want finer control over capacity vs. robustness.
- **Grayscale watermark only.** The watermark image is converted to
  grayscale before embedding; color information in the watermark itself is
  not preserved.

---

## Troubleshooting

- **"One of the uploaded files doesn't look like a valid image."** — the
  file either isn't actually an image or is corrupted; try re-exporting it.
- **Recovered watermark looks like pure noise** — double-check that the
  alpha and sub-band on the Extract page exactly match what you used on
  the Embed page, and that you uploaded the *original* PNG (not a
  re-compressed, resized, or otherwise re-saved copy).
- **`ModuleNotFoundError` when running `manage.py`** — make sure your
  virtual environment is activated and `pip install -r requirements.txt`
  completed without errors.
