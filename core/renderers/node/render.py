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


def render_node_view(node_query: models.NodeQuery, node_id: str, filters: inputs.NodeQueryFilters | None = None , pagination: inputs.NodeQueryPagination | None = None, order: inputs.NodeQueryOrder | None = None):

    if node_query.kind == enums.ViewKind.PATH:
        return path(node_query, node_id, filters=filters, pagination=pagination, order=order)
    if node_query.kind == enums.ViewKind.TABLE:
        return table(node_query, node_id, filters=filters, pagination=pagination, order=order)
    if node_query.kind == enums.ViewKind.PAIRS:
        return pairs(node_query, node_id, filters=filters, pagination=pagination, order=order)

    raise ValueError("Unknown view kind")
