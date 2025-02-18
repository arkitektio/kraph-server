from core import models, types, enums, filters as f, pagination as p, age, scalars
import strawberry
from kante.types import Info


def structure(
    info: Info, graph: strawberry.ID, structure: scalars.StructureString
) -> types.Structure:

    the_graph = models.Graph.objects.get(id=graph)

    return types.Entity(_value=age.get_age_structure(the_graph.age_name, structure))
