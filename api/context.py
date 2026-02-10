from kante.types import Info
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


def extract_node_id(composite_id: str) -> int:
    """
    Extract the entity UUID from a composite ID.

    Composite IDs are in the format: {graph_id}-{entity_uuid}
    This function returns everything after the first hyphen.

    Args:
        composite_id: The composite ID (e.g., "1-abc123-def456-...")

    Returns:
        The entity UUID part (e.g., "abc123-def456-...")
    """
    parts = composite_id.split("-", 1)
    if len(parts) == 2:
        return int(parts[1])
    raise ValueError(f"Invalid composite ID format: {composite_id}")


def extract_graph_id(composite_id: str) -> str:
    """
    Extract the graph ID from a composite ID.

    Composite IDs are in the format: {graph_id}-{entity_uuid}
    This function returns everything before the first hyphen.

    Args:
        composite_id: The composite ID (e.g., "1-abc123-def456-...")

    Returns:
        The graph ID part (e.g., "1")
    """
    parts = composite_id.split("-", 1)
    if len(parts) == 2:
        return parts[0]
    raise ValueError(f"Invalid composite ID format: {composite_id}")
