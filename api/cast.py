from typing import Union
from graph_engine.retrieved import RetrievedNode
from api.types import Entity, Structure, Measurement, Assertion

def cast_retrieve_to_graphql_type(retrieved: RetrievedNode) -> Union[Entity, Structure, Measurement, Assertion]:
    """Cast a RetrievedBase object to its corresponding GraphQL type name."""
    from graph_engine.retrieved import RetrievedEntity, RetrievedStructure, RetrievedMeasurement, RetrievedAssertion
    if isinstance(retrieved, RetrievedEntity):
        return Entity(_value=retrieved)
    elif isinstance(retrieved, RetrievedStructure):
        return Structure(_value=retrieved)
    elif isinstance(retrieved, RetrievedMeasurement):
        return Measurement(_value=retrieved)    
    elif isinstance(retrieved, RetrievedAssertion):
        return Assertion(_value=retrieved)
    else:
        raise ValueError(f"Unknown RetrievedBase subclass: {type(retrieved)}")