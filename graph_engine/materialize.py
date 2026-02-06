from .input_models import GraphInput
from core import models
from .engine.protocol import CypherEngine



def ensure_node_category(
    graph: models.Graph,
    category: models.EntityCategory,
    engine: CypherEngine,
):
    """
    Ensure that the node category exists in the graph database.
    
    This function checks if the corresponding labels and indexes
    for the node category are present in the graph database,
    and creates them if they do not exist.
    
    Args:
        category: The EntityCategory model instance to ensure.
        engine: The CypherEngine to execute queries against.
    """
    # Implementation of ensuring node category in the graph database goes here
    pass


def materialize(input: GraphInput, engine: CypherEngine) -> models.Graph:
    """
    Materialize a graph based on the provided graph definition.
    This is the initial step to set up the graph structure in the database
    and import. 
    
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
    age_graph = engine.create_graph(graph=graph, definition=input.definition)
    
    # TODO: Create sequences in the graph and in the db
    
    
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
    
    #TODO: Implement everything based on the input definition
    
    
    pass