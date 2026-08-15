from typing import cast

from kante.types import Info

import strawberry
from api import inputs, types
from api.mutations._scoped import scoped
from api.mutations.insights._saved_query import create_saved_query, update_saved_query
from core import models


def create_edge_pairs_query(
    info: Info,
    input: inputs.CreateEdgePairsQueryInput,
) -> types.EdgePairsQuery:
    """Save a new edge pairs query. See `api.mutations.insights._saved_query`."""
    return cast(types.EdgePairsQuery, create_saved_query(info, input.to_pydantic(), models.EdgePairsQuery, "edge pairs query"))


def update_edge_pairs_query(
    info: Info,
    input: inputs.UpdateEdgePairsQueryInput,
) -> types.EdgePairsQuery:
    """Change a saved edge pairs query. See `api.mutations.insights._saved_query`."""
    return cast(types.EdgePairsQuery, update_saved_query(info, input.to_pydantic(), models.EdgePairsQuery, "edge pairs query"))


def delete_edge_pairs_query(
    info: Info,
    input: inputs.DeleteEdgePairsQueryInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = scoped(info, models.EdgePairsQuery, model.id, what="edge pairs query")
    item.delete()
    return model.id


def archive_edge_pairs_query(
    info: Info,
    input: inputs.ArchiveEdgePairsQueryInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = scoped(info, models.EdgePairsQuery, model.id, what="edge pairs query")
    item.archived = True
    item.save()
    return model.id
