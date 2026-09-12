from typing import cast

from kante.types import Info

import strawberry
from api import inputs, types
from api.mutations._scoped import scoped
from api.mutations.insights._saved_query import create_saved_query, update_saved_query
from core import models


def create_graph_table_query(
    info: Info,
    input: inputs.CreateGraphTableQueryInput,
) -> types.GraphTableQuery:
    """Save a new graph table query. See `api.mutations.insights._saved_query`."""
    return cast(types.GraphTableQuery, create_saved_query(info, input.to_pydantic(), models.GraphTableQuery, "graph table query"))


def update_graph_table_query(
    info: Info,
    input: inputs.UpdateGraphTableQueryInput,
) -> types.GraphTableQuery:
    """Change a saved graph table query. See `api.mutations.insights._saved_query`."""
    return cast(types.GraphTableQuery, update_saved_query(info, input.to_pydantic(), models.GraphTableQuery, "graph table query"))


def delete_graph_table_query(
    info: Info,
    input: inputs.DeleteGraphTableQueryInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = scoped(info, models.GraphTableQuery, model.id, what="graph table query")
    item.delete()
    return model.id


def archive_graph_table_query(
    info: Info,
    input: inputs.ArchiveGraphTableQueryInput,
) -> types.GraphTableQuery:
    """Archive a saved graph table query — a soft delete, so the row survives.

    Returns the graph table query itself, and returned a bare `ID` before. `delete`
    returns an id because the row is gone and an id is all that is left to
    name it; `archive` leaves the row in place with `archived` set, and
    `archiveGraph` already returned the object for exactly that reason. The
    two spellings of one act disagreed about their own result type.
    """
    model = input.to_pydantic()
    item = scoped(info, models.GraphTableQuery, model.id, what="graph table query")
    item.archived = True
    item.save()
    return cast(types.GraphTableQuery, item)
