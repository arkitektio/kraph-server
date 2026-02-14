from typing import Optional
from core import models
from strawberry import auto
import strawberry_django
import kante
from strawberry_django.ordering import Ordering
import strawberry


@kante.input(description="Ordering options for entity queries")
class EntityOrder:
    """Ordering options for entity queries."""

    created_at: Optional[Ordering] = kante.field(default=None, description="Order by creation timestamp")
    category: Optional[Ordering] = kante.field(default=None, description="Order by entity kind/type")
    id: Optional[Ordering] = kante.field(default=None, description="Order by entity ID")


@strawberry_django.order_type(models.Graph)
class GraphOrder:
    name: auto
    id: auto


@strawberry_django.order_type(models.Category)
class CategoryOrder:
    label: auto
    id: auto


@strawberry_django.order_type(models.MaterializedEdge)
class MaterializedEdgeOrder:
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


@strawberry_django.order_type(models.MeasurementCategory)
class MeasurementCategoryOrder(CategoryOrder):
    label: auto
    id: auto
