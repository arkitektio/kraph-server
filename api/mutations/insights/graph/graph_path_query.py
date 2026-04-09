from kante.types import Info

import strawberry
from api import inputs, types
from core import models


def create_graph_path_query(
    info: Info,
    input: inputs.CreateGraphPathQueryInput,
) -> types.GraphPathQuery:
    raise NotImplementedError("Creating graph path queries is not implemented yet")


def update_graph_path_query(
    info: Info,
    input: inputs.UpdateGraphPathQueryInput,
) -> types.GraphPathQuery:
    raise NotImplementedError


def delete_graph_path_query(
    info: Info,
    input: inputs.DeleteGraphPathQueryInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = models.GraphPathQuery.objects.get(id=model.id)
    item.delete()
    return model.id


def archive_graph_path_query(
    info: Info,
    input: inputs.ArchiveGraphPathQueryInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = models.GraphPathQuery.objects.get(id=model.id)
    item.archived = True
    item.save()
    return model.id
