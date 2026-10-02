from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", RedirectView.as_view(pattern_name="watermarking:embed", permanent=False)),
    path("watermark/", include("watermarking.urls")),
]

if settings.DEBUG:
    # Serve uploaded/generated media files during local development.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
