





from core import models, types, enums, filters as f, pagination as p, age
import strawberry
from kante.types import Info

@strawberry.type
class PairedStructure:
    left: types.Entity
    right: types.Entity
    relation: types.EntityRelation






def paired_entities(info: Info, graph: strawberry.ID | None = None, relation_filter: f.EntityRelationFilter | None = None, left_filter: f.EntityFilter | None = None, right_filter: f.EntityFilter | None = None, pagination: p.GraphPaginationInput | None = None) -> list[PairedStructure]:

    if not left_filter:
        left_filter = f.EntityFilter()

    if not right_filter:
        right_filter = f.EntityFilter()

    if not relation_filter:
        relation_filter = f.EntityRelationFilter()

    if not pagination:
        pagination = p.GraphPaginationInput()


    

    graph = models.Graph.objects.get(id=graph) if graph else models.Graph.objects.filter(user=info.context.request.user).first()
    print(graph.name)

    
    return [PairedStructure(left=types.Entity(_value=left),right=types.Entity(_value=right), relation=types.EntityRelation(_value=edge)) for left, right, edge in age.select_paired_entities(graph.age_name, pagination, relation_filter, left_filter, right_filter)]
