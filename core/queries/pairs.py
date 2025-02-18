from core import models, types, enums, filters as f, pagination as p, age
import strawberry
from kante.types import Info
from typing import Annotated


@strawberry.type(
    description="A paired structure two entities and the relation between them."
)
class Pair:
    left: types.Node = strawberry.field(description="The left entity.")
    right: types.Node = strawberry.field(description="The right entity.")
    edge: types.Edge = strawberry.field(
        description="The relation between the two entities."
    )


def pairs(
    info: Info,
    graph: strawberry.ID,
    query: str
) -> list[Pair]:

    if not query:
        raise ValueError("Query is required")



    return [
        Pair(
            left=types.Node(_value=left),
            right=types.Node(_value=right),
            relation=types.Edge(_value=edge),
        )
        for left, right, edge in age.select_paired_entities(
            graph.age_name, pagination, relation_filter, left_filter, right_filter
        )
    ]
