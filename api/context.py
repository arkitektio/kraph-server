from kante.types import Info
from graph_engine.input_models import ProvenanceContext
from graph_engine import input_models
from api.extensions.cypher import cypher_engine
from graph_engine.controller import GraphController, extract_graph_id as exg, extract_node_id as exn
from graph_engine.scalars import GraphID, LocalID, GraphName
from core import models


def extract_graph_id(composite_id: GraphID) -> GraphName:
    """Extract the graph ID (graph name) from a composite ID."""
    return exg(composite_id)


def extract_node_id(composite_id: GraphID) -> LocalID:
    """Extract the local node ID from a composite ID."""
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


def _get_request_scopes(info: Info) -> list[str]:
    request = info.context.request

    extension_scopes = request._extensions.get("scopes") if hasattr(request, "_extensions") else None
    if isinstance(extension_scopes, list):
        return [str(scope) for scope in extension_scopes]
    if isinstance(extension_scopes, str):
        return [scope for scope in extension_scopes.split(" ") if scope]

    token = request._extensions.get("token") if hasattr(request, "_extensions") else None
    token_scopes = getattr(token, "scopes", None)
    if isinstance(token_scopes, list):
        return [str(scope) for scope in token_scopes]
    if isinstance(token_scopes, str):
        return [scope for scope in token_scopes.split(" ") if scope]

    return []


def validate_graph_access(info: Info, graph: models.Graph) -> models.Graph:
    """Validate that the graph is accessible based on the request's membership and scopes."""
    request = info.context.request
    membership = getattr(request, "membership", None)
    if membership is None and hasattr(request, "_extensions"):
        membership = request._extensions.get("membership")

    if membership is None:
        raise ValueError("No membership found in context")

    scopes = _get_request_scopes(info)
    try:
        graph.validate_accessible(membership=membership, scopes=scopes)
    except PermissionError:
        token = request._extensions.get("token") if hasattr(request, "_extensions") else None
        if token is not None and token.__class__.__name__ == "StaticToken":
            graph.validate_accessible(membership=graph.membership, scopes=scopes)
        else:
            raise
    return graph


def validate_graph_actions(
    info: Info,
    graph: models.Graph,
    actions: list[input_models.Action | str] | None = None,
) -> models.Graph:
    """Validate that all requested actions are allowed for the current graph context."""
    if not actions:
        return graph

    for action in actions:
        action_value = action.value if hasattr(action, "value") else str(action)
        graph.validate_action_allowed(info=info, action=action_value)

    return graph


def get_accessible_graph(
    info: Info,
    identifier: str | GraphName,
    actions: list[input_models.Action | str] | None = None,
) -> models.Graph:
    graph = None
    identifier_str = str(identifier)

    if identifier_str.isdigit():
        graph = models.Graph.objects.filter(id=int(identifier_str)).first()
    else:
        graph = models.Graph.objects.get_graph_from_graph_name(GraphName(identifier_str))

    if graph is None:
        raise ValueError(f"Graph not found for identifier {identifier}")

    graph = validate_graph_access(info, graph)
    return validate_graph_actions(info, graph, actions=actions)
