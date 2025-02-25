from core import models, types, enums, filters as f, pagination as p, age, scalars
import strawberry
from kante.types import Info


def structure(self, info: Info, identifier: scalars.StructureIdentifier, object: strawberry.ID, graph: strawberry.ID | None = None) -> types.Structure:
        
    tgraph = models.Graph.objects.get(id=graph) if graph else models.Graph.objects.filter(user=info.context.request.user).first()

    return types.Structure(_value=age.get_age_structure(tgraph.age_name, f"{identifier}:{object}"))
