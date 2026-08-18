from typing import cast

from kante.types import Info

import strawberry
from api import inputs, types
from api.mutations._scoped import scoped
from api.mutations.insights._saved_query import create_saved_query, update_saved_query
from core import models


def create_node_table_query(
    info: Info,
    input: inputs.CreateNodeTableQueryInput,
) -> types.NodeTableQuery:
    """Save a new node table query. See `api.mutations.insights._saved_query`."""
    return cast(types.NodeTableQuery, create_saved_query(info, input.to_pydantic(), models.NodeTableQuery, "node table query"))


def update_node_table_query(
    info: Info,
    input: inputs.UpdateNodeTableQueryInput,
) -> types.NodeTableQuery:
    """Change a saved node table query. See `api.mutations.insights._saved_query`."""
    return cast(types.NodeTableQuery, update_saved_query(info, input.to_pydantic(), models.NodeTableQuery, "node table query"))


def delete_node_table_query(
    info: Info,
    input: inputs.DeleteNodeTableQueryInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = scoped(info, models.NodeTableQuery, model.id, what="node table query")
    item.delete()
    return model.id


def archive_node_table_query(
    info: Info,
    input: inputs.ArchiveNodeTableQueryInput,
) -> types.NodeTableQuery:
    """Archive a saved node table query — a soft delete, so the row survives.

    Returns the node table query itself, and returned a bare `ID` before. `delete`
    returns an id because the row is gone and an id is all that is left to
    name it; `archive` leaves the row in place with `archived` set, and
    `archiveGraph` already returned the object for exactly that reason. The
    two spellings of one act disagreed about their own result type.
    """
    model = input.to_pydantic()
    item = scoped(info, models.NodeTableQuery, model.id, what="node table query")
    item.archived = True
    item.save()
    return cast(types.NodeTableQuery, item)
