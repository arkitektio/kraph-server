"""
Measurement mutation resolvers.
"""

from kante.types import Info
import strawberry
from typing import cast

from api import types, inputs, context
from core import models
from graph_engine.scalars import GraphID


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
