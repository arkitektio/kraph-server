from typing import Optional

from core import models
from strawberry import auto
import strawberry_django
import kante
from strawberry_django.ordering import Ordering
from graph_engine import input_models


# The node, edge and structure orderings below advertise `createdAt` and `id`
# and nothing else, deliberately. They used to expose the pydantic models whole
# (`all_fields=True`), which dragged in `property` and `category` — and those
# were a lottery: `property` raised on the node lists
# (`_nodes.refuse_drawing_filters`), was silently dropped on the edge lists
# (`_edges.narrow` never received the ordering), and was silently reinterpreted
# as ordering by `object` on `structures`. The schema says what the resolvers
# answer now. The pydantic fields stay: `EntityOrder.property` is consumed by
# the drawing-scoped `GraphController.list_entities_for_category`, which no
# GraphQL field is built on.
#
# `PropertyOrder` and `MetricOrder` wrappers used to sit here too — the first
# was only ever the type of the removed `property` fields, the second was
# referenced by no resolver (`metrics(metricKindId:)` takes no ordering, see
# `api/queries/metric.py`).


@kante.pydantic_input(input_models.EntityOrder, description="Ordering options for entity queries")
class EntityOrder:
    """Ordering options for entity queries."""

    created_at: Optional[Ordering] = kante.field(default=None, description="Order by creation timestamp")
    id: Optional[Ordering] = kante.field(default=None, description="Order by entity ID")


@kante.pydantic_input(input_models.NodeOrder, description="Ordering options for node queries")
class NodeOrder:
    """Ordering options for node queries."""

    created_at: Optional[Ordering] = kante.field(default=None, description="Order by creation timestamp")
    id: Optional[Ordering] = kante.field(default=None, description="Order by node ID")


@kante.pydantic_input(input_models.StructureOrder, description="Ordering options for structure queries")
class StructureOrder:
    """Ordering options for structure queries."""

    created_at: Optional[Ordering] = kante.field(default=None, description="Order by creation timestamp")
    id: Optional[Ordering] = kante.field(default=None, description="Order by structure ID")


@kante.pydantic_input(input_models.NaturalEventOrder, description="Ordering options for natural event queries")
class NaturalEventOrder:
    """Ordering options for natural event queries."""

    created_at: Optional[Ordering] = kante.field(default=None, description="Order by creation timestamp")
    id: Optional[Ordering] = kante.field(default=None, description="Order by natural event ID")


@kante.pydantic_input(input_models.ProtocolEventOrder, description="Ordering options for protocol event queries")
class ProtocolEventOrder:
    """Ordering options for protocol event queries."""

    created_at: Optional[Ordering] = kante.field(default=None, description="Order by creation timestamp")
    id: Optional[Ordering] = kante.field(default=None, description="Order by protocol event ID")


@kante.pydantic_input(input_models.MeasurementOrder, description="Ordering options for measurement queries")
class MeasurementOrder:
    """Ordering options for measurement queries."""

    created_at: Optional[Ordering] = kante.field(default=None, description="Order by creation timestamp")
    id: Optional[Ordering] = kante.field(default=None, description="Order by measurement ID")


@kante.pydantic_input(input_models.StructureRelationOrder, description="Ordering options for structure relation queries")
class StructureRelationOrder:
    """Ordering options for structure relation queries."""

    created_at: Optional[Ordering] = kante.field(default=None, description="Order by creation timestamp")
    id: Optional[Ordering] = kante.field(default=None, description="Order by structure relation ID")


@kante.pydantic_input(input_models.RelationOrder, description="Ordering options for participation queries")
class ParticipationOrder:
    """Ordering options for participation queries — see `filters.ParticipationFilter`."""

    created_at: Optional[Ordering] = kante.field(default=None, description="Order by creation timestamp")
    id: Optional[Ordering] = kante.field(default=None, description="Order by participation ID")


@kante.pydantic_input(input_models.RelationOrder, description="Ordering options for relation queries")
class RelationOrder:
    """Ordering options for relation queries."""

    created_at: Optional[Ordering] = kante.field(default=None, description="Order by creation timestamp")
    id: Optional[Ordering] = kante.field(default=None, description="Order by relation ID")


@strawberry_django.order_type(models.Graph)
class GraphOrder:
    name: auto
    id: auto


@strawberry_django.order_type(models.Category)
class CategoryOrder:
    label: auto
    id: auto


@strawberry_django.order_type(models.Category)
class NodeCategoryOrder(CategoryOrder):
    instance_kind: auto


@strawberry_django.order_type(models.Category)
class EdgeCategoryOrder(CategoryOrder):
    instance_kind: auto


@strawberry_django.order_type(models.Category)
class EntityCategoryOrder(NodeCategoryOrder):
    label: auto
    id: auto


# `TermOrder`, `StructureKindOrder` and `MetricKindOrder` used to sit here. The
# vocabulary lists accepted them and applied nothing — the canonical order is
# word order (`kinds.py`) — and the `ordering=` slots on the corresponding
# `kante.django_type` declarations surfaced nothing either, so both references
# went together.


@strawberry_django.order_type(models.Category)
class NaturalEventCategoryOrder(NodeCategoryOrder):
    label: auto
    id: auto


@strawberry_django.order_type(models.Category)
class ProtocolEventCategoryOrder(NodeCategoryOrder):
    label: auto
    id: auto


@strawberry_django.order_type(models.Category)
class RelationCategoryOrder(EdgeCategoryOrder):
    label: auto
    id: auto


@strawberry_django.order_type(models.Category)
class StructureRelationCategoryOrder(EdgeCategoryOrder):
    label: auto
    id: auto


@strawberry_django.order_type(models.Category)
class MeasurementCategoryOrder(CategoryOrder):
    label: auto
    id: auto


@strawberry_django.order_type(models.GraphQuery)
class GraphQueryOrder:
    label: auto
    id: auto


@strawberry_django.order_type(models.GraphQuery)
class GraphTableQueryOrder:
    label: auto
    id: auto


@strawberry_django.order_type(models.GraphQuery)
class GraphNodesQueryOrder:
    label: auto
    id: auto


@strawberry_django.order_type(models.GraphQuery)
class GraphPairsQueryOrder:
    label: auto
    id: auto


@strawberry_django.order_type(models.GraphQuery)
class GraphPathQueryOrder:
    label: auto
    id: auto


@strawberry_django.order_type(models.NodeQuery)
class NodeQueryOrder:
    label: auto
    id: auto


@strawberry_django.order_type(models.NodeQuery)
class NodeTableQueryOrder:
    label: auto
    id: auto


@strawberry_django.order_type(models.NodeQuery)
class NodePairsQueryOrder:
    label: auto
    id: auto


@strawberry_django.order_type(models.NodeQuery)
class NodePathQueryOrder:
    label: auto
    id: auto


@strawberry_django.order_type(models.EdgeQuery)
class EdgeQueryOrder:
    label: auto
    id: auto


@strawberry_django.order_type(models.EdgeQuery)
class EdgeTableQueryOrder:
    label: auto
    id: auto


@strawberry_django.order_type(models.EdgeQuery)
class EdgePairsQueryOrder:
    label: auto
    id: auto


@strawberry_django.order_type(models.EdgeQuery)
class EdgePathQueryOrder:
    label: auto
    id: auto


@strawberry_django.order_type(models.ScatterPlot)
class ScatterPlotOrder:
    name: auto
    id: auto
