from django.urls import path

from . import views

app_name = "watermarking"

urlpatterns = [
    path("embed/", views.embed_view, name="embed"),
    path("extract/", views.extract_view, name="extract"),
]
