"""Rendering a table plan that is not saved."""

from typing import Optional

import strawberry
from kante.types import Info

from api import context, inputs, types
from graph_engine import query_ir, retrieved


def render_table_plan(
    info: Info,
    graph: strawberry.ID,
    plan: inputs.TableQueryPlanInput,
    filters: Optional[inputs.RenderGraphTableFilter] = None,
    pagination: Optional[inputs.RenderGraphTablePagination] = None,
    order: Optional[inputs.RenderGraphTableOrder] = None,
) -> types.TablePlanRender:
    """Run a plan against a view without saving it, and return its rows.

    The same compile-and-render path as `renderGraphTable` — labels resolved
    against the view's namespace, every value a parameter, the render filter over
    a returned alias — for a plan the client is still writing. Nothing is
    written: the plan is echoed back as compiled, so a client can save exactly
    what it saw. The view is resolved through `get_accessible_graph`, the same
    boundary `nodes(graph:)` has.
    """
    controller = context.get_controller()
    graph_model = context.get_accessible_graph(info, graph)
    plan_model = query_ir.plan_from_input(plan.to_pydantic(), [], controller.projector)

    rows = controller.render_table_plan(
        graph_model,
        plan_model,
        filters=filters.to_pydantic() if filters else None,
        order=order.to_pydantic() if order else None,
        pagination=pagination.to_pydantic() if pagination else None,
        info=info,
    )
    return types.TablePlanRender(_value=retrieved.RetrievedTablePlanRender(graph_id=int(graph_model.pk), plan=plan_model, rows=rows))
