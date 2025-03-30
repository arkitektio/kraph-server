from core import models, types, enums, filters as f, pagination as p, age
import strawberry
from kante.types import Info
from typing import Annotated


def pairs(
    node_query: models.NodeQuery,
    node_id: str,
) -> types.Pairs:

    tgraph = node_query.graph
    query = node_query.query

    raise NotImplementedError("Pairs view is not implemented yet")
