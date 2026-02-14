from typing import Optional

from core import models
from strawberry import auto
import strawberry_django
import kante
from strawberry_django.ordering import Ordering
import strawberry
from graph_engine import scalars, input_models


@kante.pydantic_input(input_models.PropertyOrder, all_fields=True, description="Ordering options for graph table queries")
class PropertyOrder:
    """Property odering options for graph table queries."""


@kante.pydantic_input(input_models.EntityOrder, all_fields=True, description="Ordering options for entity queries")
class EntityOrder:
    """Ordering options for entity queries."""


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
