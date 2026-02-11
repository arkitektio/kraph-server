"""
Measurement query resolvers.
"""

from typing import List
from kante.types import Info

from api import types, context


def metrics_for_structure(
    info: Info,
    structure_id: str,
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
    responses = controller.get_measurements_for_structure(
        identifier=identifier,
        structure_object=object,
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
