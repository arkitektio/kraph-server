from kante.types import Info
from core.datalayer import get_current_datalayer

import strawberry
from core import types, models, enums, scalars, inputs
from core import age
from strawberry.file_uploads import Upload
from django.conf import settings
from core.renderers.graph import render


@strawberry.input(description="Input for creating a new expression")
class ScatterPlotInput:
    query: strawberry.ID = strawberry.field(description="The query to use")
    name: str = strawberry.field(description="The label/name of the expression")
    description: str | None = strawberry.field(
        default=None, description="A detailed description of the expression"
    )
    id_column: str = strawberry.field(
        description="The column to use for the ID of the points"
    )
    x_column: str = strawberry.field(description="The column to use for the x-axis")
    x_id_column: str | None = strawberry.field(
        default=None, description="The column to use for the x-axis ID (node, or edge)"
    )
    y_column: str = strawberry.field(description="The column to use for the y-axis")
    y_id_column: str | None = strawberry.field(
        default=None, description="The column to use for the y-axis ID (node, or edge)"
    )
    size_column: str | None = strawberry.field(
        default=None, description="The column to use for the size of the points"
    )
    color_column: str | None = strawberry.field(
        default=None, description="The column to use for the color of the points"
    )
    shape_column: str | None = strawberry.field(
        default=None, description="The column to use for the shape of the points"
    )
    test_against: strawberry.ID | None = strawberry.field(
        default=None, description="The graph to test against"
    )


@strawberry.input(description="Input for updating an existing expression")
class UpdateScatterPlotInput(ScatterPlotInput):
    id: strawberry.ID = strawberry.field(
        description="The ID of the expression to update"
    )


@strawberry.input(description="Input for deleting an expression")
class DeleteScatterPlotInput:
    id: strawberry.ID = strawberry.field(
        description="The ID of the expression to delete"
    )


def check_column(
    columns: list[inputs.ColumnInput],
    name: str,
    assert_kind: list[enums.ColumnKind] | None = None,
) -> inputs.ColumnInput:
    for column in columns:
        if column.name == name:
            if assert_kind and column.kind not in assert_kind:
                raise ValueError(f"Column {name} is not of kind {assert_kind}")
            return column.name
    raise ValueError(f"Column {name} not found in query")


def check_id_column(columns: list[inputs.ColumnInput], name: str) -> inputs.ColumnInput:
    return check_column(columns, name, [enums.ColumnKind.NODE, enums.ColumnKind.EDGE])


def create_scatter_plot(
    info: Info,
    input: ScatterPlotInput,
) -> types.ScatterPlot:

    query = models.GraphQuery.objects.get(id=input.query)

    columns = query.input_columns

    id_column = check_id_column(columns, input.id_column)
    x_column = check_column(columns, input.x_column)
    y_column = check_column(columns, input.y_column)
    x_id_column = (
        check_id_column(columns, input.x_id_column) if input.x_id_column else None
    )
    y_id_column = (
        check_id_column(columns, input.y_id_column) if input.y_id_column else None
    )
    size_column = (
        check_column(columns, input.size_column) if input.size_column else None
    )
    color_column = (
        check_column(columns, input.color_column) if input.color_column else None
    )
    shape_column = (
        check_column(columns, input.shape_column) if input.shape_column else None
    )

    scatter_plot = models.ScatterPlot.objects.create(
        name=input.name,
        description=input.description,
        query=query,
        id_column=id_column,
        x_column=x_column,
        y_column=y_column,
        x_id_column=x_id_column,
        y_id_column=y_id_column,
        size_column=size_column,
        color_column=color_column,
        shape_column=shape_column,
        creator=info.context.request.user,
    )

    return scatter_plot


def delete_scatter_plot(
    info: Info,
    input: DeleteScatterPlotInput,
) -> strawberry.ID:
    item = models.ScatterPlot.objects.get(id=input.id)
    item.delete()
    return input.id
