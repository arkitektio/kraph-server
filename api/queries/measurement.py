"""
Measurement query resolvers.
"""
from typing import List
from kante.types import Info

from api.types import Measurement, measurement_from_response
from api.context import get_controller_for_node_id


def measurements_for_structure(
    info: Info,
    structure_id: str,
) -> List[Measurement]:
    """
    Fetch all measurements attached to a structure.
    
    Args:
        info: Strawberry Info context
        identifier: Structure identifier (e.g. '@mikro/roi')
        object: Structure object ID
        
    Returns:
        List of Measurement objects
    """
    controller = get_controller_for_node_id(structure_id, info)
    responses = controller.get_measurements_for_structure(
        identifier=identifier,
        structure_object=object,
    )
    return [measurement_from_response(r) for r in responses]


def measurements_for_assertion(
    info: Info,
    assertion_id: int,
) -> List[Measurement]:
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
    from api.context import get_controller_for_graph_id
    # TODO: This needs graph_id - assertion_id alone doesn't contain it
    # This might need refactoring to include graph context
    raise NotImplementedError("measurements_for_assertion needs graph_id context")
