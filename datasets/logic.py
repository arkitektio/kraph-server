"""Running a pairs query into a stored result, and what queries, runs and models say about themselves.

`run_pairs_query` is the one place a training set is made. It renders the query's plan
against its view's drawing (`Projector.render_table`, through the controller: the same
compiler, validation and cost bound as every table query), and stores what came back with
where the drawing stood: the lower of the view's projection cursor and the log's committed
horizon, read before the render, so every pair the run holds was drawn from a log that
reached at least that seq. The drawing has no "as of" (RFC 0014): the stored answer is the
only exact record of what a model learned from.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from authentikate.models import Organization
from django.db import transaction

from core import models as core_models
from datasets import models
from evidence import log as log_module
from evidence import models as evidence_models
from graph_engine import query_ir, watermark
from graph_engine.input_models import RenderGraphTableOrder

if TYPE_CHECKING:
    from graph_engine.controller import GraphController

#: How a drawn instance travels as one end of a pair: kraph's own structure for it.
ENTITY_IDENTIFIER = "@kraph/entity"


class RunRefused(ValueError):
    """The run asked for cannot be made: the reason says which part of the request."""


def horizon(organization: Organization) -> int:
    """The highest seq every act of the organization at or below which is committed."""
    return log_module.horizon(evidence_models.Assertion.objects.for_organization(organization))


def pairs_plan(query: core_models.GraphQuery) -> query_ir.PairsQueryPlan:
    """A pairs query's plan, refused when the row carries none."""
    plan = query_ir.PairsQueryPlan.from_stored(query.plan)
    if plan is None:
        raise RunRefused(f"Pairs query #{query.pk} has no plan")
    return plan


def _end(identifier: Any, obj: Any, ref: Any) -> tuple[str, str]:  # noqa: ANN401
    """One end as ``(identifier, object)``: a drawn structure's own, else the drawn instance's."""
    if identifier:
        return str(identifier), str(obj)
    return ENTITY_IDENTIFIER, str(ref)


def render_pairs(controller: GraphController, query: core_models.GraphQuery, *, info: Any = None) -> list[tuple[tuple[str, str], tuple[str, str]]]:  # noqa: ANN401
    """Every distinct pair the query answers now, in a stable order: ``((src identifier, object), (tgt identifier, object))``."""
    rows = controller.render_table_plan(query.graph, pairs_plan(query).to_table_plan(), order=RenderGraphTableOrder(key="source_ref"), info=info)
    pairs = {(_end(row.get("source_identifier"), row.get("source_object"), row.get("source_ref")), _end(row.get("target_identifier"), row.get("target_object"), row.get("target_ref"))) for row in rows}
    return sorted(pairs)


def _shared(identifiers: list[str]) -> str | None:
    distinct = set(identifiers)
    return distinct.pop() if len(distinct) == 1 else None


def run_pairs_query(
    controller: GraphController,
    query: core_models.GraphQuery,
    *,
    name: str,
    description: str | None = None,
    auto: bool = False,
    creator: Any = None,  # noqa: ANN401
    info: Any = None,  # noqa: ANN401
) -> models.PairsQueryRun:
    """Run ``query`` against its view's drawing and store the answer with where the drawing stood.

    Raises:
        RunRefused: the query is not a pairs query, or its view is not drawn consistently
            (a rebuilding view's drawing is partial, so its answer would say nothing).
    """
    if str(query.kind) != core_models.GraphPairsQuery.KIND:
        raise RunRefused(f"Saved query #{query.pk} is a {query.kind} query; only a pairs query runs into pairs")
    graph = query.graph
    position = watermark.position(graph)
    if position.cursor <= 0:
        raise RunRefused(f"The view {graph.name!r} is not drawn consistently ({position.status}): its drawing is partial. Run the query once it has converged")
    as_of = min(position.cursor, horizon(graph.organization))
    pairs = render_pairs(controller, query, info=info)

    with transaction.atomic():
        run = models.PairsQueryRun.objects.create(
            organization=graph.organization,
            query=query,
            graph=graph,
            name=name,
            description=description,
            auto=auto,
            as_of_seq=as_of,
            plan=query.plan,
            schema_hash=getattr(position, "schema_hash", None),
            n_pairs=len(pairs),
            source_identifier=_shared([source[0] for source, _ in pairs]),
            target_identifier=_shared([target[0] for _, target in pairs]),
            creator=creator,
        )
        models.PairsQueryRunEntry.objects.bulk_create([models.PairsQueryRunEntry(run=run, position=index, source_identifier=source[0], source_object=source[1], target_identifier=target[0], target_object=target[1]) for index, (source, target) in enumerate(pairs)])
    return run


def _end_identifier(query: core_models.GraphQuery, side: str) -> str | None:
    """The structure identifier a pairs query constrains one end to: the one its STRUCTURE category mounts."""
    plan = query_ir.PairsQueryPlan.from_stored(query.plan)
    if plan is None:
        return None
    label = plan.end_category(plan.source if side == "source" else plan.target)
    if label is None:
        return None
    category = core_models.StructureCategory.objects.filter(graph_id=query.graph_id, age_name=label).select_related("structure_kind").first()
    return category.identifier if category is not None else None


def pairs_query_descriptors(query: core_models.GraphQuery) -> dict[str, Any]:
    """What a pairs query says about itself, for a port's `requires`.

    Its view, and the identifier each end is constrained to when the plan pins that node to
    a mounted STRUCTURE category. Every key is always present, null where it does not
    apply: a run's check on an expanded argument skips a key the object lacks, but fails a
    null one, as the server's SQL does.
    """
    return {
        "@kraph/graph": str(query.graph_id),
        "@kraph/source_identifier": _end_identifier(query, "source"),
        "@kraph/target_identifier": _end_identifier(query, "target"),
    }


def pairs_run_descriptors(run: models.PairsQueryRun) -> dict[str, Any]:
    """What a run says about itself: its query and view, its size and position, and the identifiers every pair shares."""
    return {
        "@kraph/graph": str(run.graph_id),
        "@kraph/query": str(run.query_id),
        "@kraph/n_pairs": run.n_pairs,
        "@kraph/as_of_seq": run.as_of_seq,
        "@kraph/source_identifier": run.source_identifier,
        "@kraph/target_identifier": run.target_identifier,
    }


def model_descriptors(model: models.TrainedModel) -> dict[str, Any]:
    """What a trained model says about itself: its framework, and the run it was trained on.

    The run's query, position and identifiers, so a prediction action can require "a CARE
    model trained on image pairs". Every key is always present, null where it does not apply.
    """
    run = model.trained_on
    return {
        "@kraph/framework": model.framework,
        "@kraph/trained_on": str(run.pk) if run is not None else None,
        "@kraph/query": str(run.query_id) if run is not None else None,
        "@kraph/as_of_seq": run.as_of_seq if run is not None else None,
        "@kraph/source_identifier": run.source_identifier if run is not None else None,
        "@kraph/target_identifier": run.target_identifier if run is not None else None,
    }
