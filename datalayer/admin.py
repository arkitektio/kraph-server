from django.contrib import admin

# Register your models here.
from datalayer import models


admin.site.register(models.S3Store)
admin.site.register(models.MediaStore)
admin.site.register(models.BigFileStore)
