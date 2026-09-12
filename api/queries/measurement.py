"""Measurement query resolvers."""

from typing import List

import strawberry
from kante.types import Info

from api import context, types, filters, order, pagination
from api.queries import _edges
from evidence import models as evidence_models
from graph_engine import input_models
from core import models


def measurement(info: Info, id: strawberry.ID) -> types.Measurement:
    """Fetch one measurement by the id of the claim that made it.

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

    edge = controller.get_relation_by_id(str(id), info=info, kind=evidence_models.Link.Kind.MEASUREMENT)
    if edge is None:
        raise ValueError(f"Measurement with ID {id} not found")

    return types.Measurement(_value=edge)


def measurements(
    info: Info,
    measurement_category_id: strawberry.ID,
    filters: filters.MeasurementFilter | None = None,
    ordering: list[order.MeasurementOrder] | None = None,
    pagination: pagination.MeasurementPaginationInput | None = None,
) -> List[types.Measurement]:
    """Every standing measurement claim stated in this category's word.

    Read from `evidence.Link`, not from Apache AGE. This returned nothing at all
    before: a measurement has **no AGE edge** —
    `assertMeasurementExists` says so in its own description — so the Cypher
    `MATCH ()-[r]->()` it ran could not match one.

    Scoped by the category's **term**, so two graphs declaring the same word list
    the same claims — see `api/queries/_edges.py`.

    Authorized against the **organization**, the grain the answer is at, and reached
    through the category's graph rather than through the request — see `relations`
    for why both halves of that matter.
    """
    controller = context.get_controller()

    category = models.MeasurementCategory.objects.filter(id=measurement_category_id).first()
    if category is None:
        raise ValueError(f"Measurement category {measurement_category_id} not found")

    organization = category.graph.organization
    context.assert_can_access_organization(info, organization)

    filter_model = filters.to_pydantic() if filters else input_models.MeasurementFilters()
    ordering_models = [entry.to_pydantic() for entry in ordering] if ordering else []
    pagination_model = pagination.to_pydantic() if pagination else input_models.MeasurementPagination()

    links = _edges.links_for_category(organization, category, evidence_models.Link.Kind.MEASUREMENT)
    rows = _edges.narrow(links, filter_model, ordering_models, pagination_model)

    return [types.Measurement(_value=controller.retrieved_edge(link, category=category)) for link in rows]
