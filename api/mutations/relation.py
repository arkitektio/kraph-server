"""
Relation mutation resolvers.
"""

from kante.types import Info
from api import types, inputs, context
from core import models
from graph_engine import scalars


def delete_relation(info: Info, input: inputs.DeleteRelationInput) -> scalars.GraphID:
    """
    Delete a relation by its composite ID. Only the owner of the graph or an admin can delete a relation.

    Args:
        info: Strawberry Info context
        input: Composite ID of the relation to delete (e.g., "1-abc123-def456-...")

    Returns:
        The ID of the deleted relation
    """
    controller = context.get_controller()

    model = input.to_pydantic()  # Validate input with Pydantic models
    # Extract graph ID and local ID from composite ID
    graph_id = context.extract_graph_id(model.id)
    local_id = context.extract_node_id(model.id)

    graph = context.get_accessible_graph(info, graph_id)

    controller.delete_relation(
        graph,
        relation_id=local_id,
        info=info,
    )

    return model.id


def archive_relation(info: Info, input: inputs.ArchiveRelationInput) -> types.Relation:
    """
    Archive (soft delete) a relation by its composite ID.

    Args:
        info: Strawberry Info context
        input: Composite ID of the relation to archive (e.g., "1-abc123-def456-...")

    Returns:
        The ID of the archived relation
    """
    controller = context.get_controller()

    model = input.to_pydantic()  # Validate input with Pydantic models
    # Extract graph ID and local ID from composite ID
    graph_id = context.extract_graph_id(model.id)
    local_id = context.extract_node_id(model.id)

    graph = context.get_accessible_graph(info, graph_id)

    controller.archive_relation(
        graph,
        relation_id=local_id,
        info=info,
    )

    archived = controller.get_relation_by_id(local_id)
    assert archived is not None, "Relation was archived but could not be loaded"

    return types.Relation(_value=archived)
