from core import models
from strawberry import auto
from django.db.models import Q
import strawberry_django


@strawberry_django.order_type(models.Category)
class CategoryOrder:
    label: auto
    id: auto


@strawberry_django.order_type(models.NodeCategory)
class NodeCategoryOrder(CategoryOrder):
    instance_kind: auto


@strawberry_django.order_type(models.EdgeCategory)
class EdgeCategoryOrder(CategoryOrder):
    instance_kind: auto


@strawberry_django.order_type(models.EntityCategory)
class EntityCategoryOrder(NodeCategoryOrder):
    label: auto
    id: auto


@strawberry_django.order_type(models.StructureCategory)
class StructureCategoryOrder(NodeCategoryOrder):
    label: auto
    id: auto


@strawberry_django.order_type(models.MetricCategory)
class MetricCategoryOrder(NodeCategoryOrder):
    label: auto
    id: auto


@strawberry_django.order_type(models.NaturalEventCategory)
class NaturalEventCategoryOrder(NodeCategoryOrder):
    label: auto
    id: auto


@strawberry_django.order_type(models.ProtocolEventCategory)
class ProtocolEventCategoryOrder(NodeCategoryOrder):
    label: auto
    id: auto


@strawberry_django.order_type(models.RelationCategory)
class RelationCategoryOrder(EdgeCategoryOrder):
    label: auto
    id: auto
