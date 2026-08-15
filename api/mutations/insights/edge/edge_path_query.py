from typing import cast

from kante.types import Info

import strawberry
from api import inputs, types
from api.mutations._scoped import scoped
from api.mutations.insights._saved_query import create_saved_query, update_saved_query
from core import models


def create_edge_path_query(
    info: Info,
    input: inputs.CreateEdgePathQueryInput,
) -> types.EdgePathQuery:
    """Save a new edge path query. See `api.mutations.insights._saved_query`."""
    return cast(types.EdgePathQuery, create_saved_query(info, input.to_pydantic(), models.EdgePathQuery, "edge path query"))


def update_edge_path_query(
    info: Info,
    input: inputs.UpdateEdgePathQueryInput,
) -> types.EdgePathQuery:
    """Change a saved edge path query. See `api.mutations.insights._saved_query`."""
    return cast(types.EdgePathQuery, update_saved_query(info, input.to_pydantic(), models.EdgePathQuery, "edge path query"))


def delete_edge_path_query(
    info: Info,
    input: inputs.DeleteEdgePathQueryInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = scoped(info, models.EdgePathQuery, model.id, what="edge path query")
    item.delete()
    return model.id


def archive_edge_path_query(
    info: Info,
    input: inputs.ArchiveEdgePathQueryInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = scoped(info, models.EdgePathQuery, model.id, what="edge path query")
    item.archived = True
    item.save()
    return model.id
