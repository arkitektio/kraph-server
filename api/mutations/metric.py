"""
Measurement mutation resolvers.
"""

from kante.types import Info

from api import types, inputs, context
from graph_engine.scalars import GraphID
from graph_engine import input_models, scalars


def record_metric(
    info: Info,
    input: inputs.RecordMetricInput,
) -> types.Metric:
    """
    Record a new metric for a structure. If the structure doesn't exist, it will be created automatically.

    Args:
        info: Strawberry Info context
        input: RecordMetricInput
    Returns:
        Created Metric object
    """

    controller = context.get_controller()

    # Convert strawberry-pydantic inputs to pydantic models
    model = input.to_pydantic()

    graph = context.get_accessible_graph(info, model.graph)

    structure_category = controller.ensure_structure_category_or_raise(
        graph=graph,
        identifier=model.identifier,
        info=info,
    )

    controller.ensure_metric_category_or_raise(
        graph=graph,
        structure_category=structure_category,
        key=model.key,
        value_kind=model.value_kind,
        info=info,
    )

    try:
        s = controller.get_structure_by_object(structure_category, model.object)
    except ValueError:
        if graph.can_auto_add_structures(info):
            s = controller.create_structure(
                structure_category=structure_category,
                payload=input_models.StructureInput(
                    object=model.object,
                ),
            )
        else:
            raise ValueError(f"Structure with object '{model.object}' does not exist in graph '{model.graph}' and auto-adding structures is not allowed")

    response = controller.create_metric(
        graph,
        structure_id=s.local_id,
        input=model,
        info=info,
    )

    return types.Metric.from_specific(response)  # Convert to GraphQL type, preserving specific subtype information. If the metric already exists, it will be updated with the new value and timestamp.


def create_metric(
    info: Info,
    input: inputs.CreateMetricInput,
) -> types.Metric:
    """
    Add a measurement to an existing structure.

    If the structure doesn't exist, it will be created automatically.

    Args:
        info: Strawberry Info context
        input: AddMeasurementInput

    Returns:
        Created Measurement object
    """
    controller = context.get_controller()

    # Convert strawberry-pydantic inputs to pydantic models
    model = input.to_pydantic()

    graph_id = context.extract_graph_id(model.structure)
    local_id = context.extract_node_id(model.structure)

    graph = context.get_accessible_graph(info, graph_id)

    response = controller.create_metric(
        graph,
        structure_id=local_id,
        input=model,
        info=info,
    )

    return types.Metric.from_specific(response)  # Convert to GraphQL type, preserving specific subtype information. If the metric already exists,


def delete_metric(
    info: Info,
    input: inputs.DeleteMetricInput,
) -> GraphID:
    """
    Delete a measurement by its composite ID.
    Only the owner of the graph or an admin can delete a measurement.

    Args:
        info: Strawberry Info context
        input: Composite ID of the measurement to delete (e.g., "1-abc123-def456-...")

    Returns:
        The ID of the deleted measurement
    """
    controller = context.get_controller()

    model = input.to_pydantic()

    graph_id = context.extract_graph_id(model.id)
    node_id = context.extract_node_id(model.id)

    graph = context.get_accessible_graph(info, graph_id)

    controller.delete_metric(
        graph,
        metric_id=node_id,
    )

    return model.id


def update_metric(
    info: Info,
    input: inputs.UpdateMetricInput,
) -> types.Metric:
    """
    Update a metric by creating a new metric and archiving the previous one.

    Args:
        info: Strawberry Info context
        input: The metric update payload

    Returns:
        The newly created metric
    """
    controller = context.get_controller()

    model = input.to_pydantic()
    graph_id = context.extract_graph_id(model.id)
    graph = context.get_accessible_graph(info, graph_id)

    updated = controller.update_metric(
        graph,
        payload=model,
        info=info,
    )

    return types.Metric(_value=updated)


def archive_metric(
    info: Info,
    input: inputs.ArchiveMetricInput,
) -> types.Metric:
    """
    Archive (soft delete) a measurement by its composite ID.

    Args:
        info: Strawberry Info context
        input: Composite ID of the measurement to archive (e.g., "1-abc123-def456-...")

    Returns:
        The ID of the archived measurement
    """
    controller = context.get_controller()

    model = input.to_pydantic()  # Validate input with Pydantic models

    graph_id = context.extract_graph_id(model.id)
    node_id = context.extract_node_id(model.id)

    graph = context.get_accessible_graph(info, graph_id)

    controller.archive_metric(
        graph,
        metric_id=node_id,
        info=info,
    )

    archived_metric = controller.get_node_by_local_id(graph, local_id=node_id)

    return types.Metric(_value=archived_metric)
