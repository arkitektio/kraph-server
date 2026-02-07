"""
Measurement mutation resolvers.
"""
from kante.types import Info

from api.types import Measurement, measurement_from_response
from api.inputs import CreateNaturalEventInput
from api.context import get_provenance_from_context, get_controller
from core import models


def create_natural_event(
    info: Info,
    input: CreateNaturalEventInput,
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
    natural_event = input.to_pydantic()
    
    
    
    graph = models.Graph.objects.get(id=natural_event.graph)  # Validate graph exists
    
    
    response = controller.add_natural_event(
        graph,
        structure_id=local_id,
        measurement=measurement,
        provenance=get_provenance_from_context(info),
    )
    
    return measurement_from_response(response)
