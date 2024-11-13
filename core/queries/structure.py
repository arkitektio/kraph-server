
from core import models, types, enums, filters as f, pagination as p, age, scalars
import strawberry
from kante.types import Info




def structure(info: Info, graph: strawberry.ID, structure: scalars.StructureString) -> types.Entity:

    graph = models.Graph.objects.get(id=graph)

    
    return [types.Entity(_value=entity) for entity in age.get_age_structure(graph.age_name, structure)]
