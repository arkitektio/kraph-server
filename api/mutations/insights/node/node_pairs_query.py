from typing import cast

from kante.types import Info

import strawberry
from api import inputs, types
from api.mutations._scoped import scoped
from api.mutations.insights._saved_query import create_saved_query, update_saved_query
from core import models


def create_node_pairs_query(
    info: Info,
    input: inputs.CreateNodePairsQueryInput,
) -> types.NodePairsQuery:
    """Save a new node pairs query. See `api.mutations.insights._saved_query`."""
    return cast(types.NodePairsQuery, create_saved_query(info, input.to_pydantic(), models.NodePairsQuery, "node pairs query"))


def update_node_pairs_query(
    info: Info,
    input: inputs.UpdateNodePairsQueryInput,
) -> types.NodePairsQuery:
    """Change a saved node pairs query. See `api.mutations.insights._saved_query`."""
    return cast(types.NodePairsQuery, update_saved_query(info, input.to_pydantic(), models.NodePairsQuery, "node pairs query"))


def delete_node_pairs_query(
    info: Info,
    input: inputs.DeleteNodePairsQueryInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = scoped(info, models.NodePairsQuery, model.id, what="node pairs query")
    item.delete()
    return model.id


def archive_node_pairs_query(
    info: Info,
    input: inputs.ArchiveNodePairsQueryInput,
) -> types.NodePairsQuery:
    """Archive a saved node pairs query — a soft delete, so the row survives.

    Returns the node pairs query itself, and returned a bare `ID` before. `delete`
    returns an id because the row is gone and an id is all that is left to
    name it; `archive` leaves the row in place with `archived` set, and
    `archiveGraph` already returned the object for exactly that reason. The
    two spellings of one act disagreed about their own result type.
    """
    model = input.to_pydantic()
    item = scoped(info, models.NodePairsQuery, model.id, what="node pairs query")
    item.archived = True
    item.save()
    return cast(types.NodePairsQuery, item)
