from typing import Optional
from core import models
from strawberry import auto
import strawberry_django
import kante
from strawberry_django.ordering import Ordering
import strawberry


@kante.input(description="Ordering options for graph table queries")
class PropertyOrder:
    key: str = strawberry.field(description="The property key to order by")
    direction: Ordering = strawberry.field(description="The direction to order (ASC or DESC)")


@kante.input(description="Ordering options for entity queries")
class EntityOrder:
    """Ordering options for entity queries."""

    created_at: Optional[Ordering] = kante.field(default=None, description="Order by creation timestamp")
    category: Optional[Ordering] = kante.field(default=None, description="Order by entity kind/type")
    id: Optional[Ordering] = kante.field(default=None, description="Order by entity ID")
    property: Optional[PropertyOrder] = kante.field(default=None, description="Order by a specific property value (requires 'has_property' filter)")


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


@strawberry_django.order_type(models.GraphQuery)
class GraphQueryOrder:
    label: auto
    id: auto


@strawberry_django.order_type(models.GraphTableQuery)
class GraphTableQueryOrder:
    label: auto
    id: auto


@strawberry_django.order_type(models.GraphNodesQuery)
class GraphNodesQueryOrder:
    label: auto
    id: auto


@strawberry_django.order_type(models.GraphPairsQuery)
class GraphPairsQueryOrder:
    label: auto
    id: auto
