"""OutputParticipation query resolvers."""

from typing import List

import strawberry
from kante.types import Info

from api import context, types, filters, order, pagination
from api.queries import _edges
from evidence import models as evidence_models
from graph_engine import input_models


def output_participation(info: Info, id: strawberry.ID) -> types.OutputParticipation:
    """Fetch one output participation edge by the id of the claim that made it.

    Resolved from the `Link` row, not from Apache AGE. The id a client holds is
    that row's primary key — `RetrievedEdge.unique_id` returns it for every
    row-backed edge, which is all of them — and this used to split it on the first
    hyphen to recover a graph name and an integer AGE edge id. Given a uuid that
    yielded a graph named after its first segment and `int()` over the rest:
    `invalid literal for int() with base 10`, on the very id the API had just
    handed out.

    It could not be made to work by parsing harder. An AGE edge carries no claim
    id and cannot: `project_edges` merges every assertion of one proposition onto
    a single edge, which is the point — agreement is countable in the evidence and
    a traversal still sees one connection.
    """
    controller = context.get_controller()

    edge = controller.get_relation_by_id(str(id), info=info, kind=evidence_models.Link.Kind.PARTICIPATES_AS_OUTPUT)
    if edge is None:
        raise ValueError(f"Output participation edge with ID {id} not found")

    return types.OutputParticipation(_value=edge)


def output_participations(
    info: Info,
    graph: strawberry.ID,
    filters: filters.ParticipationFilter | None = None,
    ordering: list[order.ParticipationOrder] | None = None,
    pagination: pagination.ParticipationPaginationInput | None = None,
) -> List[types.OutputParticipation]:
    """Every standing outputparticipation claim about an event this graph contains.

    Read from `evidence.Link`, not from Apache AGE. This returned nothing at all
    before, for the reason `input_participations` gives: it matched labels the
    projector never writes.

    Graph-scoped through `selector.instance_refs_for`, the same membership subquery
    every other view-scoped read uses — the event has to be in the graph, and
    `participation_key` stores the event as `target_ref` on both sides.
    """
    controller = context.get_controller()
    graph_model = context.get_accessible_graph(info, graph)

    filter_model = filters.to_pydantic() if filters else input_models.RelationFilters()
    ordering_models = [entry.to_pydantic() for entry in ordering] if ordering else []
    pagination_model = pagination.to_pydantic() if pagination else input_models.RelationPagination()

    links = _edges.links_in_graph(graph_model, evidence_models.Link.Kind.PARTICIPATES_AS_OUTPUT, ref_field="target_ref")
    rows = _edges.narrow(links, filter_model, ordering_models, pagination_model)

    return [types.OutputParticipation(_value=controller.retrieved_edge(link)) for link in rows]
