import datetime
import strawberry
from core import models, enums, scalars
from strawberry import auto
import strawberry_django as kante
from django.db.models import Q
import kante


print("Test")


@kante.filter_type(models.EntityCategory)
class EntityCategoryFilter:
    label: strawberry.auto
    id: strawberry.auto

    @kante.filter_field(description="Filter by list of IDs")
    def pinned(self, info: kante.Info, value: bool, prefix: str) -> Q:
        return Q(**{f"{prefix}_pinned_by": info.context.request.user}) if value else Q()

    @kante.filter_field(description="Filter by list of IDs")
    def search(self, info: kante.Info, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}__label__search": value}) if value else Q()
