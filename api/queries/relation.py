"""Relation query resolvers."""

from typing import List

import strawberry
from kante.types import Info

from api import context, types, filters, order, pagination
from api.queries import _edges
from evidence import models as evidence_models
from graph_engine import input_models
from core import models


def relation(info: Info, id: strawberry.ID) -> types.Relation:
    """Fetch one relation by the id of the claim that made it.

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

    edge = controller.get_relation_by_id(str(id), info=info, kind=evidence_models.Link.Kind.RELATION)
    if edge is None:
        raise ValueError(f"Relation with ID {id} not found")

    return types.Relation(_value=edge)


def relations(
    info: Info,
    relation_category_id: strawberry.ID,
    filters: filters.RelationFilter | None = None,
    ordering: list[order.RelationOrder] | None = None,
    pagination: pagination.RelationPaginationInput | None = None,
) -> List[types.Relation]:
    """Every standing relation claim stated in this category's word.

    Read from `evidence.Link`, not from Apache AGE. Relations are the one edge kind
    Apache AGE genuinely draws, so this query
    did return rows — but with `{graph}:{ageId}` ids the singular fetcher could not
    accept. Reading the claim fixes the identity as well as the scope.

    Scoped by the category's **term**, so two graphs declaring the same word list
    the same claims — see `api/queries/_edges.py`.

    Authorized against the **organization**, which is the grain the answer is at.
    It used to be `get_accessible_graph(category.graph)` — a check one grain narrower
    than the list, asserting that the view whose word this is owns claims that belong
    to the tenant. The organization comes from the category's graph rather than from
    the request for the reason `GraphController._assert_can_access` gives: the client
    names a primary key and never names a tenant, so authorization has to come from
    what the id points at.
    """
    controller = context.get_controller()

    category = models.RelationCategory.objects.filter(id=relation_category_id).first()
    if category is None:
        raise ValueError(f"Relation category {relation_category_id} not found")

    organization = category.graph.organization
    context.assert_can_access_organization(info, organization)

    filter_model = filters.to_pydantic() if filters else input_models.RelationFilters()
    ordering_models = [entry.to_pydantic() for entry in ordering] if ordering else []
    pagination_model = pagination.to_pydantic() if pagination else input_models.RelationPagination()

    links = _edges.links_for_category(organization, category, evidence_models.Link.Kind.RELATION)
    rows = _edges.narrow(links, filter_model, ordering_models, pagination_model)

    return [types.Relation(_value=controller.retrieved_edge(link, category=category)) for link in rows]
