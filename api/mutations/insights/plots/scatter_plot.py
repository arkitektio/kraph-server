from kante.types import Info
import strawberry

from api import inputs, types
from api.mutations._scoped import scoped
from core import models


def _resolve_plot_query(info: Info, model) -> models.GraphTableQuery:
    """The saved table query this plot is drawn from, checked against the caller.

    A plot has no graph of its own — it reaches one through its query, which is
    why `_scoped.graph_of` walks it. This was a bare primary-key fetch, so a plot
    could be built over another tenant's saved query and would then render that
    tenant's data through `render_graph_table`.
    """
    return scoped(info, models.GraphTableQuery, model.graph_query_id, what="graph table query")


def _own_plot(info: Info, pk) -> models.ScatterPlot:
    """A plot the caller may change, which is a stricter test than tenancy.

    `ScatterPlot.creator` was already on the model and read by nothing —
    `update_scatter_plot` and `delete_scatter_plot` fetched by bare primary key,
    so one member of an organization could rewrite or destroy another's saved
    plots. Tenancy alone would not catch that, so both checks run: the graph
    boundary through `scoped`, then ownership.
    """
    plot = scoped(info, models.ScatterPlot, pk, what="scatter plot")

    user = info.context.request.user
    if not user.is_superuser and plot.creator_id != user.id:
        raise PermissionError("You do not have permission to change this scatter plot — it belongs to somebody else.")

    return plot


def create_scatter_plot(info: Info, input: inputs.CreateScatterPlotInput) -> types.ScatterPlot:
    model = input.to_pydantic()
    graph_query = _resolve_plot_query(info, model)

    return models.ScatterPlot.objects.create(
        graph_query=graph_query,
        name=model.name,
        description=model.description,
        id_column=model.id_column,
        x_column=model.x_column,
        x_id_column=model.x_id_column,
        y_column=model.y_column,
        y_id_column=model.y_id_column,
        color_column=model.color_column,
        size_column=model.size_column,
        shape_column=model.shape_column,
        creator=info.context.request.user,
    )


def update_scatter_plot(info: Info, input: inputs.UpdateScatterPlotInput) -> types.ScatterPlot:
    model = input.to_pydantic()
    scatter_plot = _own_plot(info, model.id)
    scatter_plot.graph_query = _resolve_plot_query(info, model)
    scatter_plot.name = model.name
    scatter_plot.description = model.description
    scatter_plot.id_column = model.id_column
    scatter_plot.x_column = model.x_column
    scatter_plot.x_id_column = model.x_id_column
    scatter_plot.y_column = model.y_column
    scatter_plot.y_id_column = model.y_id_column
    scatter_plot.color_column = model.color_column
    scatter_plot.size_column = model.size_column
    scatter_plot.shape_column = model.shape_column
    scatter_plot.save()

    return scatter_plot


def delete_scatter_plot(info: Info, input: inputs.DeleteScatterPlotInput) -> strawberry.ID:
    model = input.to_pydantic()
    item = _own_plot(info, model.id)
    item.delete()
    return strawberry.ID(str(model.id))


