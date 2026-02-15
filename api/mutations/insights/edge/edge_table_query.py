from kante.types import Info

import strawberry
from api import inputs, types
from core import models


def create_edge_table_query(
    info: Info,
    input: inputs.CreateEdgeTableQueryInput,
) -> types.EdgeTableQuery:
    raise NotImplementedError("Creating edge table queries is not implemented yet")


def update_edge_table_query(
    info: Info,
    input: inputs.UpdateEdgeTableQueryInput,
) -> types.EdgeTableQuery:
    raise NotImplementedError


def delete_edge_table_query(
    info: Info,
    input: inputs.DeleteEdgeTableQueryInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = models.EdgeTableQuery.objects.get(id=model.id)
    item.delete()
    return model.id


def archive_edge_table_query(
    info: Info,
    input: inputs.ArchiveEdgeTableQueryInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = models.EdgeTableQuery.objects.get(id=model.id)
    item.archived = True
    item.save()
    return model.id
