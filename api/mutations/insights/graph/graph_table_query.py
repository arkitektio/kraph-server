from kante.types import Info

import strawberry
from api import inputs, types, context
from graph_engine import scalars
from core import models


def create_graph_table_query(
    info: Info,
    input: inputs.CreateGraphTableQueryInput,
) -> types.GraphTableQuery:
    raise NotImplementedError("Creating graph queries through builders is not implemented yet")


def create_graph_table_query_through_builder(
    info: Info,
    input: inputs.CreateGraphTableQueryThroughBuilderInput,
) -> types.GraphTableQuery:
    raise NotImplementedError("Creating graph queries through builders is not implemented yet")


def update_graph_table_query(info: Info, input: inputs.UpdateGraphTableQueryInput) -> types.GraphTableQuery:
    raise NotImplementedError


def delete_graph_table_query(
    info: Info,
    input: inputs.DeleteGraphTableQueryInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = models.GraphTableQuery.objects.get(id=model.id)
    item.delete()
    return model.id


def archive_graph_table_query(
    info: Info,
    input: inputs.ArchiveGraphTableQueryInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = models.GraphTableQuery.objects.get(id=model.id)
    item.archived = True
    item.save()
    return model.id
