from kante.types import Info
from core.datalayer import get_current_datalayer

import strawberry
from core import types, models, enums, scalars, inputs
from core import age
from strawberry.file_uploads import Upload
from django.conf import settings
from core.renderers.node import render
from django.contrib.auth import get_user_model


@strawberry.input(description="Input for creating a new expression")
class NodeQueryInput:
    graph: strawberry.ID = strawberry.field(
        description="The ID of the ontology this expression belongs to. If not provided, uses default ontology",
    )
    name: str = strawberry.field(description="The label/name of the expression")
    query: scalars.Cypher = strawberry.field(
        description="The label/name of the expression"
    )
    description: str | None = strawberry.field(
        default=None, description="A detailed description of the expression"
    )
    kind: enums.ViewKind = strawberry.field(
        default=None, description="The kind/type of this expression"
    )
    columns: list[inputs.ColumnInput] | None = strawberry.field(
        default=None, description="The columns (if ViewKind is Table)"
    )
    test_against: strawberry.ID | None = strawberry.field(
        default=None, description="The node to test against"
    )
    relevant_for: list[strawberry.ID] | None = strawberry.field(
        default=None,
        description="The list of categories this expression is relevant for",
    )
    pin: bool | None = strawberry.field(
        default=None,
        description="Whether to pin this expression for the current user",
    )


@strawberry.input(description="Input for updating an existing expression")
class UpdateNodeQueryInput(NodeQueryInput):
    id: strawberry.ID = strawberry.field(
        description="The ID of the expression to update"
    )
    pin: bool | None = strawberry.field(
        default=None,
        description="Whether to pin this expression for the current user",
    )


@strawberry.input(description="Input for deleting an expression")
class DeleteNodeQueryInput:
    id: strawberry.ID = strawberry.field(
        description="The ID of the expression to delete"
    )


def create_node_query(
    info: Info,
    input: NodeQueryInput,
) -> types.NodeQuery:

    graph = models.Graph.objects.get(id=input.graph)

    node_query, _ = models.NodeQuery.objects.update_or_create(
        graph=graph,
        query=input.query,
        defaults=dict(
            name=input.name,
            description=input.description,
            kind=input.kind,
            columns=(
                [strawberry.asdict(c) for c in input.columns] if input.columns else []
            ),
        ),
    )

    try:
        if not input.test_against:
            node = age.get_random_node(graph.age_name)
            node_id = node.unique_id

        else:
            node_id = input.test_against

        render.render_node_view(node_query, node_id)
    except Exception as e:
        node_query.delete()
        raise e
    
    if input.relevant_for:
        for category in input.relevant_for:
            category_obj = models.Category.objects.get(id=category)
            node_query.relevant_for_nodes.add(category_obj)

    return node_query


def delete_node_query(
    info: Info,
    input: DeleteNodeQueryInput,
) -> strawberry.ID:
    item = models.NodeQuery.objects.get(id=input.id)
    item.delete()
    return input.id


    
    



@strawberry.input
class PinNodeQueryInput:
    id: strawberry.ID
    pin: bool


def pin_node_query(
    info: Info,
    input: PinNodeQueryInput,
) -> types.NodeQuery:
    item = models.NodeQuery.objects.get(id=input.id)

    if input.pin:
        item.pinned_by.add(info.context.request.user)
    else:
        item.pinned_by.remove(info.context.request.user)

    item.save()
    return item
