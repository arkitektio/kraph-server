from core import models, types, enums, filters as f, pagination as p, age
import strawberry
from kante.types import Info
from typing import Annotated
from .pairs import pairs
from .path import path




def render_graph(
    info: Info,
    graph: strawberry.ID,
    query: strawberry.ID
) -> types.Path | types.Pairs:
    

    tgraph = models.Graph.objects.get(id=graph)
    tquery = models.GraphQuery.objects.get(id=query)


    if tquery.kind == enums.ViewKind.PATH:
        return path(info, graph, tquery.query)
    elif tquery.kind == enums.ViewKind.PAIRS:
        return pairs(info, graph, tquery.query)