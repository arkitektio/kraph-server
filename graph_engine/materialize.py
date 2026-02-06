from .input_models import GraphInput
from core import models


def materialize(input: GraphInput) -> models.Graph:
    """
    Materialize a graph based on the provided graph definition.
    
    This function creates or updates the graph schema, node categories,
    edge categories, and event categories as defined in the input.
    
    Args:
        input: GraphDefinitionInput containing the graph schema definition.
        
    Returns:
        The materialized Graph instance.
    """
    # Implementation of materialization logic goes here
    
    graph = models.Graph.objects.create(
        name=input.name,
        description=input.description,
    )
    
    
    entity_definitions = input.definition.extensions.entities
    
    for defn in entity_definitions:
        # Create NodeCategory for each entity definition
        node_category = models.EntityCategory.objects.create(
            graph=graph,
            key=defn.key,
            description=defn.description or "",
            property_definitions=[prop.model_dump(mode='json') for prop in defn.properties] if defn.properties else [],
        )
        
    relation_definitions = input.definition.extensions.relations
    
    for defn in relation_definitions:
        # Create EdgeCategory for each relation definition
        edge_category = models.EdgeCategory.objects.create(
            graph=graph,
            key=defn.key,
            description=defn.description or "",
            property_definitions=[prop.model_dump(mode='json') for prop in defn.properties] if defn.properties else [],
        )
    

    
    
    pass