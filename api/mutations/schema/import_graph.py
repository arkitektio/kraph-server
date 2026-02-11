from kante.types import Info
import strawberry
from api import types, inputs, context
from core import models


@strawberry.input(description="Input type for creating a new entity")
class ImportGraphInput:
    definition: inputs.GraphDefinitionInput = strawberry.field(description="The graph definition to import, including nodes and edges")
    entities: list[inputs.CreateEntityInput] = strawberry.field(description="List of nodes to import that will be created as entities if they don't already exist")
    relations: list[inputs.CreateRelationInput] = strawberry.field(description="List of edges to import that will be created as relations if they don't already exist")


def import_graph(
    info: Info,
    input: ImportGraphInput,
) -> types.Graph:
    raise NotImplementedError(
        "Graph import functionality is not yet implemented. This will allow users to import a graph definition along with associated entities and relations in a single operation, automatically creating any missing entities or relations as needed according to the provided graph definition."
    )
