from core import models, types, enums, inputs
from .path import path
from .table import table
from .pairs import pairs
from .node_list import node_list


def render_graph_query(graph_query: models.GraphQuery, check_exists: bool = False, filters: inputs.GraphQueryFilters | None = None, pagination: inputs.GraphQueryPagination | None = None, order: inputs.GraphQueryOrder | None = None) -> types.Path | types.Table | types.Pairs | types.NodeList:
    if graph_query.kind == enums.ViewKind.PATH:
        return path(graph_query, check_exists=check_exists, filters=filters, pagination=pagination, order=order)
    if graph_query.kind == enums.ViewKind.TABLE:
        return table(graph_query, check_exists=check_exists, filters=filters, pagination=pagination, order=order)
    if graph_query.kind == enums.ViewKind.PAIRS:
        return pairs(graph_query, check_exists=check_exists, filters=filters, pagination=pagination, order=order)
    if graph_query.kind == enums.ViewKind.NODE_LIST:
        return node_list(graph_query, check_exists=check_exists, filters=filters, pagination=pagination, order=order)

    raise ValueError("Unknown view kind")
