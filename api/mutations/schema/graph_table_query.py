"""`createGraphTableQueryThroughBuilder` — the builder's spelling of a saved table query.

It used to compile its arguments to Cypher *here*, string-interpolating values,
and store that string as the query. It stores a **plan** now
(`graph_engine/query_ir.py`) — the same thing `createGraphTableQuery` stores —
and the projection kind in use compiles it at render time. Kept one release as an
alias; `createGraphTableQuery(input: {plan: …})` is the contract.
"""

from typing import cast

from kante.types import Info

from api import context, inputs, types
from api.mutations.insights._saved_query import plan_from_builder_args
from core import models
from graph_engine import input_models


def create_graph_table_query_through_builder(
    info: Info,
    input: inputs.CreateGraphTableQueryThroughBuilderInput,
) -> types.GraphTableQuery:
    """Create or update a graph table query from builder arguments. Upserts on `(graph, key)`."""
    model = input.to_pydantic()

    graph = context.get_accessible_graph(
        info,
        str(model.graph),
        actions=[input_models.Action.CREATE_BUILDER_ARG],
    )
    plan = plan_from_builder_args(model.builder_args, model.column_input)

    graph_table_query, _ = models.GraphTableQuery.objects.update_or_create(
        graph=graph,
        key=model.key,
        defaults={
            "label": model.name or model.key,
            "description": model.description,
            "kind": "TABLE",
            "plan": plan.to_stored(),
            "query": None,
            "columns": [column.model_dump(mode="json") for column in model.column_input],
        },
    )

    return cast(types.GraphTableQuery, graph_table_query)
