from core import models, types, enums, filters as f, pagination as p, age
import strawberry


def edges(
    info,
    filters: f.EntityRelationFilter | None = None,
    pagination: p.GraphPaginationInput | None = None,
) -> list[types.Edge]:

    if not filters:
        filters = f.EntityFilter()

    if not pagination:
        pagination = p.GraphPaginationInput()

    print(filters.graph)

    graph = (
        models.Graph.objects.get(id=filters.graph)
        if filters.graph
        else models.Graph.objects.filter(user=info.context.request.user).last()
    )

    print("Called")

    return [
        types.Edge(_value=rel)
        for rel in age.select_all_relations(graph.age_name, pagination, filters)
    ]
