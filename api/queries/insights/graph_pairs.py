"""Rendering a saved pairs query: its pairs, live, from the view's drawing.

A preview: answered from the drawing as of its cursor, through the same compiler and cost
bound as every table query (`datasets.logic.render_pairs`). What a model trains on is a
run (`runPairsQuery`): the same answer, stored with where the drawing stood.
"""

from typing import List, Optional

import strawberry
from kante.types import Info
from strawberry_django.pagination import OffsetPaginationInput

from api import context, types
from api.mutations._scoped import scoped
from core import models
from graph_engine.input_models import clamp_window


def render_graph_pairs(info: Info, id: strawberry.ID, pagination: Optional[OffsetPaginationInput] = None) -> List[types.PairsQueryRow]:
    """The pairs a saved pairs query answers now, in a stable order, one page of them."""
    from datasets import logic

    query = scoped(info, models.GraphPairsQuery, id, what="pairs query")
    pairs = logic.render_pairs(context.get_controller(), query, info=info)
    offset, limit = clamp_window(getattr(pagination, "offset", None), getattr(pagination, "limit", None))
    return [types.PairsQueryRow(source_identifier=source[0], source_object=strawberry.ID(source[1]), target_identifier=target[0], target_object=strawberry.ID(target[1])) for source, target in pairs[offset : offset + limit]]
