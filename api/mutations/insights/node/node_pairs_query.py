from kante.types import Info

import strawberry
from api import inputs, types
from core import models


def create_node_pairs_query(
    info: Info,
    input: inputs.CreateNodePairsQueryInput,
) -> types.NodePairsQuery:
    raise NotImplementedError("Creating node pairs queries is not implemented yet")


def update_node_pairs_query(
    info: Info,
    input: inputs.UpdateNodePairsQueryInput,
) -> types.NodePairsQuery:
    raise NotImplementedError


def delete_node_pairs_query(
    info: Info,
    input: inputs.DeleteNodePairsQueryInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = models.NodePairsQuery.objects.get(id=model.id)
    item.delete()
    return model.id


def archive_node_pairs_query(
    info: Info,
    input: inputs.ArchiveNodePairsQueryInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = models.NodePairsQuery.objects.get(id=model.id)
    item.archived = True
    item.save()
    return model.id
