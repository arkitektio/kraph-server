from kante.types import Info
from graph_engine.input_models import ProvenanceContext
from graph_engine import input_models
from api.extensions.cypher import cypher_engine
from graph_engine.controller import GraphController
from graph_engine.scalars import GraphName
from core import models


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


def get_active_organization(info: Info):
    """The organization this request is acting for.

    Evidence is organization-scoped, so structures, metrics and assertions are
    reached through the request's active organization rather than through a
    graph. Their IDs are bare primary keys with no graph component, so there is
    no graph to extract one from — which is the point: a structure belongs to the
    tenant, not to whichever projection happened to create it.
    """
    request = info.context.request

    organization = getattr(request, "organization", None) or getattr(request, "_organization", None)
    if organization is None:
        membership = getattr(request, "membership", None)
        organization = getattr(membership, "organization", None)

    if organization is None:
        raise ValueError("No active organization on the request; cannot resolve evidence scope.")

    return organization


def assert_can_access_organization(info: Info, organization) -> None:
    """Check the caller may act for this organization.

    Kinds are identified by a globally unique primary key, so the client never
    names a tenant — which means authorization comes from the row rather than
    from the request. Same shape as `GraphController._assert_can_access`.
    """
    from authentikate.models import Membership

    user = getattr(info.context.request, "user", None)
    if user is None:
        raise PermissionError("Cannot access organization vocabulary without an authenticated user")

    if not Membership.objects.filter(user=user, organization=organization, blocked=False).exists():
        raise PermissionError("You are not allowed to access this organization's vocabulary")


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
    """Validate that the graph is accessible based on the request's membership and scopes.

    This used to resolve a membership and then return the graph unconditionally,
    so access control was a no-op at the API layer — every caller could reach
    every graph. It went unnoticed because the test identity never matched the
    organization owning the graph either, so nothing would have caught a
    regression here.

    Now that evidence is shared across projections within an organization,
    "which graph may I touch" is the boundary that decides what a caller can
    reach, so it has to actually decide something.
    """
    request = info.context.request

    membership = getattr(request, "membership", None)
    if membership is None and hasattr(request, "_extensions"):
        membership = request._extensions.get("membership")

    if membership is None:
        raise PermissionError("No membership on the request; cannot access this graph.")

    graph.validate_accessible(membership, _get_request_scopes(info))
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
