from core import models, types, enums, filters as f, pagination as p, age
import strawberry
from kante.types import Info
from typing import Annotated


def pairs(
    graph_query: models.GraphQuery,
) -> types.Pairs:

    tgraph = graph_query.graph
    query = graph_query.query

    raise NotImplementedError("Pairs view is not implemented yet")
