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


#: Every derivation that reads from evidence. All four are handled — leaving
#: PRIORITY_LATEST and LATEST_ASSERTION_TOOL out would make properties using them
#: silently never populate, which is the failure mode this transition exists to
#: remove. They previously aliased plain LATEST, quietly ignoring the priority
#: the schema asked for.
EVIDENCE_DERIVATIONS = (
    DerivationType.ROLLUP,
    DerivationType.LATEST,
    DerivationType.PRIORITY_LATEST,
    DerivationType.LATEST_ASSERTION_TOOL,
)


def _derived_properties(category: core_models.Category) -> list[Any]:
    """The property definitions on a category that come from evidence."""
    return [prop for prop in (category.defined_properties or []) if prop.derivation in EVIDENCE_DERIVATIONS and prop.key != "id"]


def _structure_ids_informing(graph: core_models.Graph, entity_ref: str) -> list[Any]:
    """The structure primary keys whose measurements reach this entity."""
    import uuid as uuid_module

    refs = selector_module.informs_links_for(graph).filter(target_ref=entity_ref).values_list("source_ref", flat=True)

    parsed = []
    for ref in refs:
        try:
            parsed.append(uuid_module.UUID(str(ref)))
        except ValueError:
            # Not a structure — a relation link, say. Not evidence for a rollup.
            continue
    return parsed


def _priority_scoped_value(
    graph: core_models.Graph,
    entity_ref: str,
    source_category: Any,
    key: str,
    prop: Any,
) -> Any:
    """The latest value from the most-trusted source that has one.

    PRIORITY_LATEST and LATEST_ASSERTION_TOOL cannot read the state vector: its
    grain is `(entity, source_category, key)` with no subject discriminator, and
    adding one would multiply every row by the number of sources that ever
    measured. These query the metrics directly instead — more expensive, but
    correct, and properties declared this way have few contributors by
    construction.

    An unlisted source can never outrank a listed one: the fallback to "anyone"
    applies only when the rule names no priorities at all. Falling through would
    make the priority advisory, which is not what "priority" means.
    """
    from evidence import models as evidence_models

    rule = prop.rule
    by_tool = prop.derivation == DerivationType.LATEST_ASSERTION_TOOL
    ordering = list(getattr(rule, "tool_priority", []) if by_tool else getattr(rule, "subject_priority", []))
    field = "assertion__app_id" if by_tool else "assertion__subject"

    structure_ids = _structure_ids_informing(graph, entity_ref)
    if not structure_ids:
        return None

    base = evidence_models.Metric.objects.for_organization(graph.organization).filter(
        structure_id__in=structure_ids,
        structure__category=source_category,
        key=key,
        status=evidence_models.LifecycleStatus.ACTIVE,
    )

    for source in ordering:
        latest = base.filter(**{field: source}).order_by("-measured_at").first()
        if latest is not None:
            return latest.value

    if ordering:
        return None

    latest = base.order_by("-measured_at").first()
    return latest.value if latest else None


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

        if prop.derivation in (DerivationType.PRIORITY_LATEST, DerivationType.LATEST_ASSERTION_TOOL):
            value = _priority_scoped_value(graph, entity_ref, source_category, key, prop)
        else:
            state = state_module.state_for(organization, entity_ref, source_category, key)

            aggregation = rule.aggregation if rule and rule.aggregation else None
            if prop.derivation == DerivationType.LATEST and aggregation is None:
                from graph_engine.input_models import AggregationFunction

                aggregation = AggregationFunction.LATEST

            value = aggregate.apply(aggregation, state) if aggregation else None

        if value is not None:
            values[prop.key] = value

    return values


def _observation_window(graph: core_models.Graph, entity_ref: str) -> dict[str, Any]:
    """When the evidence behind this node was observed.

    `valid_from` and `valid_to` are read by six GraphQL fields that have always
    returned null, because nothing ever wrote them. They are the observation
    window of the contributing measurements — `measured_at`, not `asserted_at`:
    a node is valid over the period the world was actually looked at, regardless
    of when somebody got round to saying so.
    """
    from django.db.models import Max, Min

    from evidence import models as evidence_models

    structure_ids = _structure_ids_informing(graph, entity_ref)
    if not structure_ids:
        return {"valid_from": None, "valid_to": None}

    window = (
        evidence_models.Metric.objects.for_organization(graph.organization)
        .filter(
            structure_id__in=structure_ids,
            status=evidence_models.LifecycleStatus.ACTIVE,
        )
        .aggregate(earliest=Min("measured_at"), latest=Max("measured_at"))
    )

    return {
        "valid_from": window["earliest"].isoformat() if window["earliest"] else None,
        "valid_to": window["latest"].isoformat() if window["latest"] else None,
    }


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

    # The graph's active schema is the version that derived these values.
    # `NodeCategory.schema_hash` hashes one category's properties, which is a
    # different question and cannot identify the schema a value came from.
    active_schema = core_models.GraphSchema.active_for(graph)
    schema_version = active_schema.hash if active_schema else None

    for entity_ref in entity_refs:
        node = evidence_models.Node.objects.for_organization(graph.organization).filter(ref=entity_ref).first()
        if node is None:
            continue

        # `Category` is polymorphic, and a plain foreign key hands back the base
        # instance — which has no `defined_properties`. Downcast, or every
        # projection silently derives nothing.
        category = node.category.get_real_instance()
        values = derive_properties(graph, entity_ref, category)
        values.update(_observation_window(graph, entity_ref))
        values["__lifecycle_state"] = _lifecycle_state(graph, entity_ref)
        values["__schema_version"] = schema_version
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
