"""Creating and updating a saved table query — the plan is what is saved.

`GraphQuery.plan` (`graph_engine.query_ir.TableQueryPlan`) is the contract: what
a client sends, what comes back, and what each projection kind compiles. Nothing
here accepts raw Cypher any more; the old `query` column is read-only legacy.

**Nothing here passes `kind`.** `managers.KindedManager` stamps it from the proxy
being used, so `models.GraphTableQuery.objects.create(...)` writes `kind="TABLE"`
by itself.
"""

from typing import Any

from kante.types import Info

from api.mutations._scoped import accessible_graph, scoped
from graph_engine.query_ir import TableQueryPlan


def plan_from_input(plan_input: Any, columns: Any) -> TableQueryPlan:
    """A validated plan from the mutation's input, with the columns folded in."""
    plan = TableQueryPlan(
        matches=list(plan_input.matches or []),
        wheres=list(plan_input.wheres or []),
        returns=list(plan_input.returns or []),
        columns=list(columns or []),
    )
    # Validate once, against nothing, so a plan that cannot be compiled is
    # refused at save time rather than at the first render. Through the bound
    # projector, not a hand-made TableProjector: the projection kind is the
    # seam, and save-time validation is part of it.
    from graph_engine.projection.context import current_or_default

    current_or_default().validate_plan(plan)
    return plan


def plan_from_builder_args(builder_args: Any, columns: Any) -> TableQueryPlan:
    """The builder's spelling (`match_paths` / `where_clauses` / `return_statements`) as a plan."""

    class _Shim:
        matches = list(builder_args.match_paths or [])
        wheres = list(builder_args.where_clauses or [])
        returns = list(builder_args.return_statements or [])

    return plan_from_input(_Shim, columns)


def create_saved_query(info: Info, model: Any, django_model: Any, what: str) -> Any:
    """Save a new table query against the graph it names.

    `accessible_graph` before anything is written: the graph id arrives from the
    client, so without it a caller could save a query into another tenant's view
    — and a saved query is executed later against that view's data.
    """
    graph = accessible_graph(info, model.graph)
    plan = plan_from_input(model.plan, model.column_input)

    return django_model.objects.create(
        graph=graph,
        key=model.key,
        plan=plan.to_stored(),
        columns=[column.model_dump(mode="json") for column in model.column_input],
        # The label is what a UI shows; falling back to the key means a query is
        # never nameless, which `label` being non-null on the model requires.
        label=model.name or model.key,
        description=model.description,
    )


def update_saved_query(info: Info, model: Any, django_model: Any, what: str) -> Any:
    """Change a saved query the caller is allowed to reach. Patches only what was sent."""
    item = scoped(info, django_model, model.id, what=what)

    if model.key is not None:
        item.key = model.key
    if model.name is not None:
        item.label = model.name
    if model.description is not None:
        item.description = model.description

    columns = model.column_input
    if columns is not None:
        item.columns = [column.model_dump(mode="json") for column in columns]

    if model.plan is not None:
        plan = plan_from_input(model.plan, columns if columns is not None else item.columns)
        item.plan = plan.to_stored()
        # A row that gets a plan stops being legacy; its stored Cypher is no
        # longer what renders and is cleared so the two cannot disagree.
        item.query = None

    item.save()
    return item
