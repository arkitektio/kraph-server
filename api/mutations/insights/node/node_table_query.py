from kante.types import Info

import strawberry
from api import inputs, types
from core import models


def create_node_table_query(
    info: Info,
    input: inputs.CreateNodeTableQueryInput,
) -> types.NodeTableQuery:
    raise NotImplementedError("Creating node table queries is not implemented yet")


def update_node_table_query(
    info: Info,
    input: inputs.UpdateNodeTableQueryInput,
) -> types.NodeTableQuery:
    raise NotImplementedError


def delete_node_table_query(
    info: Info,
    input: inputs.DeleteNodeTableQueryInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = models.NodeTableQuery.objects.get(id=model.id)
    item.delete()
    return model.id


def archive_node_table_query(
    info: Info,
    input: inputs.ArchiveNodeTableQueryInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = models.NodeTableQuery.objects.get(id=model.id)
    item.archived = True
    item.save()
    return model.id
