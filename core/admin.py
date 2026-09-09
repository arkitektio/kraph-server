from django.contrib import admin

from core import models

admin.site.register(models.Graph)
admin.site.register(models.EntityCategory)
admin.site.register(models.NaturalEventCategory)
admin.site.register(models.ProtocolEventCategory)
admin.site.register(models.RelationCategory)
admin.site.register(models.MeasurementCategory)
admin.site.register(models.StructureRelationCategory)
admin.site.register(models.GraphSchema)
admin.site.register(models.GraphQuery)
