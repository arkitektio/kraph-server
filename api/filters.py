import datetime
import strawberry
from core import models, enums, scalars
from strawberry import auto
import strawberry_django as kante
from django.db.models import Q
import kante


@kante.filter_type(models.Category)
class CategoryFilter:
    id: strawberry.auto
    label: strawberry.auto

    @kante.filter_field(description="Filter by list of IDs")
    def pinned(self, info: kante.Info, value: bool, prefix: str) -> Q:
        return Q(**{f"{prefix}__pinned_by": info.context.request.user})

    @kante.filter_field(description="Filter by list of IDs")
    def search(self, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}label__search": value})


@kante.filter_type(models.EntityCategory)
class EntityCategoryFilter(CategoryFilter):
    instance_kind: strawberry.auto
