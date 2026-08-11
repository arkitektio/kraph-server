"""Building the Apache AGE projection from the evidence base.

The projection is a cache. Everything in it is derivable from
:mod:`evidence.models` plus a schema version, which means it can be dropped and
rebuilt at will — and `test_reproject_idempotent` proves that rather than
asserting it. If the graph cannot be rebuilt from the evidence, the evidence is
not the source of truth whatever the documentation says.

Three operations, and nothing else:

- :func:`dirty` — which entities a change invalidates
- :func:`project` — recompute those entities' properties into AGE
- :func:`rebuild` — drop the graph and replay it from evidence

Writes stay projection-agnostic. Ingesting a metric records evidence and emits a
dirty set; it never walks the list of graphs that might care. That is what keeps
bulk ingest linear rather than O(metrics x projections).
"""

from __future__ import annotations

import time
from typing import Any, Iterable

from core import models as core_models
from evidence import models as evidence_models
from evidence import selector as selector_module
from evidence import state as state_module
from graph_engine import aggregate
from graph_engine.input_models import DerivationType


def dirty(graph: core_models.Graph, structure_ids: Iterable[Any]) -> list[str]:
    """The entity refs invalidated by a change to the given structures.

    An indexed lookup, not a traversal: one query against
    `(organization, kind, source_ref)` regardless of how many metrics landed.
    """
    return selector_module.entity_refs_informed_by(graph, list(structure_ids))


def _derived_properties(category: core_models.Category) -> list[Any]:
    """The property definitions on a category that come from evidence."""
    return [prop for prop in (category.defined_properties or []) if prop.derivation in (DerivationType.ROLLUP, DerivationType.LATEST) and prop.key != "id"]


def _structure_category_for_rule(graph: core_models.Graph, rule: Any) -> core_models.StructureCategory | None:
    """Resolve a rule's `source_node` to a structure category of this graph."""
    if not rule or not rule.source_node:
        return None
    return core_models.StructureCategory.objects.filter(graph=graph, identifier=rule.source_node).first() or core_models.StructureCategory.objects.filter(graph=graph, key=rule.source_node).first()


def derive_properties(graph: core_models.Graph, entity_ref: str, category: core_models.Category) -> dict[str, Any]:
    """Compute one entity's derived properties from its state vectors.

    Reads only statistics. No metric is scanned, no Cypher is run, and switching
    a property's aggregation changes the answer without touching storage.
    """
    organization = graph.organization
    values: dict[str, Any] = {}

    for prop in _derived_properties(category):
        rule = prop.rule
        source_category = _structure_category_for_rule(graph, rule)
        if source_category is None:
            # The schema names a structure kind this graph has never seen. Not an
            # error — structures are resolved dynamically at write time, so the
            # category simply does not exist yet and there is no evidence to
            # aggregate.
            continue

        key = rule.key if rule and rule.key else prop.key
        state = state_module.state_for(organization, entity_ref, source_category, key)

        aggregation = rule.aggregation if rule and rule.aggregation else None
        if prop.derivation == DerivationType.LATEST and aggregation is None:
            from graph_engine.input_models import AggregationFunction

            aggregation = AggregationFunction.LATEST

        value = aggregate.apply(aggregation, state) if aggregation else None
        if value is not None:
            values[prop.key] = value

    return values


def _lifecycle_state(graph: core_models.Graph, entity_ref: str) -> str:
    """The current lifecycle state of a projected node, from the evidence log."""
    latest = evidence_models.LifecycleEvent.objects.for_organization(graph.organization).filter(target_type__in=("entity", "event"), target_id=entity_ref).order_by("-at").first()
    return latest.status if latest else evidence_models.LifecycleStatus.ACTIVE


def project(
    controller: Any,
    graph: core_models.Graph,
    entity_refs: Iterable[str],
) -> int:
    """Write derived properties onto the named entities. Returns how many were written.

    Batched deliberately: one call handles a whole dirty set, so a bulk ingest of
    a thousand metrics against one structure triggers a single projection pass
    rather than a thousand. The old design re-derived per fact, which is the
    O(N x P) regression `test_bulk_ingest` guards against.
    """
    projected = 0

    for entity_ref in entity_refs:
        node = evidence_models.Node.objects.for_organization(graph.organization).filter(ref=entity_ref).first()
        if node is None:
            continue

        # `Category` is polymorphic, and a plain foreign key hands back the base
        # instance — which has no `defined_properties`. Downcast, or every
        # projection silently derives nothing.
        category = node.category.get_real_instance()
        values = derive_properties(graph, entity_ref, category)
        values["__lifecycle_state"] = _lifecycle_state(graph, entity_ref)
        values["__schema_version"] = getattr(category, "schema_hash", None)
        values["__last_derived"] = int(time.time() * 1000)

        _write_properties(controller, graph, entity_ref, category, values)
        projected += 1

    return projected


def _write_properties(
    controller: Any,
    graph: core_models.Graph,
    entity_ref: str,
    category: core_models.Category,
    values: dict[str, Any],
) -> None:
    """Set properties on the AGE node identified by a durable entity ref.

    Matched by the node's stable `id` property rather than by vertex id, because
    vertex ids do not survive a rebuild — which is the whole reason refs are
    keyed on the uuid.
    """
    _, _, node_uuid = entity_ref.partition(":")

    set_clause = ", ".join(f"e.{controller._validate_property_key(key)} = $u_{key}" for key in values)
    params: dict[str, Any] = {f"u_{key}": value for key, value in values.items()}
    params["node_uuid"] = node_uuid

    controller.engine.execute(
        graph,
        f"""
        MATCH (e:{category.age_name}) WHERE e.id = $node_uuid
        SET {set_clause}
        """,
        params,
    )


def rebuild(controller: Any, graph: core_models.Graph) -> dict[str, int]:
    """Drop the projection and replay it from evidence.

    The honesty test. Everything AGE holds for this graph is destroyed and
    reconstructed from Postgres alone; if anything is missing afterwards, it was
    never really derived.

    State vectors are rebuilt too. They are also a cache — statistics folded from
    metrics — so replaying without them would only prove the projection can be
    rebuilt from *another* cache.
    """
    organization = graph.organization

    nodes = list(evidence_models.Node.objects.for_organization(organization).filter(ref__startswith=f"{graph.age_name}:", status=evidence_models.LifecycleStatus.ACTIVE))

    controller.engine.drop_graph(graph.age_name, cascade=True)
    controller.engine.create_graph(age_name=graph.age_name)

    for node in nodes:
        _, _, node_uuid = node.ref.partition(":")
        category = node.category.get_real_instance()
        controller.engine.execute(
            graph,
            f"""
            CREATE (e:{category.age_name} {{id: $eid, category_id: $cid}})
            RETURN id(e) as db_id
            """,
            {"eid": node_uuid, "cid": category.pk},
        )

    refolded = refold_state(graph)
    projected = project(controller, graph, [node.ref for node in nodes])

    return {"nodes": len(nodes), "states": refolded, "projected": projected}


def refold_state(graph: core_models.Graph) -> int:
    """Rebuild every state vector this graph projects, from the metrics themselves.

    Deletes the existing rows first rather than merging over them: merging into a
    stale row would double-count, and the point of a rebuild is to depend on
    nothing that came before it.
    """
    organization = graph.organization

    entity_refs = set(selector_module.informs_links_for(graph).values_list("target_ref", flat=True))
    if entity_refs:
        evidence_models.State.objects.for_organization(organization).filter(entity_ref__in=entity_refs).delete()

    folded = 0
    for metric in selector_module.metrics_for(graph):
        refs = selector_module.entity_refs_informed_by(graph, [metric.structure_id])
        if refs:
            state_module.merge(metric, refs)
            folded += 1

    return folded
