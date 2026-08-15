from typing import cast

from kante.types import Info

import strawberry
from api import inputs, types
from api.mutations._scoped import scoped
from api.mutations.insights._saved_query import create_saved_query, update_saved_query
from core import models


def create_edge_table_query(
    info: Info,
    input: inputs.CreateEdgeTableQueryInput,
) -> types.EdgeTableQuery:
    """Save a new edge table query. See `api.mutations.insights._saved_query`."""
    return cast(types.EdgeTableQuery, create_saved_query(info, input.to_pydantic(), models.EdgeTableQuery, "edge table query"))


def update_edge_table_query(
    info: Info,
    input: inputs.UpdateEdgeTableQueryInput,
) -> types.EdgeTableQuery:
    """Change a saved edge table query. See `api.mutations.insights._saved_query`."""
    return cast(types.EdgeTableQuery, update_saved_query(info, input.to_pydantic(), models.EdgeTableQuery, "edge table query"))


def delete_edge_table_query(
    info: Info,
    input: inputs.DeleteEdgeTableQueryInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = scoped(info, models.EdgeTableQuery, model.id, what="edge table query")
    item.delete()
    return model.id


def archive_edge_table_query(
    info: Info,
    input: inputs.ArchiveEdgeTableQueryInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = scoped(info, models.EdgeTableQuery, model.id, what="edge table query")
    item.archived = True
    item.save()
    return model.id
