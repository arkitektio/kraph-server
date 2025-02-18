from core import models, types, enums, filters as f, pagination as p, age
import strawberry
from kante.types import Info
from typing import Annotated





def pairs(
    info: Info,
    graph: strawberry.ID,
    query: str
) -> list[types.Pair]:

    if not query:
        raise ValueError("Query is required")



    return [
        types.Pair(
            left=types.Node(_value=left),
            right=types.Node(_value=right),
            relation=types.Edge(_value=edge),
        )
        for left, right, edge in age.select_paired_entities(
            graph.age_name, pagination, relation_filter, left_filter, right_filter
        )
    ]
