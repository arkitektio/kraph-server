from core import models
from strawberry import auto
from django.db.models import Q
import strawberry_django


@strawberry_django.order_type(models.EntityCategory)
class EntityCategoryOrder:
    label: auto
    id: auto
