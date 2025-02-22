import json
from core.age import RetrievedEntity, graph_cursor, RetrievedRelation, vertex_ag_to_retrieved_entity
import strawberry
from core import models, types, enums
import re
import json
import re
import json
from kante.types import Info
from core.renderers.utils import parse_age_path
from .path import path
from .table import table
from .pairs import pairs


def render_graph_view(graph_view: models.GraphView):
    
    if graph_view.query.kind == enums.ViewKind.PATH:
        return path(graph_view)
    if graph_view.query.kind == enums.ViewKind.TABLE:
        return table(graph_view)
    if graph_view.query.kind == enums.ViewKind.PAIRS:
        return pairs(graph_view)
    
    raise ValueError("Unknown view kind")
    
    
    