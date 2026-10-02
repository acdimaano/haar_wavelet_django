from django import forms

from .utils import DEFAULT_ALPHA, DEFAULT_SUBBAND, SUPPORTED_SUBBANDS

SUBBAND_CHOICES = [
    ("LL", "LL — approximation (coarse brightness)"),
    ("LH", "LH — horizontal detail"),
    ("HL", "HL — vertical detail (default, good balance)"),
    ("HH", "HH — diagonal detail (most invisible, least robust)"),
]

_ALPHA_HELP = (
    "Embedding strength. Higher values recover more cleanly but are more "
    "visible in the cover image. Must be the same value you use later when "
    "extracting this watermark."
)
_SUBBAND_HELP = (
    "Which wavelet sub-band to embed into. Must match at extraction time."
)


class EmbedForm(forms.Form):
    cover_image = forms.ImageField(
        label="Cover image",
        help_text="The image that will carry the hidden watermark.",
    )
    watermark_image = forms.ImageField(
        label="Watermark image",
        help_text=(
            "The image to hide (e.g. a logo or a bit of bold text). It will "
            "be converted to grayscale and resized automatically — simple, "
            "high-contrast watermarks survive best."
        ),
    )
    alpha = forms.FloatField(
        label="Alpha (embedding strength)",
        initial=DEFAULT_ALPHA,
        min_value=0.1,
        max_value=100,
        help_text=_ALPHA_HELP,
    )
    subband = forms.ChoiceField(
        label="DWT sub-band",
        choices=SUBBAND_CHOICES,
        initial=DEFAULT_SUBBAND,
        help_text=_SUBBAND_HELP,
    )

    def clean_subband(self):
        value = self.cleaned_data["subband"]
        if value not in SUPPORTED_SUBBANDS:
            raise forms.ValidationError("Unsupported sub-band.")
        return value


class ExtractForm(forms.Form):
    watermarked_image = forms.ImageField(
        label="Watermarked image",
        help_text="The image produced by the Embed page (must be the PNG, not a re-compressed copy).",
    )
    original_image = forms.ImageField(
        label="Original cover image",
        help_text=(
            "The same cover image you used when embedding, before the "
            "watermark was added. This scheme needs it to recover the watermark."
        ),
    )
    alpha = forms.FloatField(
        label="Alpha (embedding strength)",
        initial=DEFAULT_ALPHA,
        min_value=0.1,
        max_value=100,
        help_text="Must be exactly the value used when this watermark was embedded.",
    )
    subband = forms.ChoiceField(
        label="DWT sub-band",
        choices=SUBBAND_CHOICES,
        initial=DEFAULT_SUBBAND,
        help_text="Must be exactly the sub-band used when this watermark was embedded.",
    )

    def clean_subband(self):
        value = self.cleaned_data["subband"]
        if value not in SUPPORTED_SUBBANDS:
            raise forms.ValidationError("Unsupported sub-band.")
        return value
