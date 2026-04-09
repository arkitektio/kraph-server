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


@kante.pydantic_input(input_models.NodeOrder, all_fields=True, description="Ordering options for node queries")
class NodeOrder:
    """Ordering options for node queries."""


@kante.pydantic_input(input_models.StructureOrder, all_fields=True, description="Ordering options for structure queries")
class StructureOrder:
    """Ordering options for structure queries."""


@kante.pydantic_input(input_models.MetricOrder, all_fields=True, description="Ordering options for metric queries")
class MetricOrder:
    """Ordering options for metric queries."""


@kante.pydantic_input(input_models.NaturalEventOrder, all_fields=True, description="Ordering options for natural event queries")
class NaturalEventOrder:
    """Ordering options for natural event queries."""


@kante.pydantic_input(input_models.ProtocolEventOrder, all_fields=True, description="Ordering options for protocol event queries")
class ProtocolEventOrder:
    """Ordering options for protocol event queries."""


@kante.pydantic_input(input_models.MeasurementOrder, all_fields=True, description="Ordering options for measurement queries")
class MeasurementOrder:
    """Ordering options for measurement queries."""


@kante.pydantic_input(input_models.StructureRelationOrder, all_fields=True, description="Ordering options for structure relation queries")
class StructureRelationOrder:
    """Ordering options for structure relation queries."""


@kante.pydantic_input(input_models.RelationOrder, all_fields=True, description="Ordering options for relation queries")
class RelationOrder:
    """Ordering options for relation queries."""


@strawberry_django.order_type(models.Graph)
class GraphOrder:
    name: auto
    id: auto


@strawberry_django.order_type(models.Category)
class CategoryOrder:
    label: auto
    id: auto


@strawberry_django.order_type(models.CategoryTag)
class CategoryTagOrder:
    name: auto
    id: auto


@strawberry_django.order_type(models.MaterializedEdge)
class MaterializedEdgeOrder:
    id: auto


@strawberry_django.order_type(models.MaterializedStructureRelationEdge)
class MaterializedStructureRelationEdgeOrder:
    id: auto


@strawberry_django.order_type(models.MaterializedRelationEdge)
class MaterializedRelationEdgeOrder:
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


@strawberry_django.order_type(models.StructureRelationCategory)
class StructureRelationCategoryOrder(EdgeCategoryOrder):
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


@strawberry_django.order_type(models.GraphPathQuery)
class GraphPathQueryOrder:
    label: auto
    id: auto


@strawberry_django.order_type(models.NodeQuery)
class NodeQueryOrder:
    label: auto
    id: auto


@strawberry_django.order_type(models.NodeTableQuery)
class NodeTableQueryOrder:
    label: auto
    id: auto


@strawberry_django.order_type(models.NodePairsQuery)
class NodePairsQueryOrder:
    label: auto
    id: auto


@strawberry_django.order_type(models.NodePathQuery)
class NodePathQueryOrder:
    label: auto
    id: auto


@strawberry_django.order_type(models.EdgeQuery)
class EdgeQueryOrder:
    label: auto
    id: auto


@strawberry_django.order_type(models.EdgeTableQuery)
class EdgeTableQueryOrder:
    label: auto
    id: auto


@strawberry_django.order_type(models.EdgePairsQuery)
class EdgePairsQueryOrder:
    label: auto
    id: auto


@strawberry_django.order_type(models.EdgePathQuery)
class EdgePathQueryOrder:
    label: auto
    id: auto


@strawberry_django.order_type(models.ScatterPlot)
class ScatterPlotOrder:
    name: auto
    id: auto
