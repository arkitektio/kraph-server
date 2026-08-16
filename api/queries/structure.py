"""
Structure query resolvers.
"""

from typing import Optional, List
from kante.types import Info
import strawberry

from api import types, context, filters, order, pagination
from core import models
from evidence import models as evidence_models
from graph_engine import scalars
from graph_engine import input_models


def structure_by_identifier(
    info: Info,
    identifier: scalars.StructureIdentifier,
    object: scalars.StructureObject,
) -> types.Structure:
    """The structure for one external datum, by identifier and object.

    **No graph.** A structure is idempotent by `(organization, identifier,
    object)` and has no vertex in any projection, so naming a view selected
    nothing — see `GraphController.get_structure`. The sibling
    `structures(structureKindId:)` was already de-graphed on the same grounds.
    """
    controller = context.get_controller()
    organization = context.get_active_organization(info)

    response = controller.get_structure(
        organization=organization,
        identifier=identifier,
        object=object,
        info=info,
    )

    return types.Structure(_value=response)


def structure(
    info: Info,
    id: scalars.GraphID,
) -> types.Structure:
    """
    Fetch a specific structure by its evidence ID.

    Structures live in the relational evidence base and are scoped to the
    organization, so the id is a bare primary key with no graph component to
    split out. The controller resolves the row and then authorizes the caller
    against that row's organization.

    Args:
        info: Strawberry Info context
        id: The structure's evidence primary key

    Returns:
        Structure object

    Raises:
        ValueError: if no structure has that id
    """
    controller = context.get_controller()

    return types.Structure(_value=controller.get_structure_by_id(str(id), info))


def structures(
    info: Info,
    structure_kind_id: strawberry.ID | None = None,
    filters: filters.StructureFilter | None = None,
    ordering: list[order.StructureOrder] | None = None,
    pagination: pagination.StructurePaginationInput | None = None,
) -> List[types.Structure]:
    """List structures in the organization, optionally narrowed to one kind.

    `structure_kind_id` is optional now. Structures belong to the organization,
    so listing them does not need a kind any more than it needs a graph — and the
    old signature reached `structure_category.graph` to pick a projection to
    query, which no longer exists.
    """
    controller = context.get_controller()
    organization = context.get_active_organization(info)

    filter_model = filters.to_pydantic() if filters else input_models.StructureFilters()
    if structure_kind_id is not None:
        kind = evidence_models.StructureKind.objects.for_organization(organization).filter(id=structure_kind_id).first()
        if kind is None:
            raise ValueError(f"Structure kind {structure_kind_id} not found")
        filter_model.category = kind.identifier

    ordering_models = [order.to_pydantic() for order in ordering] if ordering else []
    pagination_model = pagination.to_pydantic() if pagination else input_models.StructurePagination()

    result = controller.list_structures(
        organization=organization,
        filters=filter_model,
        pagination=pagination_model,
        ordering=ordering_models,
        info=info,
    )

    return [types.Structure(_value=structure) for structure in result]


def informing_structures(
    info: Info,
    entity_id: str,
) -> List[types.Structure]:
    """
    Fetch all structures that inform a given entity.

    Args:
        info: Strawberry Info context
        entity_id: The entity's string ID

    Returns:
        List of Structure objects
    """
    controller = context.get_controller()

    # No graph. INFORMS is organization-grain, so there was never a view to pick
    # — and picking one meant `_graph_for_node`, which returns an arbitrary
    # declarer among the graphs that speak the node's word.
    node = controller._resolve_node(entity_id, info)

    responses = controller.get_informing_structures(node, info=info)
    return [types.Structure(_value=r) for r in responses]
