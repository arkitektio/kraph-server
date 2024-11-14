from core import models, types, enums, filters as f, pagination as p, age
import strawberry
from kante.types import Info
from typing import Annotated


@strawberry.type(
    description="A paired structure two entities and the relation between them."
)
class PairedStructure:
    left: types.Entity = strawberry.field(description="The left entity.")
    right: types.Entity = strawberry.field(description="The right entity.")
    relation: types.EntityRelation = strawberry.field(
        description="The relation between the two entities."
    )


def paired_entities(
    info: Info,
    graph: Annotated[
        strawberry.ID | None,
        strawberry.argument(description="The graph to query the paired entities from"),
    ] = None,
    relation_filter: Annotated[
        f.EntityRelationFilter | None,
        strawberry.argument(description="The filter to apply to the relation"),
    ] = None,
    left_filter: Annotated[
        f.EntityFilter | None,
        strawberry.argument(
            description="The filter to apply to the left side of the relation"
        ),
    ] = None,
    right_filter: Annotated[
        f.EntityFilter | None,
        strawberry.argument(
            description="The filter to apply to the right side of the relation"
        ),
    ] = None,
    pagination: Annotated[
        p.GraphPaginationInput | None,
        strawberry.argument(description="The pagination to apply to the query"),
    ] = None,
) -> list[PairedStructure]:

    if not left_filter:
        left_filter = f.EntityFilter()

    if not right_filter:
        right_filter = f.EntityFilter()

    if not relation_filter:
        relation_filter = f.EntityRelationFilter()

    if not pagination:
        pagination = p.GraphPaginationInput()

    graph = (
        models.Graph.objects.get(id=graph)
        if graph
        else models.Graph.objects.filter(user=info.context.request.user).first()
    )
    print(graph.name)

    return [
        PairedStructure(
            left=types.Entity(_value=left),
            right=types.Entity(_value=right),
            relation=types.EntityRelation(_value=edge),
        )
        for left, right, edge in age.select_paired_entities(
            graph.age_name, pagination, relation_filter, left_filter, right_filter
        )
    ]
