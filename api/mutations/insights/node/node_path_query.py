from kante.types import Info

import strawberry
from api import inputs, types
from core import models


def create_node_path_query(
    info: Info,
    input: inputs.CreateNodePathQueryInput,
) -> types.NodePathQuery:
    raise NotImplementedError("Creating node path queries is not implemented yet")


def update_node_path_query(
    info: Info,
    input: inputs.UpdateNodePathQueryInput,
) -> types.NodePathQuery:
    raise NotImplementedError


def delete_node_path_query(
    info: Info,
    input: inputs.DeleteNodePathQueryInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = models.NodePathQuery.objects.get(id=model.id)
    item.delete()
    return model.id


def archive_node_path_query(
    info: Info,
    input: inputs.ArchiveNodePathQueryInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = models.NodePathQuery.objects.get(id=model.id)
    item.archived = True
    item.save()
    return model.id
