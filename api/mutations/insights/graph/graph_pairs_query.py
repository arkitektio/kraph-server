from typing import cast

from kante.types import Info

import strawberry
from api import inputs, types
from api.mutations._scoped import scoped
from api.mutations.insights._saved_query import create_saved_query, update_saved_query
from core import models


def create_graph_pairs_query(
    info: Info,
    input: inputs.CreateGraphPairsQueryInput,
) -> types.GraphPairsQuery:
    """Save a new graph pairs query. See `api.mutations.insights._saved_query`."""
    return cast(types.GraphPairsQuery, create_saved_query(info, input.to_pydantic(), models.GraphPairsQuery, "graph pairs query"))


def update_graph_pairs_query(
    info: Info,
    input: inputs.UpdateGraphPairsQueryInput,
) -> types.GraphPairsQuery:
    """Change a saved graph pairs query. See `api.mutations.insights._saved_query`."""
    return cast(types.GraphPairsQuery, update_saved_query(info, input.to_pydantic(), models.GraphPairsQuery, "graph pairs query"))


def delete_graph_pairs_query(
    info: Info,
    input: inputs.DeleteGraphPairsQueryInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = scoped(info, models.GraphPairsQuery, model.id, what="graph pairs query")
    item.delete()
    return model.id


def archive_graph_pairs_query(
    info: Info,
    input: inputs.ArchiveGraphPairsQueryInput,
) -> types.GraphPairsQuery:
    """Archive a saved graph pairs query — a soft delete, so the row survives.

    Returns the graph pairs query itself, and returned a bare `ID` before. `delete`
    returns an id because the row is gone and an id is all that is left to
    name it; `archive` leaves the row in place with `archived` set, and
    `archiveGraph` already returned the object for exactly that reason. The
    two spellings of one act disagreed about their own result type.
    """
    model = input.to_pydantic()
    item = scoped(info, models.GraphPairsQuery, model.id, what="graph pairs query")
    item.archived = True
    item.save()
    return cast(types.GraphPairsQuery, item)
