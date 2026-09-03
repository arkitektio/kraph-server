"""Fetching a row the caller is actually allowed to touch.

Instance mutations have been authorized since the write API started naming terms:
they resolve the request's active organization and call
`context.assert_can_access_organization`. Everything *around* them — the ontology,
the saved queries, the plots — did not. Those mutations fetched by bare
primary key on managers that filter only by `kind`:

    item = models.EntityCategory.objects.get(id=model.id)
    item.delete()

Nothing in that names an organization, a graph, or an owner. Primary keys are
sequential integers, so any authenticated member of any tenant could read, edit
and delete another tenant's categories, saved queries and plots by
guessing a number. Eleven of those paths ended in a bare `.delete()`.

The check has to come from the *row*, not from the request, for the same reason
`GraphController._assert_same_organization` does: the client names a primary key
and never names a tenant, so trusting the request's organization would authorize
the caller against their own tenant while acting on somebody else's row.

Everything here is graph-scoped, which is the boundary that applies:
`Graph.validate_accessible` compares the graph's organization against the
requester's membership. Instance data is organization-scoped instead — a claim
belongs to the tenant, not to whichever view drew it — and keeps its own path.
"""

from typing import Any, TypeVar

from api import context

T = TypeVar("T")


def graph_of(item: Any) -> Any:
    """The graph a row belongs to, however it is reached.

    Categories and saved queries carry `graph` directly. A `ScatterPlot`
    does not — it reaches one through its `graph_query` — so the walk is
    spelled out here rather than repeated at each call site.
    """
    graph = getattr(item, "graph", None)
    if graph is not None:
        return graph

    query = getattr(item, "graph_query", None)
    if query is not None:
        return query.graph

    return None


def scoped(info, model, pk, *, what: str):
    """Fetch a graph-owned row, or refuse.

    Raises `ValueError` when there is no such row and `PermissionError` when
    there is one the caller may not reach — deliberately different exceptions,
    because "no such id" and "not yours" are different answers and a client
    debugging the first should not have to guess.

    They are *not* collapsed into one message to avoid leaking existence. Ids
    here are sequential integers over schema rows, so enumeration tells an
    attacker nothing they could not get by counting, and a misleading "not found"
    for a row that exists costs every legitimate caller real debugging time.
    """
    item = model.objects.filter(pk=pk).first()
    if item is None:
        raise ValueError(f"No {what} with id {pk}")

    graph = graph_of(item)
    if graph is None:
        raise PermissionError(f"Cannot establish which graph this {what} belongs to, so it cannot be authorized.")

    context.validate_graph_access(info, graph)
    return item


def accessible_graph(info, pk):
    """The graph a create-mutation names, checked before anything is written.

    `create_*_category` took `models.Graph.objects.get(id=model.graph)` and wrote
    a category into it, so a caller could add vocabulary to any tenant's view.
    """
    from core import models

    graph = models.Graph.objects.filter(pk=pk).first()
    if graph is None:
        raise ValueError(f"No graph with id {pk}")

    context.validate_graph_access(info, graph)
    return graph


def schema_scoped(info: Any, model: Any, identifier: Any, *, what: str) -> Any:
    """`scoped`, plus the definition-editing RBAC (RFC 0013).

    For the mutations that change what a graph's words mean. Tenancy first
    (the row must be reachable at all), then owner-or-admin on its graph.
    """
    item = scoped(info, model, identifier, what=what)
    graph_of(item).validate_definition_editable(info)
    return item


def schema_graph(info: Any, identifier: Any) -> Any:
    """`accessible_graph`, plus the definition-editing RBAC (RFC 0013)."""
    graph = accessible_graph(info, identifier)
    graph.validate_definition_editable(info)
    return graph
