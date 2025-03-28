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


def render_graph_query(graph_query: models.GraphQuery):
    
    if graph_query.kind == enums.ViewKind.PATH:
        return path(graph_query)
    if graph_query.kind == enums.ViewKind.TABLE:
        return table(graph_query)
    if graph_query.kind == enums.ViewKind.PAIRS:
        return pairs(graph_query)
    
    raise ValueError("Unknown view kind")
    
    
    