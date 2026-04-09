"""
Relation mutation resolvers.
"""

from kante.types import Info
from api import types, inputs, context
from core import models
from graph_engine import scalars


def create_relation(info: Info, input: inputs.CreateRelationInput) -> types.Relation:
    """
    Create a new relation between two entities with optional supporting evidence.

    Relations are edges between entities that can be backed by evidence
    (e.g., ROI overlaps that prove a synapse connection). Properties on
    the relation are automatically derived from the evidence according
    to the graph schema's materialization rules.

    Args:
        info: Strawberry Info context
        input: RelationCreationInput (pydantic-validated)

    Returns:
        RelationCreationResult with the created relation
    """
    # Convert strawberry-pydantic input to pydantic model
    payload = input.to_pydantic()

    # Get controller from source entity's graph
    controller = context.get_controller()

    # Extract the actual entity IDs from the composite IDs
    # The controller expects just the entity UUID, not the composite ID
    graph1 = context.extract_graph_id(payload.source_id)  # Validate graph exists and get graph context
    graph2 = context.extract_graph_id(payload.target_id)  # Validate graph exists and get graph context

    if graph1 != graph2:
        raise ValueError("Source and target entities must belong to the same graph")
    context.extract_node_id(payload.source_id)
    context.extract_node_id(payload.target_id)

    source_graph = context.get_accessible_graph(info, graph1)
    target_graph = context.get_accessible_graph(info, graph2)
    assert source_graph.id == target_graph.id, "Source and target entities must belong to the same graph"

    relation = models.RelationCategory.objects.get(id=payload.category)  # Validate relation category exists
    context.validate_graph_access(info, relation.graph)

    assert relation.graph.get_age_name() == graph1, "Relation category must belong to the same graph as the entities"

    result = controller.create_relation(
        category=relation,
        payload=payload,
        info=info,
    )

    return types.Relation(_value=result)


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


def update_relation(info: Info, input: inputs.UpdateRelationInput) -> types.Relation:
    """
    Update a relation by archiving the current edge and creating a new one in the same category.
    """
    controller = context.get_controller()

    model = input.to_pydantic()
    graph_id = context.extract_graph_id(model.id)
    local_id = context.extract_node_id(model.id)

    graph = context.get_accessible_graph(info, graph_id)

    existing = controller.get_relation_by_id(local_id)
    if existing is None:
        raise ValueError(f"Relation not found with ID {model.id}")

    category = models.RelationCategory.objects.get(graph=graph, age_name=existing.label)

    controller.archive_relation(
        graph,
        relation_id=local_id,
        info=info,
    )

    updated = controller.create_relation(
        category=category,
        payload=model,
        info=info,
    )

    return types.Relation(_value=updated)


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
