from kante.types import Info
from core.utils import node_id_to_graph_id, node_id_to_graph_name
import strawberry
from core import types, models, age, inputs, scalars


@strawberry.input(description="Input type for creating a relation between two entities")
class SetNodePropertyInput:
    """Input type for creating a relation between two entities"""

    entity: strawberry.ID = strawberry.field(description="ID of the entity (format: graph:id)")
    variable: str = strawberry.field(description="ID of the variable (format: graph:id)")
    value: scalars.Any = strawberry.field(description="The value to set for the variable")


@strawberry.input(description="Input type for deleting an entity relation")
class DeleteRelationInput:
    """Input type for deleting an entity relation"""

    id: strawberry.ID = strawberry.field(description="ID of the relation to delete")


def set_node_property(
    info: Info,
    input: SetNodePropertyInput,
) -> types.Node:
    user_id = str(info.context.request.user.id) if info.context.request.user and hasattr(info.context.request.user, "id") else None

    retrieved_entity = age.set_entity_variable(
        node_id_to_graph_name(input.entity),
        node_id_to_graph_id(input.entity),
        input.variable,
        input.value,
        created_by=user_id,
    )

    return types.entity_to_node_subtype(retrieved_entity)
