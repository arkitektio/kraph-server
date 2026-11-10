"""Saving, changing and deleting a pairs query: an insight over one view whose runs are training sets.

The plan is the contract, as for table queries (`_saved_query`): a match over the view's
drawing and which two of its nodes are the pair, validated by compiling its lowering
(`query_ir.pairs_plan_from_input`) before anything is saved.
"""

import strawberry
from django.db.models import RestrictedError
from kante.types import Info

from api import inputs, types
from api.mutations._scoped import accessible_graph, scoped
from core import models
from graph_engine import query_ir


def create_graph_pairs_query(info: Info, input: inputs.CreateGraphPairsQueryInput) -> types.GraphPairsQuery:
    """Save a pairs query against the view it names."""
    model = input.to_pydantic()
    graph = accessible_graph(info, model.graph)
    plan = query_ir.pairs_plan_from_input(model.plan)
    return models.GraphPairsQuery.objects.create(  # type: ignore[return-value]
        graph=graph,
        key=model.key,
        plan=plan.to_stored(),
        columns=[],
        label=model.name or model.key,
        description=model.description,
    )


def update_graph_pairs_query(info: Info, input: inputs.UpdateGraphPairsQueryInput) -> types.GraphPairsQuery:
    """Change a saved pairs query. Its runs keep the plan they were run with."""
    model = input.to_pydantic()
    item = scoped(info, models.GraphPairsQuery, model.id, what="pairs query")
    if model.key is not None:
        item.key = model.key
    if model.name is not None:
        item.label = model.name
    if model.description is not None:
        item.description = model.description
    if model.plan is not None:
        item.plan = query_ir.pairs_plan_from_input(model.plan).to_stored()
    item.save()
    return item  # type: ignore[return-value]


def delete_graph_pairs_query(info: Info, input: inputs.DeleteGraphTableQueryInput) -> strawberry.ID:
    """Delete a pairs query, refused while it has runs: they are what models were trained on."""
    model = input.to_pydantic()
    item = scoped(info, models.GraphPairsQuery, model.id, what="pairs query")
    try:
        item.delete()
    except RestrictedError as error:
        raise ValueError(f"Pairs query {model.id} has {len(error.restricted_objects)} run(s): delete them first") from error
    return model.id
