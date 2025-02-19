from core import models, types, enums, filters as f, pagination as p, age
import strawberry
from kante.types import Info
from typing import Annotated
from .pairs import pairs
from .path import path
from .node_path import node_path
from .node_pairs import node_pairs
from .table import table




def render_graph(
    info: Info,
    graph: strawberry.ID,
    query: strawberry.ID
) -> types.Path | types.Pairs | types.Table:
    

    tquery = models.GraphQuery.objects.get(id=query)


    if tquery.kind == enums.ViewKind.PATH:
        return path(info, graph, tquery.query)
    elif tquery.kind == enums.ViewKind.PAIRS:
        return pairs(info, graph, tquery.query)
    elif tquery.kind == enums.ViewKind.TABLE:
        return table(info, graph, tquery.query, tquery.input_columns)
    
    
    
def render_node(
    info: Info,
    node: strawberry.ID,
    query: strawberry.ID,
) -> types.Path | types.Pairs:
    

    tquery = models.NodeQuery.objects.get(id=query)


    if tquery.kind == enums.ViewKind.PATH:
        return node_path(info, node, tquery.query)
    elif tquery.kind == enums.ViewKind.PAIRS:
        return pairs(info, node, tquery.query)