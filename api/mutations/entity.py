"""
Entity mutation resolvers.
"""

from graph_engine import scalars
from graph_engine import input_models
from api import inputs, types, context
from core import models
from kante import Info


def create_entity(
    info: Info,
    input: inputs.CreateEntityInput,
) -> types.Entity:
    """
    Create a new entity with optional supporting evidence structures.

    Properties are automatically derived from the evidence according to
    the graph schema rules.

    Args:
        info: Strawberry Info context
        input: CreateEntityInput         with graph_id, kind, and evidence

    Returns:
        EntityCreationResult with the created entity
    """

    input_model = input.to_pydantic()  # Validate input with Pydantic models

    entity_category = models.EntityCategory.objects.get(id=input_model.entity_category)  # Validate graph exists
    context.validate_graph_access(info, entity_category.graph)

    # Get controller for the specified graph (includes provenance from context)
    controller = context.get_controller()

    # Call controller with kwargs (provenance is already in the controller)
    result = controller.create_entity(
        entity_category=entity_category,
        payload=input_model,
        info=info,
    )

    return types.Entity(_value=result)


def delete_entity(
    info: Info,
    input: inputs.DeleteEntityInput,
) -> scalars.GraphID:
    """
    Delete an entity by its composite ID.

    Args:
        info: Strawberry Info context
        input: Composite ID of the entity to delete (e.g., "1-abc123-def456-...")

    Returns:
        The ID of the deleted entity
    """
    controller = context.get_controller()
    model = input.to_pydantic()  # Validate input with Pydantic models

    graph_id = context.extract_graph_id(model.id)
    node_id = context.extract_node_id(model.id)

    graph = context.get_accessible_graph(info, graph_id)

    deleted_entity = controller.get_node_by_local_id(graph, local_id=node_id)

    controller.delete_entity(graph, local_id=node_id)

    return model.id


def archive_entity(
    info: Info,
    input: inputs.ArchiveEntityInput,
) -> types.Entity:
    """
    Archive (soft delete) an entity by its composite ID.

    Args:
        info: Strawberry Info context
        input: Composite ID of the entity to archive (e.g., "1-abc123-def456-...")

    Returns:
        The ID of the archived entity
    """
    controller = context.get_controller()

    model = input.to_pydantic()

    graph_id = context.extract_graph_id(model.id)
    node_id = context.extract_node_id(model.id)

    graph = context.get_accessible_graph(info, graph_id)

    controller.archive_entity(
        graph,
        local_id=node_id,
        info=info,
    )

    archived_entity = controller.get_node_by_local_id(graph, local_id=node_id)

    return types.Entity(_value=archived_entity)


def update_entity(
    info: Info,
    input: inputs.UpdateEntityInput,
) -> types.Entity:
    """
    Archive (soft delete) an entity by its composite ID.

    Args:
        info: Strawberry Info context
        input: Composite ID of the entity to archive (e.g., "1-abc123-def456-...")

    Returns:
        The ID of the archived entity
    """
    controller = context.get_controller()

    model = input.to_pydantic()

    graph_id = context.extract_graph_id(model.id)
    local_id = context.extract_node_id(model.id)
    graph = context.get_accessible_graph(info, graph_id)

    existing = controller.get_node_by_local_id(graph, local_id=local_id, info=info)
    if not existing.category_id:
        raise ValueError("Entity does not have a category and cannot be updated")

    entity_category = models.EntityCategory.objects.get(id=existing.category_id)

    controller.archive_entity(
        graph,
        local_id=local_id,
        info=info,
    )

    updated = controller.create_entity(
        entity_category=entity_category,
        payload=input_models.CreateEntityInput(
            entity_category=str(entity_category.pk),
            supporting_evidence=model.supporting_evidence,
        ),
        info=info,
    )

    return types.Entity(_value=updated)


def set_entity_property(
    info: Info,
    input: inputs.SetEntityPropertyInput,
) -> types.Entity:
    """
    Set properties on an entity, replacing any existing values for the specified keys.

    Args:
        info: Strawberry Info context
        input: SetEntityPropertiesInput with entity_id and properties to set
    """

    controller = context.get_controller()

    model = input.to_pydantic()

    graph_id = context.extract_graph_id(input.entity_id)
    node_id = context.extract_node_id(input.entity_id)

    graph = context.get_accessible_graph(info, graph_id)

    entity = controller.get_node_by_local_id(graph, local_id=node_id, info=info)
    if not entity.category_id:
        raise ValueError("Entity does not have a category and cannot be updated")

    entity_category = models.EntityCategory.objects.get(id=entity.category_id)
    property_definition = entity_category.property_map.get(model.key)
    if property_definition is None:
        raise ValueError(f"Property '{model.key}' is not defined for entity category '{entity_category.key}'")

    if property_definition.derivation != input_models.DerivationType.LATEST:
        raise ValueError('only "latest" properties can be actively set')

    controller.set_entity_property(
        graph,
        local_id=node_id,
        key=model.key,
        value=model.value,
    )
    # Only the system metadata is refreshed. The value was written directly
    # rather than derived from evidence, so there is nothing for the projector to
    # recompute — and running it here would overwrite the value just set.
    controller._stamp_projection(entity_category, node_id)

    updated_entity = controller.get_node(graph, local_id=node_id, info=info)
    return types.Entity(_value=updated_entity)
