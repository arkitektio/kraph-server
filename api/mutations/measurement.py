"""
Measurement mutation resolvers.
"""

from kante.types import Info
import strawberry
from typing import cast

from api import types, inputs, context
from core import models
from graph_engine.scalars import GraphID


def create_measurement(info: Info, input: inputs.CreateMeasurementInput) -> types.Measurement:
    """
    Create a new measurement edge between a structure and an entity.

    A measurement is an edge type with its own category semantics.
    """
    payload = input.to_pydantic()

    controller = context.get_controller()

    graph1 = context.extract_graph_id(cast(GraphID, payload.source_id))
    graph2 = context.extract_graph_id(cast(GraphID, payload.target_id))

    if graph1 != graph2:
        raise ValueError("Source and target nodes must belong to the same graph")
    context.extract_node_id(cast(GraphID, payload.source_id))
    context.extract_node_id(cast(GraphID, payload.target_id))

    source_graph = context.get_accessible_graph(info, graph1)
    target_graph = context.get_accessible_graph(info, graph2)
    assert source_graph.pk == target_graph.pk, "Source and target nodes must belong to the same graph"

    measurement = models.MeasurementCategory.objects.get(id=payload.category)
    context.validate_graph_access(info, measurement.graph)

    assert measurement.graph.get_age_name() == graph1, "Measurement category must belong to the same graph as the nodes"

    result = controller.create_relation(
        category=cast(models.RelationCategory, measurement),
        payload=payload,
        info=info,
    )

    return types.Measurement(_value=result)


def update_measurement(info: Info, input: inputs.UpdateMeasurementInput) -> types.Measurement:
    """
    Update a measurement by archiving the current edge and creating a new one in the same category.
    """
    controller = context.get_controller()

    model = input.to_pydantic()
    graph_id = context.extract_graph_id(cast(GraphID, model.id))
    local_id = context.extract_node_id(cast(GraphID, model.id))

    graph = context.get_accessible_graph(info, graph_id)

    existing = controller.get_relation_by_id(local_id)
    if existing is None:
        raise ValueError(f"Measurement not found with ID {model.id}")

    category = models.MeasurementCategory.objects.get(graph=graph, age_name=existing.label)

    controller.archive_relation(
        graph,
        relation_id=local_id,
        info=info,
    )

    updated = controller.create_relation(
        category=cast(models.RelationCategory, category),
        payload=model,
        info=info,
    )

    return types.Measurement(_value=updated)


def delete_measurement(info: Info, input: inputs.DeleteMeasurementInput) -> GraphID:
    """
    Delete a measurement edge by its composite ID.
    """
    controller = context.get_controller()

    model = input.to_pydantic()
    graph_id = context.extract_graph_id(cast(GraphID, model.id))
    local_id = context.extract_node_id(cast(GraphID, model.id))

    graph = context.get_accessible_graph(info, graph_id)

    controller.delete_relation(
        graph,
        relation_id=local_id,
        info=info,
    )

    return cast(GraphID, model.id)


def archive_measurement(info: Info, input: inputs.ArchiveMeasurementInput) -> types.Measurement:
    """
    Archive (soft delete) a measurement edge by its composite ID.
    """
    controller = context.get_controller()

    model = input.to_pydantic()
    graph_id = context.extract_graph_id(cast(GraphID, model.id))
    local_id = context.extract_node_id(cast(GraphID, model.id))

    graph = context.get_accessible_graph(info, graph_id)

    controller.archive_relation(
        graph,
        relation_id=local_id,
        info=info,
    )

    archived = controller.get_relation_by_id(local_id)
    assert archived is not None, "Measurement was archived but could not be loaded"

    return types.Measurement(_value=archived)
