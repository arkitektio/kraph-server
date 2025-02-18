from django.contrib import admin

# Register your models here.
from core import models
from simple_history.admin import SimpleHistoryAdmin


class HistoryAdmin(SimpleHistoryAdmin):
    list_display = ["id"]
    history_list_display = ["name", "user"]
    search_fields = ["name", "user__username"]


admin.site.register(models.Ontology)
admin.site.register(models.Graph)
admin.site.register(models.S3Store)
