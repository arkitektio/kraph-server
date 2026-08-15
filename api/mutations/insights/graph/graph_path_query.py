from typing import cast

from kante.types import Info

import strawberry
from api import inputs, types
from api.mutations._scoped import scoped
from api.mutations.insights._saved_query import create_saved_query, update_saved_query
from core import models


def create_graph_path_query(
    info: Info,
    input: inputs.CreateGraphPathQueryInput,
) -> types.GraphPathQuery:
    """Save a new graph path query. See `api.mutations.insights._saved_query`."""
    return cast(types.GraphPathQuery, create_saved_query(info, input.to_pydantic(), models.GraphPathQuery, "graph path query"))


def update_graph_path_query(
    info: Info,
    input: inputs.UpdateGraphPathQueryInput,
) -> types.GraphPathQuery:
    """Change a saved graph path query. See `api.mutations.insights._saved_query`."""
    return cast(types.GraphPathQuery, update_saved_query(info, input.to_pydantic(), models.GraphPathQuery, "graph path query"))


def delete_graph_path_query(
    info: Info,
    input: inputs.DeleteGraphPathQueryInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = scoped(info, models.GraphPathQuery, model.id, what="graph path query")
    item.delete()
    return model.id


def archive_graph_path_query(
    info: Info,
    input: inputs.ArchiveGraphPathQueryInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = scoped(info, models.GraphPathQuery, model.id, what="graph path query")
    item.archived = True
    item.save()
    return model.id
