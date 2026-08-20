"""The projection seam.

`Projector` (`protocol.py`) is what the controller and `graph_engine.projector`
draw through; `CypherProjector` (`cypher.py`) is the Apache AGE implementation
and the only module in the repo that emits Cypher for a drawing. A second
projection kind — a per-view table, a search index — implements the same
protocol and plugs in where `CypherProjector` does: `api/schema.py`,
`api/context.py`, and the management commands.
"""

from graph_engine.projection.context import current_or_default, current_projector, get_current_projector
from graph_engine.projection.cypher import CypherProjector
from graph_engine.projection.protocol import DrawnEdge, Projector

__all__ = ["CypherProjector", "DrawnEdge", "Projector", "current_or_default", "current_projector", "get_current_projector"]
