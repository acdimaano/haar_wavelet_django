# This app is intentionally stateless: images are processed in memory and
# only the generated output image is written to disk (under MEDIA_ROOT/outputs),
# so there are no database models to define here.
#
# If you extend this project to keep a history of watermarking jobs, this is
# where you'd add a model, e.g.:
#
#     from django.db import models
#
#     class WatermarkJob(models.Model):
#         created_at = models.DateTimeField(auto_now_add=True)
#         alpha = models.FloatField()
#         subband = models.CharField(max_length=2)
#         output_image = models.ImageField(upload_to="outputs/")
