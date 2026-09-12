"""Bind the projection kind a request draws through — the Strawberry half.

One `Projector` per process today, the Apache AGE one built in `api/schema.py`,
bound into `graph_engine.projection.context.current_projector` for the duration
of each operation so that `api.context.get_controller()` and anything else that
draws finds it without being handed it. The ContextVar is named for what it holds
(a projector), not for the query language the current implementation happens to
speak: this is the one place a second projection kind would be selected.
"""

from __future__ import annotations

from strawberry.extensions import SchemaExtension

from graph_engine.projection import Projector
from graph_engine.projection.context import current_or_default, current_projector, get_current_projector

__all__ = ["ProjectionExtension", "current_or_default", "current_projector", "get_current_projector"]


class ProjectionExtension(SchemaExtension):
    """Strawberry extension that binds one projector per operation."""

    def __init__(self, projector: Projector, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.projector: Projector = projector

    def on_operation(self):
        """Bind for the operation, then unbind."""
        token = current_projector.set(self.projector)
        yield
        current_projector.reset(token)
