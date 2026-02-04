from kante.types import Info
from core.datalayer import get_current_datalayer

import strawberry
from core import types, models, enums, scalars, inputs
from core import age
from strawberry.file_uploads import Upload
from django.conf import settings
from core.renderers.graph import render


@strawberry.input(description="Input for creating a new expression")
class MatchPathInput:
    nodes: list[strawberry.ID] = strawberry.field(description="List of node IDs to match")
    relations: list[strawberry.ID] = strawberry.field(description="List of node IDs representing the path")
    optional: bool = strawberry.field(default=False, description="Whether the path match is optional")
    title: str | None = strawberry.field(default=None, description="Title for the matched path")
    color: list[float] | None = strawberry.field(default=None, description="Color for the matched path as RGB values")
    relation_directions: list[bool] | None = strawberry.field(
        default=None,
        description="List of booleans indicating the direction of each relationship in the path (True for outgoing, False for incoming)",
    )


@strawberry.input(description="Input for updating an existing expression")
class WhereClauseInput:
    path: strawberry.ID = strawberry.field(description="The path ID to apply the where clause to")
    node: strawberry.ID | None = strawberry.field(default=None, description="The node ID to apply the where clause to")
    property: str = strawberry.field(description="The property name to filter on")
    operator: enums.WhereOperator = strawberry.field(description="The operator to use for filtering")
    value: scalars.CypherLiteral = strawberry.field(description="The value to compare against")


@strawberry.input
class ReturnInput:
    path: strawberry.ID = strawberry.field(description="The path ID to return")
    node: strawberry.ID | None = strawberry.field(default=None, description="The node ID to return")
    property: str | None = strawberry.field(default=None, description="The property name to return")


@strawberry.input(description="Input for creating a new expression")
class GraphQueryInput:
    graph: strawberry.ID = strawberry.field(
        default=None,
        description="The ID of the ontology this expression belongs to. If not provided, uses default ontology",
    )
    name: str = strawberry.field(description="The label/name of the expression")
    query: scalars.Cypher = strawberry.field(default=None, description="The label/name of the expression")
    description: str | None = strawberry.field(default=None, description="A detailed description of the expression")
    kind: enums.ViewKind = strawberry.field(default=None, description="The kind/type of this expression")
    columns: list[inputs.ColumnInput] | None = strawberry.field(default=None, description="The columns (if ViewKind is Table)")
    node_category: strawberry.ID | None = strawberry.field(
        default=None,
        description="An optional node category to associate with this query (if its a node-list)",
    )
    relevant_for: list[strawberry.ID] | None = strawberry.field(
        default=None,
        description="A list of categories where this query is releveant and should be shown",
    )
    pin: bool | None = strawberry.field(
        default=None,
        description="Whether to pin this expression for the current user",
    )
    check_exists: bool = strawberry.field(
        default=True,
        description="If true, will check that the query can be rendered. If false, will skip this check.",
    )
    matches: list[MatchPathInput] | None = strawberry.field(
        default=None,
        description="List of paths to match in the query",
    )
    wheres: list[WhereClauseInput] | None = strawberry.field(
        default=None,
        description="List of where clauses to apply to the query",
    )
    returns: list[ReturnInput] | None = strawberry.field(
        default=None,
        description="List of return statements for the query",
    )


@strawberry.input(description="Input for updating an existing expression")
class UpdateGraphQueryInput(GraphQueryInput):
    id: strawberry.ID = strawberry.field(description="The ID of the expression to update")
    pin: bool | None = strawberry.field(
        default=None,
        description="Whether to pin this expression for the current user",
    )
    check_exists: bool = strawberry.field(
        default=True,
        description="If true, will check that the query can be rendered. If false, will skip this check.",
    )


@strawberry.input(description="Input for deleting an expression")
class DeleteGraphQueryInput:
    id: strawberry.ID = strawberry.field(description="The ID of the expression to delete")


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
            columns=([strawberry.asdict(c) for c in input.columns] if input.columns else []),
        ),
    )

    try:
        render.render_graph_query(graph_query, check_exists=input.check_exists)
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

    if input.matches is not None:
        graph_query.matches = [strawberry.asdict(m) for m in input.matches]

    if input.wheres is not None:
        graph_query.wheres = [strawberry.asdict(w) for w in input.wheres]

    if input.returns is not None:
        graph_query.returns = [strawberry.asdict(r) for r in input.returns]

    graph_query.save()

    return graph_query


def update_graph_query(info: Info, input: UpdateGraphQueryInput) -> types.GraphQuery:
    item = models.GraphQuery.objects.get(id=input.id)

    item.name = input.name
    item.query = input.query
    item.description = input.description
    item.kind = input.kind
    item.columns = [strawberry.asdict(c) for c in input.columns] if input.columns else []

    try:
        render.render_graph_query(item, check_exists=input.check_exists)
    except Exception as e:
        raise Exception(f"Failed to render graph query: {e}")

    item.relevant_for.clear()
    if input.relevant_for:
        for category in input.relevant_for:
            category_obj = models.Category.objects.get(id=category)
            item.relevant_for.add(category_obj)

    if input.pin is not None:
        if input.pin:
            item.pinned_by.add(info.context.request.user)
        else:
            item.pinned_by.remove(info.context.request.user)

    if input.matches is not None:
        item.matches = [strawberry.asdict(m) for m in input.matches]

    if input.wheres is not None:
        item.wheres = [strawberry.asdict(w) for w in input.wheres]

    if input.returns is not None:
        item.returns = [strawberry.asdict(r) for r in input.returns]

    item.save()
    return item


def delete_graph_query(
    info: Info,
    input: DeleteGraphQueryInput,
) -> strawberry.ID:
    item = models.GraphQuery.objects.get(id=input.id)
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
