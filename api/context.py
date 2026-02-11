from kante.types import Info
from graph_engine.input_models import ProvenanceContext
from api.extensions.cypher import cypher_engine
from graph_engine.controller import GraphController, extract_graph_id as exg, extract_node_id as exn


def extract_graph_id(composite_id: str) -> str:
    return exg(composite_id)


def extract_node_id(composite_id: str) -> int:
    return exn(composite_id)


def get_provenance_from_context(info: Info) -> ProvenanceContext:
    """
    Extract provenance context from the authenticated request.

    Returns:
        Dict with subject (user ID) and app_id (client ID)
    """
    request = info.context.request

    user = getattr(request, "user", None)
    client = getattr(request, "client", None)

    if not user:
        raise ValueError("No authenticated user found in context")

    return ProvenanceContext(
        subject=str(user.id),
        app_id=str(client.id) if client else "unknown",
    )


def get_controller() -> GraphController:
    """
    Get a default GraphController without a specific graph context.

    This can be used for operations that don't require a specific graph,
    such as listing available graphs or creating a new graph.

    Returns:
        GraphController with no specific graph context
    """
    engine = cypher_engine.get()

    return GraphController(engine=engine)
