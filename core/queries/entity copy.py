
from core import models, types, enums, filters as f, pagination as p, age
import strawberry
from kante.types import Info




def entities(info: Info, filters: f.EntityFilter | None = None, pagination: p.GraphPaginationInput | None = None) -> list[types.Entity]:

    if not filters:
        filters = f.EntityFilter()

    if not pagination:
        pagination = p.GraphPaginationInput()


    
    print(filters.graph)


    graph = models.Graph.objects.get(id=filters.graph) if filters.graph else models.Graph.objects.filter(user=info.context.request.user).last()


    
    return [types.Entity(_value=entity) for entity in age.select_all_entities(graph.age_name, pagination, filters)]
