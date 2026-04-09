from kante.types import Info

import strawberry
from api import inputs, types
from core import models


def create_edge_pairs_query(
    info: Info,
    input: inputs.CreateEdgePairsQueryInput,
) -> types.EdgePairsQuery:
    raise NotImplementedError("Creating edge pairs queries is not implemented yet")


def update_edge_pairs_query(
    info: Info,
    input: inputs.UpdateEdgePairsQueryInput,
) -> types.EdgePairsQuery:
    raise NotImplementedError


def delete_edge_pairs_query(
    info: Info,
    input: inputs.DeleteEdgePairsQueryInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = models.EdgePairsQuery.objects.get(id=model.id)
    item.delete()
    return model.id


def archive_edge_pairs_query(
    info: Info,
    input: inputs.ArchiveEdgePairsQueryInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = models.EdgePairsQuery.objects.get(id=model.id)
    item.archived = True
    item.save()
    return model.id
