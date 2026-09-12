"""The projection seam.

`Projector` (`protocol.py`) is what the controller and `graph_engine.projector`
draw through; `TableProjector` (`table.py`) is the Postgres-table
implementation and the only module in the repo that reads or writes the
drawing's rows. A second projection kind — a search index, a real graph engine
if variable-length traversal ever becomes real — implements the same protocol
and plugs in where `TableProjector` does: `api/schema.py`, `api/context.py`,
and the management commands.
"""

from graph_engine.projection.context import current_or_default, current_projector, get_current_projector
from graph_engine.projection.protocol import DrawnEdge, DrawnOrder, IncidentEdge, IncidentEdgesSpec, ListDrawnSpec, Projector, PropertyPredicate
from graph_engine.projection.table import TableProjector

__all__ = ["DrawnEdge", "DrawnOrder", "IncidentEdge", "IncidentEdgesSpec", "ListDrawnSpec", "Projector", "PropertyPredicate", "TableProjector", "current_or_default", "current_projector", "get_current_projector"]
