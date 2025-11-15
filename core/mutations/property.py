from kante.types import Info
from core.utils import node_id_to_graph_id, node_id_to_graph_name
import strawberry
from core import types, models, age, inputs


@strawberry.input(description="Input type for creating a relation between two entities")
class SetNodePropertyInput:
    """Input type for creating a relation between two entities"""

    entity: strawberry.ID = strawberry.field(description="ID of the entity (format: graph:id)")
    variable: str = strawberry.field(description="ID of the variable (format: graph:id)")
    value: str = strawberry.field(description="The value to set for the variable")


@strawberry.input(description="Input type for deleting an entity relation")
class DeleteRelationInput:
    """Input type for deleting an entity relation"""

    id: strawberry.ID = strawberry.field(description="ID of the relation to delete")


def set_node_property(
    info: Info,
    input: SetNodePropertyInput,
) -> types.Node:
    retrieved_entity = age.set_entity_variable(
        node_id_to_graph_name(input.entity),
        node_id_to_graph_id(input.entity),
        input.variable,
        input.value,
    )

    return types.entity_to_node_subtype(retrieved_entity)
