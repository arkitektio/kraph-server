"""
Measurement mutation resolvers.
"""
from kante.types import Info

from api.types import Measurement, measurement_from_response
from api.inputs import AddMeasurementInput
from api.context import get_controller_for_node_id, get_provenance_from_context
from graph_engine import input_models


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
    controller = get_controller_for_node_id(input.structure_object, info)
    
    # Convert strawberry-pydantic inputs to pydantic models
    measurement = input.measurement.to_pydantic()
    provenance = get_provenance_from_context(info)
    
    response = controller.add_measurement(
        structure_identifier=input.structure_identifier,
        structure_object=input.structure_object,
        measurement=measurement,
        provenance=provenance,
    )
    
    return measurement_from_response(response)
