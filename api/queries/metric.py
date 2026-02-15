"""
Measurement query resolvers.
"""

from typing import List
from kante.types import Info

from api import types, context
from graph_engine import scalars


def metric(
    info: Info,
    metric_id: scalars.GraphID,
) -> types.Metric:
    """
    Fetch a single metric by ID.

    Args:
        info: Strawberry Info context
        metric_id: The metric's graph ID

    Returns:
        A Metric object
    """
    controller = context.get_controller()

    graph_id = context.extract_graph_id(metric_id)
    local_id = context.extract_node_id(metric_id)

    graph = context.get_accessible_graph(info, graph_id)

    response = controller.get_node(graph, local_id=local_id, info=info)
    return types.Metric(_value=response)


def metrics_for_structure(
    info: Info,
    structure_id: scalars.GraphID,
) -> List[types.Metric]:
    """
    Fetch all measurements attached to a structure.

    Args:
        info: Strawberry Info context
        identifier: Structure identifier (e.g. '@mikro/roi')
        object: Structure object ID

    Returns:
        List of Measurement objects
    """
    controller = context.get_controller()
    graph_id = context.extract_graph_id(structure_id)
    local_id = context.extract_node_id(structure_id)

    graph = context.get_accessible_graph(info, graph_id)
    structure_node = controller.get_node(graph, local_id=local_id, info=info)
    structure_identifier = structure_node.properties.get("identifier")
    structure_object = structure_node.properties.get("object")

    if structure_identifier is None or structure_object is None:
        raise ValueError("Structure is missing identifier/object properties")

    responses = controller.get_metrics_for_structure(
        graph=graph,
        identifier=structure_identifier,
        structure_object=structure_object,
        info=info,
    )
    return [types.Metric(_value=r) for r in responses]


def measurements_for_assertion(
    info: Info,
    assertion_id: int,
) -> List[types.Metric]:
    """
    Fetch all measurements that were asserted by a given assertion.

    Args:
        info: Strawberry Info context
        assertion_id: The assertion's graph ID

    Returns:
        List of Measurement objects
    """
    # For assertion queries, we need to extract the graph from the assertion_id
    # This is a temporary solution - ideally assertion_id would include graph prefix
    # For now, we'll need to handle this differently or require graph_id as parameter
    # TODO: This needs graph_id - assertion_id alone doesn't contain it
    # This might need refactoring to include graph context
    raise NotImplementedError("measurements_for_assertion needs graph_id context")
