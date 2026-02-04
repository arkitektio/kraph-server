import json
from core.age import (
    RetrievedEntity,
    graph_cursor,
    RetrievedRelation,
    vertex_ag_to_retrieved_entity,
)
import strawberry
from core import models, types, enums, inputs
import re
import json
import re
import json
from kante.types import Info
from core.renderers.utils import parse_age_path
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
