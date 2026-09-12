"""Which projector the current operation draws through.

A `ContextVar`, bound per GraphQL operation by `api.extensions.projection`
(`ProjectionExtension`) and read by `api.context.get_controller()`, the graph
mutations, the management commands and the `pre_delete` signal in
`graph_engine.apps`. It lives here rather than in `api/` because the projection
layer's own signal handler needs it and `graph_engine` does not import `api`.

Outside an operation nothing has bound one; `current_or_default()` falls back
to a fresh table projector so that callers do not each carry their own copy of
that fallback (four management commands used to).
"""

from __future__ import annotations

from contextvars import ContextVar

from graph_engine.projection.protocol import Projector

#: Defaults to ``None`` rather than raising `LookupError`, so a caller has to test
#: the value — not just catch — to know whether an operation bound one.
current_projector: ContextVar[Projector | None] = ContextVar("current_projector", default=None)


def get_current_projector() -> Projector | None:
    """The projector the current operation draws through, or None outside one."""
    return current_projector.get()


def current_or_default() -> Projector:
    """The bound projector, or a fresh table one — stateless, so fresh is free."""
    bound = current_projector.get()
    if bound is not None:
        return bound

    from graph_engine.projection.table import TableProjector

    return TableProjector()
