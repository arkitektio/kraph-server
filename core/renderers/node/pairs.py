from core import models, types, enums, filters as f, pagination as p, age
import strawberry
from kante.types import Info
from typing import Annotated





def pairs(
    info: Info,
    node: strawberry.ID,
    query: str
) -> list[tuple[age.RetrievedEntity, age.RetrievedEntity, age.RetrievedRelation]]:

    if not query:
        raise ValueError("Query is required")



    return age.select_paired_entities(
            graph.age_name, pagination, relation_filter, left_filter, right_filter
        )
