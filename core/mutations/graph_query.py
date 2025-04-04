from kante.types import Info
from core.datalayer import get_current_datalayer

import strawberry
from core import types, models, enums, scalars, inputs
from core import age
from strawberry.file_uploads import Upload
from django.conf import settings
from core.renderers.graph import render


@strawberry.input(description="Input for creating a new expression")
class GraphQueryInput:
    graph: strawberry.ID = strawberry.field(
        default=None,
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
    relevant_for: list[strawberry.ID] | None = strawberry.field(
        default=None,
        description="A list of categories where this query is releveant and should be shown",
    )
    pin: bool | None = strawberry.field(
        default=None,
        description="Whether to pin this expression for the current user",
    )


@strawberry.input(description="Input for updating an existing expression")
class UpdateGraphQueryInput(GraphQueryInput):
    id: strawberry.ID = strawberry.field(
        description="The ID of the expression to update"
    )
    pin: bool | None = strawberry.field(
        default=None,
        description="Whether to pin this expression for the current user",
    )


@strawberry.input(description="Input for deleting an expression")
class DeleteGraphQueryInput:
    id: strawberry.ID = strawberry.field(
        description="The ID of the expression to delete"
    )


def create_graph_query(
    info: Info,
    input: GraphQueryInput,
) -> types.GraphQuery:

    graph_query, _ = models.GraphQuery.objects.update_or_create(
        graph_id=input.graph,
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
        render.render_graph_query(graph_query)
    except Exception as e:
        graph_query.delete()
        raise Exception(f"Failed to render graph query: {e}")

    if input.relevant_for:
        for category in input.relevant_for:
            category_obj = models.Category.objects.get(id=category)
            graph_query.relevant_for.add(category_obj)

    if input.pin is not None:
        if input.pin:
            graph_query.pinned_by.add(info.context.request.user)
        else:
            graph_query.pinned_by.remove(info.context.request.user)
            
    return graph_query


def delete_graph_query(
    info: Info,
    input: DeleteGraphQueryInput,
) -> strawberry.ID:
    item = models.NodeQuery.objects.get(id=input.id)
    item.delete()
    return input.id


@strawberry.input
class PinGraphQueryInput:
    id: strawberry.ID
    pin: bool


def pin_graph_query(
    info: Info,
    input: PinGraphQueryInput,
) -> types.GraphQuery:
    item = models.GraphQuery.objects.get(id=input.id)

    if input.pin:
        item.pinned_by.add(info.context.request.user)
    else:
        item.pinned_by.remove(info.context.request.user)

    item.save()
    return item
