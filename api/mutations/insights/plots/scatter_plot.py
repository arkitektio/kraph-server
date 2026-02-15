from kante.types import Info
import strawberry

from api import inputs, types
from core import models


def _resolve_plot_query(model) -> tuple[models.GraphTableQuery | None, models.NodeTableQuery | None, models.NodePathQuery | None]:
    graph_query = models.GraphTableQuery.objects.get(id=model.graph_query_id) if model.graph_query_id else None
    node_query = models.NodeTableQuery.objects.get(id=model.node_query_id) if model.node_query_id else None
    path_query = models.NodePathQuery.objects.get(id=model.path_query_id) if model.path_query_id else None

    if sum(1 for item in [graph_query, node_query, path_query] if item is not None) != 1:
        raise ValueError("Exactly one of graph_query_id, node_query_id, or path_query_id must be provided")

    return graph_query, node_query, path_query


def create_scatter_plot(info: Info, input: inputs.CreateScatterPlotInput) -> types.ScatterPlot:
    model = input.to_pydantic()
    graph_query, node_query, path_query = _resolve_plot_query(model)

    return models.ScatterPlot.objects.create(
        graph_query=graph_query,
        node_query=node_query,
        path_query=path_query,
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
    scatter_plot = models.ScatterPlot.objects.get(id=model.id)
    graph_query, node_query, path_query = _resolve_plot_query(model)

    scatter_plot.graph_query = graph_query
    scatter_plot.node_query = node_query
    scatter_plot.path_query = path_query
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
    item = models.ScatterPlot.objects.get(id=model.id)
    item.delete()
    return strawberry.ID(str(model.id))


def archive_scatter_plot(info: Info, input: inputs.ArchiveScatterPlotInput) -> strawberry.ID:
    model = input.to_pydantic()
    item = models.ScatterPlot.objects.get(id=model.id)
    item.delete()
    return strawberry.ID(str(model.id))
