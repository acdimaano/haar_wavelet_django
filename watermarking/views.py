import uuid
from pathlib import Path

from django.conf import settings
from django.shortcuts import render
from PIL import Image, UnidentifiedImageError

from .forms import EmbedForm, ExtractForm
from .utils import WatermarkError, embed_watermark, extract_watermark

OUTPUT_SUBDIR = "outputs"


def _save_output_image(image: Image.Image, prefix: str) -> str:
    """Save a generated PIL image under MEDIA_ROOT/outputs and return its URL."""
    output_dir = Path(settings.MEDIA_ROOT) / OUTPUT_SUBDIR
    output_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{prefix}_{uuid.uuid4().hex}.png"
    image.save(output_dir / filename, format="PNG")

    return f"{settings.MEDIA_URL}{OUTPUT_SUBDIR}/{filename}"


def embed_view(request):
    result_url = None
    error = None

    if request.method == "POST":
        form = EmbedForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                cover = Image.open(form.cleaned_data["cover_image"])
                watermark = Image.open(form.cleaned_data["watermark_image"])
                watermarked = embed_watermark(
                    cover,
                    watermark,
                    alpha=form.cleaned_data["alpha"],
                    subband=form.cleaned_data["subband"],
                )
                result_url = _save_output_image(watermarked, "watermarked")
            except UnidentifiedImageError:
                error = "One of the uploaded files doesn't look like a valid image."
            except WatermarkError as exc:
                error = str(exc)
            except Exception as exc:  # pragma: no cover - defensive catch-all
                error = f"Something went wrong while embedding the watermark: {exc}"
    else:
        form = EmbedForm()

    return render(
        request,
        "watermarking/embed.html",
        {"form": form, "result_url": result_url, "error": error},
    )


def extract_view(request):
    result_url = None
    error = None

    if request.method == "POST":
        form = ExtractForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                watermarked = Image.open(form.cleaned_data["watermarked_image"])
                original = Image.open(form.cleaned_data["original_image"])
                recovered = extract_watermark(
                    watermarked,
                    original,
                    alpha=form.cleaned_data["alpha"],
                    subband=form.cleaned_data["subband"],
                )
                result_url = _save_output_image(recovered, "recovered_watermark")
            except UnidentifiedImageError:
                error = "One of the uploaded files doesn't look like a valid image."
            except WatermarkError as exc:
                error = str(exc)
            except Exception as exc:  # pragma: no cover - defensive catch-all
                error = f"Something went wrong while extracting the watermark: {exc}"
    else:
        form = ExtractForm()

    return render(
        request,
        "watermarking/extract.html",
        {"form": form, "result_url": result_url, "error": error},
    )
