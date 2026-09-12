"""StructureRelation query resolvers."""

from typing import List

import strawberry
from kante.types import Info

from api import context, types, filters, order, pagination
from api.queries import _edges
from evidence import models as evidence_models
from graph_engine import input_models
from core import models


def structure_relation(info: Info, id: strawberry.ID) -> types.StructureRelation:
    """Fetch one structure relation by the id of the claim that made it.

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

    edge = controller.get_relation_by_id(str(id), info=info, kind=evidence_models.Link.Kind.STRUCTURE_RELATION)
    if edge is None:
        raise ValueError(f"Structure relation with ID {id} not found")

    return types.StructureRelation(_value=edge)


def structure_relations(
    info: Info,
    structure_relation_category_id: strawberry.ID,
    filters: filters.StructureRelationFilter | None = None,
    ordering: list[order.StructureRelationOrder] | None = None,
    pagination: pagination.StructureRelationPaginationInput | None = None,
) -> List[types.StructureRelation]:
    """Every standing structurerelation claim stated in this category's word.

    Read from `evidence.Link`, not from Apache AGE. This returned nothing at all
    before: neither endpoint of a structure relation has a vertex, so there was no
    edge in the projection to match.

    Scoped by the category's **term**, so two graphs declaring the same word list
    the same claims — see `api/queries/_edges.py`.

    Authorized against the **organization**, the grain the answer is at, and reached
    through the category's graph rather than through the request — see `relations`
    for why both halves of that matter.
    """
    controller = context.get_controller()

    category = models.StructureRelationCategory.objects.filter(id=structure_relation_category_id).first()
    if category is None:
        raise ValueError(f"StructureRelation category {structure_relation_category_id} not found")

    organization = category.graph.organization
    context.assert_can_access_organization(info, organization)

    filter_model = filters.to_pydantic() if filters else input_models.StructureRelationFilters()
    ordering_models = [entry.to_pydantic() for entry in ordering] if ordering else []
    pagination_model = pagination.to_pydantic() if pagination else input_models.StructureRelationPagination()

    links = _edges.links_for_category(organization, category, evidence_models.Link.Kind.STRUCTURE_RELATION)
    rows = _edges.narrow(links, filter_model, ordering_models, pagination_model)

    return [types.StructureRelation(_value=controller.retrieved_edge(link, category=category)) for link in rows]
