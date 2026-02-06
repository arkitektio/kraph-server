from kante.types import Info
from core.models import Graph
from graph_engine.input_models import ProvenanceContext
from api.extensions.cypher import cypher_engine
from graph_engine.controller import GraphController

def get_provenance_from_context(info: Info) -> ProvenanceContext:
    """
    Extract provenance context from the authenticated request.
    
    Returns:
        Dict with subject (user ID) and app_id (client ID)
    """
    request = info.context.request
    
    user = getattr(request, 'user', None)
    client = getattr(request, 'client', None)
    
    if not user:
        raise ValueError("No authenticated user found in context")
    
    return ProvenanceContext(
        subject=str(user.id),
        app_id=str(client.id) if client else "unknown",
    )


def get_controller_for_graph_id(info: Info) -> GraphController:
    """
    Load a Graph from the database and create a controller for it.
    
    Args:
        graph_id: The database ID of the Graph
        
    Returns:
        GraphController configured for the specified graph
    """
    engine = cypher_engine.get()
    
    
    # Extract provenance from context
    provenance = get_provenance_from_context(info)
    
    return GraphController(
        engine=engine, 
        subject=provenance.subject,
        app_id=provenance.app_id,
    )


def get_controller_for_node_id(node_id: str, info: Info) -> GraphController:
    """
    Load a Graph from the database and create a controller for it.
    
    Args:
        node_id: The database ID of the Graph
        
    Returns:
        GraphController configured for the specified graph
    """
    graph_id = node_id.split("-")[0]
    return get_controller_for_graph_id(graph_id, info)