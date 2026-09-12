"""Rendering a saved graph table query."""

from typing import Optional
from kante.types import Info
import strawberry

from api import types, context, inputs
from api.mutations._scoped import scoped
from core import models


def render_graph_table(
    info: Info,
    query: strawberry.ID,
    filters: inputs.RenderGraphTableFilter | None = None,
    pagination: inputs.RenderGraphTablePagination | None = None,
    order: inputs.RenderGraphTableOrder | None = None,
) -> Optional[types.GraphTableRender]:
    """Run a saved table query and return its rows.

    Fetched through `scoped`, which is what the saved-query *mutations* use. This
    did `GraphTableQuery.objects.get(id=query)` on a bare integer primary key and
    trusted `GraphController._ensure_query_access` downstream — a stub that returned
    unconditionally — so any member of any tenant could render another organization's
    saved query, and read its graph through the rows that came back. A saved query
    belongs to one graph, so the graph is the boundary, exactly as it is for editing
    one.

    Args:
        info: Strawberry Info context
        query: The ID of the saved graph table query

    Returns:
        The rendered table, or None
    """

    controller = context.get_controller()

    graph_query = scoped(info, models.GraphTableQuery, query, what="graph table query")

    filters_model = filters.to_pydantic() if filters else None
    pagination_model = pagination.to_pydantic() if pagination else None
    order_model = order.to_pydantic() if order else None

    response = controller.render_graph_table_query(graph_query, filters=filters_model, pagination=pagination_model, order=order_model, info=info)

    return types.GraphTableRender(_value=response)
