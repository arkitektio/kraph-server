from core import models, types, enums, filters as f, pagination as p, age
import strawberry
from kante.types import Info
from typing import Annotated





def pairs(
    graph_view: models.GraphView,
) -> types.Pairs:


    tgraph = graph_view.graph
    query = graph_view.query.query


    return types.Pairs(pairs=[
        types.Pair(
            left=types.Node(_value=left),
            right=types.Node(_value=right),
            relation=types.Edge(_value=edge),
        )
        for left, right, edge in age.select_paired_entities(
            tgraph.age_name, pagination, relation_filter, left_filter, right_filter
        )
    ], graph=tgraph)
