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
) -> strawberry.ID:
    model = input.to_pydantic()
    item = scoped(info, models.NodeTableQuery, model.id, what="node table query")
    item.archived = True
    item.save()
    return model.id
