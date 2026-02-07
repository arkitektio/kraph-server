"""
Measurement mutation resolvers.
"""
from kante.types import Info

from api.types import Measurement, measurement_from_response
from api.inputs import AddMeasurementInput
from api.context import extract_graph_id, get_provenance_from_context, get_controller, extract_node_id
from core import models


def add_measurement(
    info: Info,
    input: AddMeasurementInput,
) -> Measurement:
    """
    Add a measurement to an existing structure.
    
    If the structure doesn't exist, it will be created automatically.
    
    Args:
        info: Strawberry Info context
        input: AddMeasurementInput
        
    Returns:
        Created Measurement object
    """
    controller = get_controller()
    
    # Convert strawberry-pydantic inputs to pydantic models
    measurement = input.measurement.to_pydantic()
    
    graph_id = extract_graph_id(input.structure_id)
    local_id = extract_node_id(input.structure_id)
    
    graph = models.Graph.objects.get(id=graph_id)  # Validate graph exists
    
    
    response = controller.add_measurement(
        graph,
        structure_id=local_id,
        measurement=measurement,
        provenance=get_provenance_from_context(info),
    )
    
    return measurement_from_response(response)
