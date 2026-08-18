from typing import cast

from kante.types import Info

import strawberry
from api import inputs, types
from api.mutations._scoped import scoped
from api.mutations.insights._saved_query import create_saved_query, update_saved_query
from core import models


def create_node_path_query(
    info: Info,
    input: inputs.CreateNodePathQueryInput,
) -> types.NodePathQuery:
    """Save a new node path query. See `api.mutations.insights._saved_query`."""
    return cast(types.NodePathQuery, create_saved_query(info, input.to_pydantic(), models.NodePathQuery, "node path query"))


def update_node_path_query(
    info: Info,
    input: inputs.UpdateNodePathQueryInput,
) -> types.NodePathQuery:
    """Change a saved node path query. See `api.mutations.insights._saved_query`."""
    return cast(types.NodePathQuery, update_saved_query(info, input.to_pydantic(), models.NodePathQuery, "node path query"))


def delete_node_path_query(
    info: Info,
    input: inputs.DeleteNodePathQueryInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = scoped(info, models.NodePathQuery, model.id, what="node path query")
    item.delete()
    return model.id


def archive_node_path_query(
    info: Info,
    input: inputs.ArchiveNodePathQueryInput,
) -> types.NodePathQuery:
    """Archive a saved node path query — a soft delete, so the row survives.

    Returns the node path query itself, and returned a bare `ID` before. `delete`
    returns an id because the row is gone and an id is all that is left to
    name it; `archive` leaves the row in place with `archived` set, and
    `archiveGraph` already returned the object for exactly that reason. The
    two spellings of one act disagreed about their own result type.
    """
    model = input.to_pydantic()
    item = scoped(info, models.NodePathQuery, model.id, what="node path query")
    item.archived = True
    item.save()
    return cast(types.NodePathQuery, item)
