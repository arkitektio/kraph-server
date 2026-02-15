from kante.types import Info

import strawberry
from api import inputs, types
from core import models


def create_graph_pairs_query(
    info: Info,
    input: inputs.CreateGraphPairsQueryInput,
) -> types.GraphPairsQuery:
    raise NotImplementedError("Creating graph pairs queries is not implemented yet")


def update_graph_pairs_query(
    info: Info,
    input: inputs.UpdateGraphPairsQueryInput,
) -> types.GraphPairsQuery:
    raise NotImplementedError


def delete_graph_pairs_query(
    info: Info,
    input: inputs.DeleteGraphPairsQueryInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = models.GraphPairsQuery.objects.get(id=model.id)
    item.delete()
    return model.id


def archive_graph_pairs_query(
    info: Info,
    input: inputs.ArchiveGraphPairsQueryInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = models.GraphPairsQuery.objects.get(id=model.id)
    item.archived = True
    item.save()
    return model.id
