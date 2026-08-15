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
) -> strawberry.ID:
    model = input.to_pydantic()
    item = scoped(info, models.GraphPairsQuery, model.id, what="graph pairs query")
    item.archived = True
    item.save()
    return model.id
