from kante.types import Info

import strawberry
from api import inputs, types
from core import models


def create_edge_path_query(
    info: Info,
    input: inputs.CreateEdgePathQueryInput,
) -> types.EdgePathQuery:
    raise NotImplementedError("Creating edge path queries is not implemented yet")


def update_edge_path_query(
    info: Info,
    input: inputs.UpdateEdgePathQueryInput,
) -> types.EdgePathQuery:
    raise NotImplementedError


def delete_edge_path_query(
    info: Info,
    input: inputs.DeleteEdgePathQueryInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = models.EdgePathQuery.objects.get(id=model.id)
    item.delete()
    return model.id


def archive_edge_path_query(
    info: Info,
    input: inputs.ArchiveEdgePathQueryInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = models.EdgePathQuery.objects.get(id=model.id)
    item.archived = True
    item.save()
    return model.id
