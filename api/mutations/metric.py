"""
Measurement mutation resolvers.
"""

from kante.types import Info

from api import types, inputs, context
from core import models


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

    graph_id = context.extract_graph_id(model.structure_id)
    local_id = context.extract_node_id(model.structure_id)

    graph = models.Graph.objects.get(id=graph_id)  # Validate graph exists

    response = controller.create_metric(
        graph,
        structure_id=local_id,
        input=model,
        provenance=context.get_provenance_from_context(info),
    )

    return types.Metric(_value=response)


def delete_metric(
    info: Info,
    input: inputs.DeleteMetricInput,
) -> types.Metric:
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

    graph_id = context.extract_graph_id(input.id)
    node_id = context.extract_node_id(input.id)

    graph = models.Graph.objects.get(id=graph_id)  # Validate graph exists

    controller.delete_metric(graph, metric_id=node_id)

    return input


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

    graph = models.Graph.objects.get(id=graph_id)  # Validate graph exists

    controller.archive_metric(graph, metric_id=node_id)

    return input
