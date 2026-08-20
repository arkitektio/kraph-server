"""Building the Apache AGE projection from the evidence base.

The projection is a cache. Everything in it is derivable from
:mod:`evidence.models` plus a schema version, which means it can be dropped and
rebuilt at will — and `test_reproject_idempotent` proves that rather than
asserting it. If the graph cannot be rebuilt from the evidence, the evidence is
not the source of truth whatever the documentation says.

Four operations, and nothing else:

- :func:`dirty` — which entities a change invalidates
- :func:`project` — recompute those entities' properties into AGE
- :func:`unproject` — remove nodes the evidence no longer says are there
- :func:`rebuild` — drop the graph and replay it from evidence

Writes stay projection-agnostic. Ingesting a metric records evidence and emits a
dirty set; it never walks the list of graphs that might care. That is what keeps
bulk ingest linear rather than O(metrics x projections).

**The projection holds only what exists.** A node the claims do not support has no
vertex — not a vertex with a flag on it. `resolve_categories` folds the existence
claims under the reading graph's selector and refuses the node, and `unproject`
removes one that was already drawn. That is the rule `_reproject_proposition` has
always applied to edges, which delete when the last claim behind them goes rather
than lingering behind a lifecycle property; nodes were the last holdout. It is
also why nothing here writes `__lifecycle_state` any more: on a vertex it could
only ever agree with that vertex's own presence.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from django.db.models import Q

from core import models as core_models
from core.enums import ValueKind
from evidence import claims as claims_module
from evidence import models as evidence_models
from evidence import selector as selector_module
from evidence import state as state_module
from evidence import writer as writer_module
from graph_engine import aggregate
from graph_engine import watermark
from graph_engine.input_models import DerivationType

logger = logging.getLogger(__name__)

#: INT and FLOAT are distinct *terms* — a cell count and a length are different
#: declarations — but they are the same quantity to every aggregation: both live
#: in `value_num` and `state._numeric` accepts both. A rule naming FLOAT that
#: read only the FLOAT term would silently drop every INT measurement of the
#: same key, so reads widen across the family and fold the rows together.
#:
#: Deliberately the *only* widening. Routing this through
#: `Metric.VALUE_COLUMN_FOR_KIND` instead would also merge STRING with CATEGORY
#: and collapse all five vector arities — a separate semantic decision smuggled
#: in as an implementation detail.
NUMERIC_FAMILY: frozenset[str] = frozenset({ValueKind.INT.value, ValueKind.FLOAT.value})


def value_kind_family(value_kind: str) -> frozenset[str]:
    """The value kinds that fold together with this one."""
    return NUMERIC_FAMILY if value_kind in NUMERIC_FAMILY else frozenset({value_kind})


def dirty(graph: core_models.Graph, structure_ids: Iterable[Any]) -> list[str]:
    """The entity refs invalidated by a change to the given structures.

    An indexed lookup, not a traversal: one query against
    `(organization, kind, source_ref)` regardless of how many metrics landed.
    """
    return selector_module.instance_refs_informed_by(graph, list(structure_ids))


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


def is_derived(prop: Any) -> bool:
    """Whether a property is computed from evidence rather than written directly.

    The single definition. `derivation` defaults to LATEST, so the enum alone
    does not distinguish a computed property from a plain one — what makes a
    property derived is a rule naming a source, which is also the condition
    `derive_properties` requires before computing anything. The controller reads
    this too, because `_derive_unindexed` diffs the two and they have to agree.
    """
    if prop.key == "id" or prop.derivation not in EVIDENCE_DERIVATIONS:
        return False
    rule = getattr(prop, "rule", None)
    return rule is not None and bool(getattr(rule, "source_node", None))


def refs_informed_by(organization: Any, structure_ids: Iterable[Any]) -> list[str]:
    """Everything in the organization these structures are evidence for.

    Ingest names no graph, so a measurement has to reach every projection that
    cares about it. That is why this asks the organization rather than a graph:
    `dirty()` filters links to one graph, so recording a metric only ever
    refreshed the projection you happened to name, and a second view over the
    same shared evidence stayed stale until somebody reprojected it.

    Returns **every** informed ref, nodes and edges alike, ungrouped. It used to
    group by the `{age_name}:` prefix and drop anything without one — which
    silently excluded edge refs, since `_attach_supporting_evidence` keys those
    on a bare `Link` pk. So a metric recorded after a relation was created never
    reached that relation's statistics, while a rebuild would have folded it.
    Grouping is the projection step's problem, and `project_refs` does it there.
    """
    return [
        str(ref)
        for ref in claims_module.standing(
            evidence_models.Link.objects.for_organization(organization).filter(
                kind=evidence_models.Link.Kind.INFORMS,
                source_ref__in=[str(structure_id) for structure_id in structure_ids],
            ),
            "link",
        )
        .values_list("target_ref", flat=True)
        .distinct()
    ]


def graphs_for_refs(organization: Any, refs: Iterable[str]) -> dict[Any, list[str]]:
    """Group node refs by the graph that projects them.

    Replaces splitting the ref on `:`. A ref is a bare uuid now, so which view
    it belongs to is a question for the evidence base — and one a ref can answer
    with more than one graph, which the prefix could never express.

    Refs with no `Instance` row simply do not appear: they are edge refs, or nodes
    of a graph that has since been deleted. Both are expected — evidence
    outlives the projections built from it.
    """
    from core import models as core_models

    by_graph_id: dict[Any, list[str]] = {}
    for node_ref, graph_id in selector_module.graph_ids_for_instance_ids(organization, refs):
        by_graph_id.setdefault(graph_id, []).append(node_ref)

    if not by_graph_id:
        return {}

    # Ordered so the *sequence* of drawings a write reports is stable — see
    # `GraphController.drawings_for_instance`. This used to matter far more: a write
    # returned the first graph this yielded and discarded the rest, so the order
    # decided which single category a client saw. It reports all of them now, and
    # the ordering is only so that two identical writes list them alike.
    graphs = core_models.Graph.objects.filter(pk__in=list(by_graph_id)).order_by("pk")
    return {graph: by_graph_id[graph.pk] for graph in graphs}


def _derived_properties(category: core_models.Category) -> list[Any]:
    """The property definitions on a category that come from evidence."""
    return [prop for prop in (category.defined_properties or []) if is_derived(prop)]


def _structure_ids_informing(graph: core_models.Graph, claim_ref: str) -> list[Any]:
    """The structure primary keys whose measurements reach this entity.

    Parsed to real UUIDs rather than left as strings: `source_ref` is an opaque
    CharField, and Postgres will not compare one against a `uuid` column. The
    source of an INFORMS link is always a structure, so every ref here parses —
    a failure means a link was written with the wrong kind, which is worth
    hearing about rather than skipping.
    """
    import uuid as uuid_module

    refs = selector_module.informs_links_for(graph).filter(target_ref=claim_ref).values_list("source_ref", flat=True)
    return [uuid_module.UUID(str(ref)) for ref in refs]


def _priority_scoped_value(
    graph: core_models.Graph,
    claim_ref: str,
    source_kind: Any,
    key: str,
    value_kinds: Iterable[str],
    prop: Any,
) -> Any:
    """The latest value from the most-trusted source that has one.

    PRIORITY_LATEST and LATEST_ASSERTION_TOOL cannot read the state vector: its
    grain is `(entity, source_kind, key, value_kind)` with no subject
    discriminator, and
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

    structure_ids = _structure_ids_informing(graph, claim_ref)
    if not structure_ids:
        return None

    # `value_kind__in` rather than the state grain: this path never reads State,
    # so it has to apply the same narrowing itself or it would rank a STRING
    # measurement against a FLOAT one under the same key.
    base = claims_module.standing(
        evidence_models.Metric.objects.for_organization(graph.organization).filter(
            structure_id__in=structure_ids,
            structure__kind=source_kind,
            key=key,
            value_kind__in=list(value_kinds),
        ),
        "metric",
    )

    for source in ordering:
        latest = base.filter(**{field: source}).order_by("-measured_at").first()
        if latest is not None:
            return latest.value

    if ordering:
        return None

    latest = base.order_by("-measured_at").first()
    return latest.value if latest else None


def _structure_kind_for_rule(graph: core_models.Graph, rule: Any) -> Any:
    """Resolve a rule's `source_node` to one of the organization's structure kinds.

    Identifier only. The old lookup also fell back to `key`, which a structure
    kind does not have — an organization's vocabulary of external data types is
    keyed by the identifier the producing service owns.
    """
    if not rule or not rule.source_node:
        return None
    return evidence_models.StructureKind.objects.for_organization(graph.organization).filter(identifier=rule.source_node).first()


def _value_kinds_for_rule(graph: core_models.Graph, source_kind: Any, key: str, rule: Any) -> frozenset[str] | None:
    """Which value kinds this rule reads, or None when that is ambiguous.

    Symmetric with :func:`evidence.writer.ensure_metric_kind` on the write side:
    a declaration is exact, and silence is resolved from the vocabulary.

    `prop.value_kind` deliberately plays no part here. It is the aggregation's
    *result* type — `AGGREGATION_RESULT_TYPES` maps COUNT to INT and
    EUCLIDEAN_RANGE to FLOAT regardless of what the sources are — so using it to
    pick the source row would pick the wrong one precisely where it differs.
    """
    declared = writer_module.canonical_value_kind(getattr(rule, "source_value_kind", None))
    if declared is not None:
        return value_kind_family(declared)

    terms = sorted(str(term) for term in evidence_models.MetricKind.objects.for_organization(graph.organization).filter(structure_kind=source_kind, key=key).values_list("value_kind", flat=True))

    families = {value_kind_family(term) for term in terms}

    if not families:
        # Nothing measured under this key yet. Kinds are minted lazily, so this
        # is the ordinary state of a freshly declared property, not an error.
        return frozenset()

    if len(families) > 1:
        logger.warning(
            "%s.%s: '%s'.%s exists as %s, and the rule declares no source_value_kind, so there is no way to say which is meant. The property will not derive. Add `source_value_kind` to the rule.",
            getattr(rule, "source_node", "?"),
            key,
            getattr(source_kind, "identifier", "?"),
            key,
            # The terms that actually exist, not the families they widen to —
            # naming INT because FLOAT implies it would send the reader looking
            # for a term nobody declared.
            ", ".join(terms),
        )
        return None

    return next(iter(families))


#: Prefix for a per-property statistic on the vertex. `__stat__length__n` is the
#: evidence count behind the `length` property.
STAT_PREFIX = "__stat__"


#: The statistics `_property_statistics` writes for each derived property. Kept as
#: a tuple rather than left implicit in that function because `derived_property_keys`
#: has to name them without a node to compute them from — a property that derived
#: nothing on the last pass still owns its statistic keys, and they still have to be
#: swept when the property goes.
STATISTICS = ("n", "spread", "from", "to")


def statistic_key(key: str, statistic: str) -> str:
    """The vertex property holding one statistic about one derived property."""
    return f"{STAT_PREFIX}{key}__{statistic}"


def derived_property_keys(category: core_models.Category) -> set[str]:
    """Every vertex key this category's derivation rules can write.

    The value and its statistics together, because a rematerialization has to
    reason about what a *definition* owns rather than about what one node
    happened to produce — see :func:`rematerialize_category`.
    """
    keys: set[str] = set()
    for prop in _derived_properties(category):
        keys.add(prop.key)
        keys.update(statistic_key(prop.key, statistic) for statistic in STATISTICS)
    return keys


def _property_statistics(
    graph: core_models.Graph,
    claim_ref: str,
    category: core_models.Category,
) -> dict[str, Any]:
    """How much evidence stands behind each derived value, and over what window.

    `RichProperty` exposes `n_evidence`, `spread`, `measured_from` and
    `measured_to`. Those used to be read off the `State` row at query time — one
    lookup per property per node — which is the same read-time computation the
    value itself no longer does. They are statistics *about* a materialized
    value, so they are materialized beside it.

    Deliberately **not** here: `contributing_assertions` and
    `supporting_evidence`. Those return rows rather than a scalar, they are
    unbounded in length, and they answer a drill-down question about one node a
    client has already selected. A vertex property is the wrong shape for them,
    and no query filters or sorts on them. They stay a Postgres lookup — the rule
    is that no value a query *returns as a property, filters on, or sorts by* is
    computed on read.
    """
    statistics: dict[str, Any] = {}

    for prop in _derived_properties(category):
        rule = prop.rule
        source_kind = _structure_kind_for_rule(graph, rule)
        if source_kind is None:
            continue

        key = rule.key if rule and rule.key else prop.key
        value_kinds = _value_kinds_for_rule(graph, source_kind, key, rule)
        if value_kinds is None:
            continue

        state = _scoped_state(graph, claim_ref, source_kind, key, value_kinds) if graph.selector else state_module.state_for(graph.organization, claim_ref, source_kind, key, value_kinds)
        if state is None:
            continue

        statistics[statistic_key(prop.key, "n")] = state.n
        if state.min is not None and state.max is not None:
            statistics[statistic_key(prop.key, "spread")] = state.max - state.min
        if state.first_ts is not None:
            statistics[statistic_key(prop.key, "from")] = state.first_ts.isoformat()
        if state.last_ts is not None:
            statistics[statistic_key(prop.key, "to")] = state.last_ts.isoformat()

    return statistics


def derive_properties(
    graph: core_models.Graph,
    claim_ref: str,
    category: core_models.Category,
) -> dict[str, Any]:
    """Compute one entity's derived properties from its state vectors.

    **Runs at materialization, never on read.** Applying a graph's rules to the
    log is what creates its nodes and their properties; a query afterwards is a
    traversal over the result. Everything this returns is written onto the
    vertex.

    There used to be an ``indexed_only`` switch, and a companion
    `split_properties`, so that only properties marked ``index=True`` were
    materialized and the rest were folded per node on every read. `index`
    defaults to `False`, so that meant almost everything was computed on read:
    for N entities and P properties, N × (1 + 3P) queries, or more where a
    selector forced a metric scan. The cost was unbounded in the size of the
    result set, and no amount of batching makes a read into a traversal.

    The trade taken in exchange: adding a property is no longer free. It needs a
    rematerialization — see `core.managers` and `emit_schema_version`.
    """
    organization = graph.organization
    values: dict[str, Any] = {}

    for prop in _derived_properties(category):
        rule = prop.rule
        source_kind = _structure_kind_for_rule(graph, rule)
        if source_kind is None:
            # The rule names a structure kind this organization has never seen.
            # Usually benign — kinds are created lazily at write time, so it
            # simply has no evidence yet. But a rule written against a *key*
            # rather than an identifier now lands here permanently and would
            # otherwise be skipped in silence, so say something.
            logger.warning(
                "%s.%s: no structure kind matches source %r in organization %s; the property will not derive. Rules resolve by structure identifier (e.g. '@mikro/roi'), not by category key.",
                getattr(category, "key", "?"),
                prop.key,
                getattr(rule, "source_node", None),
                graph.organization_id,
            )
            continue

        key = rule.key if rule and rule.key else prop.key

        value_kinds = _value_kinds_for_rule(graph, source_kind, key, rule)
        if value_kinds is None:
            # Ambiguous: the key has terms in more than one value-kind family and
            # the rule does not say which. `_value_kinds_for_rule` has already
            # said so; deriving from an arbitrary term would be worse than not
            # deriving.
            continue

        if prop.derivation in (DerivationType.PRIORITY_LATEST, DerivationType.LATEST_ASSERTION_TOOL):
            value = _priority_scoped_value(graph, claim_ref, source_kind, key, value_kinds, prop)
        else:
            state = _scoped_state(graph, claim_ref, source_kind, key, value_kinds) if graph.selector else state_module.state_for(organization, claim_ref, source_kind, key, value_kinds)

            aggregation = rule.aggregation if rule and rule.aggregation else None
            if prop.derivation == DerivationType.LATEST and aggregation is None:
                from graph_engine.input_models import AggregationFunction

                aggregation = AggregationFunction.LATEST

            value = aggregate.apply(aggregation, state) if aggregation else None

        if value is not None:
            values[prop.key] = value

    return values


def _scoped_state(
    graph: core_models.Graph,
    claim_ref: str,
    source_kind: Any,
    key: str,
    value_kinds: Iterable[str],
) -> Any:
    """Fold this entity's metrics under the graph's selector, without storing it.

    The read-time half of the decision that `State` is organization grain. The
    stored vector counts every live metric, which is the right answer for a graph
    that counts everything — the normal case, and the only one in production,
    since nothing writes `Graph.selector`. A graph that counts less cannot share
    that row, and storing a second one per view is what would put a graph
    foreign key into `evidence/` — the one thing that app may not grow.

    So it pays for the narrowing on read instead: the metrics directly, folded
    into an unsaved vector. The same trade `_priority_scoped_value` already
    makes, and for the same reason.
    """
    structure_ids = _structure_ids_informing(graph, claim_ref)
    if not structure_ids:
        return None

    metrics = claims_module.standing(
        evidence_models.Metric.objects.for_organization(graph.organization).filter(
            selector_module.metric_filter(graph.selector),
            structure_id__in=structure_ids,
            structure__kind=source_kind,
            key=key,
            value_kind__in=list(value_kinds),
        ),
        "metric",
    )

    # `value_kind` is set only to keep the unsaved row well-formed, and it is
    # arbitrary when the family widens (INT and FLOAT fold together, and
    # `value_kinds` is a frozenset). That is safe because nothing reads it here:
    # `aggregate.apply` takes the `StateVector` protocol, which does not include
    # the field. This row is never saved, so no grain depends on it either. If an
    # aggregation ever needs the kind, give it the whole set rather than one.
    vector = evidence_models.State(
        organization=graph.organization,
        claim_ref=claim_ref,
        source_kind=source_kind,
        key=key,
        value_kind=next(iter(sorted(value_kinds)), ""),
    )
    return state_module.fold(metrics, vector)


def _observation_window(graph: core_models.Graph, claim_ref: str) -> dict[str, Any]:
    """When the evidence behind this node was observed.

    `valid_from` and `valid_to` are read by six GraphQL fields that have always
    returned null, because nothing ever wrote them. They are the observation
    window of the contributing measurements — `measured_at`, not `asserted_at`:
    a node is valid over the period the world was actually looked at, regardless
    of when somebody got round to saying so.
    """
    from django.db.models import Max, Min

    from evidence import models as evidence_models

    structure_ids = _structure_ids_informing(graph, claim_ref)
    if not structure_ids:
        return {"valid_from": None, "valid_to": None}

    window = claims_module.standing(
        evidence_models.Metric.objects.for_organization(graph.organization).filter(structure_id__in=structure_ids),
        "metric",
    ).aggregate(earliest=Min("measured_at"), latest=Max("measured_at"))

    return {
        "valid_from": window["earliest"].isoformat() if window["earliest"] else None,
        "valid_to": window["latest"].isoformat() if window["latest"] else None,
    }


def project(
    controller: Any,
    graph: core_models.Graph,
    instance_refs: Iterable[str],
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

    refs = [str(ref) for ref in instance_refs]
    nodes = list(evidence_models.Instance.objects.for_organization(graph.organization).filter(id__in=refs))
    # Which category a node projects as is this graph's question to answer, and
    # `_write_properties` needs the answer to find the vertex at all — it matches
    # on the label. Resolved once for the batch rather than per node.
    resolved, _ = resolve_categories(graph, nodes)

    for claim_ref in refs:
        category = resolved.get(claim_ref)
        if category is None:
            # Either no such node, or no category in this graph admits it. Either
            # way there is no vertex to write onto.
            continue

        # **Every** derived property, not just the filterable ones. A read is a
        # graph query: whatever a client can ask for is on the vertex before the
        # query runs. The old split wrote only `index=True` properties and left
        # the rest to `api/types._derive_unindexed`, which folded state per node
        # on every read — and since `index` defaults to False, that was almost
        # all of them.
        values = derive_properties(graph, claim_ref, category)
        values.update(_property_statistics(graph, claim_ref, category))
        values.update(_observation_window(graph, claim_ref))
        values["__schema_version"] = schema_version
        # No `__last_derived` any more. It was a wall-clock millisecond on every
        # vertex — the one projected value `reproject` could not reproduce, so the
        # rebuild tests excluded it by hand — and it answered a per-graph question
        # per node. "When was this view last derived" is `Projection.derived_at`,
        # stamped once per call below.

        if not _write_properties(controller, graph, claim_ref, category, values):
            # The node has a `Instance` row and a category this graph admits, but no
            # vertex — the projection is behind the log. `reproject` is the fix;
            # counting it as projected would hide that it is needed.
            logger.warning(
                "%s: no vertex labelled %s to write onto; the projection is behind the evidence. Run `manage.py reproject --graph %s`.",
                claim_ref,
                category.age_name,
                graph.pk,
            )
            continue

        projected += 1

    if projected:
        watermark.mark_derived(graph)

    return projected


#: A relation's identity in the projection is the *proposition* it states —
#: which two entities, under which category — never the assertion that stated it.
#: Two labs claiming the same synapse are two `Link` rows and one edge, so a
#: traversal sees the connection once while the evidence base keeps both claims.
#: Collapsing them at write time instead would make agreement uncountable, and
#: keeping them apart in AGE would make every path query return duplicates.
def proposition_key(link: evidence_models.Link) -> tuple[str, str, Any]:
    """What makes two relation assertions claims about the same edge.

    The two endpoints and the *word* — not a graph's category for it. Two views
    that both declare "IS_CONNECTED_TO" are looking at one proposition, and each
    draws it under its own label."""
    return (str(link.source_ref), str(link.target_ref), link.term_id)


def categories_by_term(graph: core_models.Graph) -> dict[Any, Any]:
    """This graph's categories, indexed by the organization term each declares.

    The join between a claim and a view. A claim names a word; this says what —
    if anything — *this* graph draws that word as. A term with no entry here is
    one this view does not speak, which is a perfectly ordinary state and not an
    error.
    """
    # `term_id__isnull=False` rather than trusting every creation path: a
    # category with no term declares no word, so nothing can ever claim it — and
    # keying a dict on `None` would quietly make one such category the answer for
    # every unnamed link.
    return {category.term_id: category for category in core_models.Category.objects.filter(graph=graph, term_id__isnull=False)}


def active_relation_links(graph: core_models.Graph) -> list[evidence_models.Link]:
    """Every live relation assertion this graph projects.

    Scoped by the word claimed rather than by a prefix on the source ref: a
    relation names one of the organization's terms, and this graph declares a
    category for some of them.

    Filtered on the cached `status` rather than through the lifecycle log:
    `Link` caches its own status (`writer.archive` writes both in one
    transaction), so unlike nodes there is no separate log to consult.
    """
    return list(
        claims_module.standing(
            evidence_models.Link.objects.for_organization(graph.organization).filter(
                kind=evidence_models.Link.Kind.RELATION,
                term__in=selector_module.term_ids_for(graph),
            ),
            "link",
        ).select_related("term")
    )


def project_edges(
    controller: Any,
    graph: core_models.Graph,
    links: Iterable[evidence_models.Link],
) -> int:
    """Write relation edges into AGE from their evidence rows.

    Shared by `create_relation` and `rebuild` so that the edge a fresh assertion
    produces and the edge a replay produces cannot drift apart — the failure this
    whole layer exists to prevent.

    `MERGE` rather than `CREATE`, keyed on the proposition: replaying twice must
    not double an edge, and a second assertion of the same relation must land on
    the one already there.
    """
    projected = 0
    by_term = categories_by_term(graph)
    grouped: dict[tuple[str, str, Any], list[evidence_models.Link]] = {}
    for link in links:
        grouped.setdefault(proposition_key(link), []).append(link)

    for (source_ref, target_ref, term_id), assertions in grouped.items():
        category = by_term.get(term_id)
        if category is None:
            # Either the claim names no word at all, or this graph declares no
            # category for the one it names — so there is no label to draw it
            # under, and an unlabelled edge is unreachable by every query the
            # schema generates.
            logger.warning(
                "Relation link %s names a term this graph has no category for; it cannot be projected here.",
                assertions[0].pk,
            )
            continue

        source_uuid = str(source_ref)
        target_uuid = str(target_ref)

        result = controller.engine.execute(
            graph,
            f"""
            MATCH (s) WHERE s.id = $src
            MATCH (t) WHERE t.id = $tgt
            MERGE (s)-[r:{category.age_name}]->(t)
            SET r.category_id = $cid,
                r.__assertion_count = $count
            RETURN id(r) as edge_id
            """,
            {
                "src": source_uuid,
                "tgt": target_uuid,
                "cid": category.pk,
                # How many live claims stand behind this edge. The edge-side
                # analogue of `State.n`: one number that says whether a relation
                # rests on one annotator or on four independent ones.
                "count": len(assertions),
            },
        )

        # An unmatched endpoint yields no rows, so the `MERGE` never fired. This
        # used to increment regardless, which made the count a claim about how
        # many edges were written that nothing checked — and once a node can
        # leave the projection while its `Link` rightly survives, that is a
        # normal occurrence rather than an impossible one.
        if not result:
            logger.warning(
                "Relation %s -> %s (%s): one or both endpoints are not in this projection, so no edge was drawn.",
                source_ref,
                target_ref,
                category.age_name,
            )
            continue

        projected += 1

    return projected


def resolve_categories(graph: core_models.Graph, nodes: list[Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Which category each node projects as, and why some project as none.

    Returns `(ref -> category, ref -> reason)`. A ref appears in exactly one of
    the two.

    This is what makes a category's meaning a property of the *graph* rather than
    of the entity. A category with an empty `definition` is **primitive**:
    membership is whatever was asserted, which is the old behaviour and stays the
    default. A category carrying a definition is **defined** — necessary and
    sufficient conditions over classification claims — so the same node can be an
    `AIS` in one graph and an `AISproximal` in another with no evidence rewritten.

    Three refusals, all deliberate:

    - **The claims say it does not exist.** Somebody retracted it, and nobody
      this graph counts has attested it since. A node the evidence says is not
      there is not in the view — there is no such thing as a node that is present
      but flagged. Note this is folded under *this graph's* selector, so a
      retraction by somebody a graph does not listen to does not remove it there.
    - **No definition matches, and the node's own claims name no primitive
      category this graph declares** — the node is not in the view. A graph is a
      selection; a node satisfying nothing in it does not belong to it. The caller
      reports the count, because a definition silently shrinking a graph is the
      class of silence this codebase treats as a defect.
    - **More than one definition matches.** Apache AGE allows exactly one label
      per vertex — a deliberate design decision on its side, since every label is
      its own table — and this code assumes it everywhere (`labels(e)[0]`).
      Choosing arbitrarily would bury exactly the disagreement the evidence base
      exists to preserve, so this refuses and names the node, the same way
      `_value_kinds_for_rule` refuses an ambiguous term rather than picking one.
    """
    from evidence import claims as claims_module
    from evidence import selector as selector_module

    # This graph's categories, indexed by the organization term each declares.
    # That index is the whole join: a claim names a word, and this is where the
    # word becomes *this view's* rule for it.
    categories = list(core_models.Category.objects.filter(graph=graph).select_related("term"))
    defined = [category for category in categories if category.definition]
    by_term = {category.term_id: category for category in categories}

    # Existence first, and in bulk. Asked once for the whole batch rather than
    # once per node, for the same reason the definitions are evaluated once: a
    # rebuild resolves every node in the graph, and per-node would be N queries
    # to answer one question.
    retracted = claims_module.retracted_ids(
        graph.organization,
        "node",
        [str(node.ref) for node in nodes],
        selector_module.claim_filter(graph.selector),
    )

    # Built once and reused below. `classification_claims_for` is not free — it
    # resolves the graph's whole vocabulary first, which is two queries of its own
    # — and it used to be called again *inside* the definition loop, so a graph
    # with a dozen defined categories paid for its vocabulary a dozen times to
    # answer one question. A queryset is lazy, so reusing the object costs
    # nothing; each `.filter()` below still issues its own query, which is the
    # part that genuinely has to happen per definition.
    standing_claims = selector_module.classification_claims_for(graph)

    claims_by_ref: dict[str, list[Any]] = {}
    for claim in standing_claims:
        claims_by_ref.setdefault(str(claim.source_ref), []).append(claim)

    # Evaluate each definition once against the whole claim set rather than once
    # per node: a definition is a queryset predicate, so asking it N times would
    # be N queries to answer one question.
    matched_by_definition: dict[Any, set[str]] = {}
    for category in defined:
        refs = set(standing_claims.filter(selector_module.classification_filter(category.definition)).values_list("source_ref", flat=True))
        matched_by_definition[category.pk] = {str(ref) for ref in refs}

    by_pk = {category.pk: category for category in categories}
    resolved: dict[str, Any] = {}
    skipped: dict[str, str] = {}

    for node in nodes:
        ref = str(node.ref)

        if ref in retracted:
            skipped[ref] = "the claims this graph counts say it does not exist"
            continue

        matches = [by_pk[pk] for pk, refs in matched_by_definition.items() if ref in refs]

        if len(matches) > 1:
            names = ", ".join(sorted(category.key for category in matches))
            # Reported, not logged. This is read by the *read* paths too now
            # (`refs_admitted_by`), and a warning here fired on every list query for
            # as long as the ambiguity existed — the same line `project_all` already
            # emits at rebuild. Whoever can act on it does the logging.
            skipped[ref] = f"matches more than one defined category ({names}); a vertex carries one label, and choosing between them would hide the disagreement"
            continue

        if matches:
            resolved[ref] = matches[0]
            continue

        # No definition claimed it. Fall back to a *primitive* category this graph
        # declares for a word the node was claimed under — a graph with no
        # definitions at all therefore behaves exactly as it did before any of
        # this existed.
        primitive = [by_term[claim.term_id] for claim in claims_by_ref.get(ref, []) if claim.term_id in by_term and not by_term[claim.term_id].definition]
        if primitive:
            resolved[ref] = primitive[0]
            continue

        # Nothing to fall back on either: every word it was claimed under is
        # defined here, and none of those definitions admitted it.
        if node.term_id in by_term and not by_term[node.term_id].definition:
            resolved[ref] = by_term[node.term_id]
            continue

        skipped[ref] = "no category in this graph admits it: every term it was asserted as is defined, and none of those definitions match"

    return resolved, skipped


def refs_admitted_by(category: core_models.Category) -> set[str]:
    """Every node this category draws — asked of the claims, not of the drawing.

    What a category-scoped node list needs, and it goes through
    :func:`resolve_categories` rather than reimplementing the rule. That matters
    more here than it looks: the list would otherwise be a *fourth* place deciding
    membership, and the three that exist agree on purpose. A definition that admits
    a node the list did not show, or the reverse, would be indistinguishable from a
    stale projection.

    The candidate set is narrowed first so this costs the category rather than the
    graph. A node can only resolve to this category two ways — its definition
    matched (so some standing `CLASSIFIES` claim names one of the words its
    ``asserted_as`` lists), or the category is primitive and the node was claimed
    under its word (as `Instance.term` or as a claim naming that term). Anything outside
    that set resolves elsewhere or nowhere, so leaving it out cannot change an
    answer. `resolve_categories` evaluates every definition in the graph against
    whatever batch it is given, so its verdict for these nodes is the same one a
    whole-graph pass would reach.
    """
    graph = category.graph
    standing_claims = selector_module.classification_claims_for(graph)

    asserted_as = selector_module.asserted_as_keys(category.definition) if category.definition else []
    if asserted_as:
        claimed = standing_claims.filter(term__key__in=asserted_as)
    else:
        claimed = standing_claims.filter(term_id=category.term_id)
    claimed_refs = {str(ref) for ref in claimed.values_list("source_ref", flat=True)}

    candidates = list(selector_module.instances_for(graph).filter(Q(term_id=category.term_id) | Q(id__in=claimed_refs)).select_related("term"))
    resolved, _ = resolve_categories(graph, candidates)

    return {ref for ref, drawn_as in resolved.items() if drawn_as.pk == category.pk}


def refs_in_graph(graph: core_models.Graph) -> set[str]:
    """Every node this graph holds, by the claims — the whole view's membership.

    `instances_for` says which nodes the graph's *words* admit; this additionally folds
    existence and the categories' definitions, which is what decides whether the
    view holds the node at all. Same answer `project_all` draws, asked without
    reference to whether it has drawn it yet.

    **This costs the whole view, and its caller paginates afterwards.** Every node the
    graph's words admit is loaded and resolved to answer a request for ten of them,
    where the Cypher it replaced pushed `SKIP`/`LIMIT` into the projection. Said out
    loud rather than left to be discovered: the rule is evaluated in Postgres against
    claims and definitions, and it has no `SKIP` to push. Narrowing it means either
    teaching `resolve_categories` to answer for a page — which would page over a set
    it has not finished computing — or accepting short pages, so it is a deliberate
    trade and not an oversight. `refs_admitted_by` is bounded by its category and is
    the one to prefer where a category is known.
    """
    nodes = list(selector_module.instances_for(graph).select_related("term"))
    resolved, _ = resolve_categories(graph, nodes)
    return set(resolved)


#: The two participation kinds, and which way the projected edge points. An input
#: runs entity → event ("this cell went through mitosis"); an output runs event →
#: entity ("mitosis produced this cell"). Keeping the direction in the projection
#: rather than only in the kind is what lets a path query traverse a protocol in
#: the order it happened.
PARTICIPATION_KINDS = (
    evidence_models.Link.Kind.PARTICIPATES_AS_INPUT,
    evidence_models.Link.Kind.PARTICIPATES_AS_OUTPUT,
)


def edge_pattern_for(category: Any, link: evidence_models.Link) -> tuple[str, bool]:
    """How this graph draws one link: `(edge label, does it run target → source)`.

    The single answer to "what does this claim look like in AGE", shared by the
    code that writes the edge and the code that reads it back. It exists because
    the two disagreed, silently and in the direction that fails green:
    `get_relation_by_ref` matched `(source)-[r:{category.age_name}]->(target)`
    for *every* kind of link, and for participation both halves of that are
    wrong.

    - **The label.** A participation edge is not labelled with the category's
      `age_name`. The category a participation claim names is the **event's** —
      a `NodeCategory` — and the label comes off its `AGE_INPUT_EDGE` /
      `AGE_OUTPUT_EDGE`, which are constants of the event kind rather than of the
      graph. `as_kind()` is needed first, because a foreign key hands back a base
      `Category` that carries the columns but none of the proxy's attributes.
    - **The direction.** `participation_key` puts the entity in `source_ref` and
      the event in `target_ref` regardless of side, but an *output* participation
      is drawn event → entity. So for outputs the AGE edge runs target → source,
      and a reader matching source → target finds nothing.

    Finding nothing is not an error at either call site, so the mismatch could not
    surface as a failure — only as a permanently empty result.
    """
    if link.kind in (evidence_models.Link.Kind.PARTICIPATES_AS_INPUT, evidence_models.Link.Kind.PARTICIPATES_AS_OUTPUT):
        event_category = category.as_kind()
        is_input = link.kind == evidence_models.Link.Kind.PARTICIPATES_AS_INPUT
        label = event_category.AGE_INPUT_EDGE if is_input else event_category.AGE_OUTPUT_EDGE
        return str(label), not is_input

    return str(category.age_name), False


def participation_key(link: evidence_models.Link) -> tuple[str, str, str, Any]:
    """What makes two participation claims claims about the same thing.

    The entity, the event, which side, and the role. Not the category: an event
    has exactly one, and folding it in would let a schema edit look like a
    different proposition.
    """
    return (str(link.source_ref), str(link.target_ref), str(link.kind), link.role)


def active_participation_links(graph: core_models.Graph) -> list[evidence_models.Link]:
    """Every live participation claim this graph projects.

    Scoped by the event category the claim names, for the same reason
    :func:`active_relation_links` is.
    """
    return list(
        claims_module.standing(
            evidence_models.Link.objects.for_organization(graph.organization).filter(
                kind__in=PARTICIPATION_KINDS,
                term__in=selector_module.term_ids_for(graph),
            ),
            "link",
        ).select_related("term")
    )


def project_participation(
    controller: Any,
    graph: core_models.Graph,
    links: Iterable[evidence_models.Link],
) -> int:
    """Draw the entity-to-event edges the evidence claims.

    Shared by `create_natural_event` and `rebuild`, for the same reason
    `project_edges` is: the edge a fresh assertion produces and the edge a replay
    produces cannot be allowed to drift apart.

    The role rides on the edge as a property rather than in its label, so
    `MATCH (e)-[:WENT_THROUGH]->(ev)` finds every input without the caller first
    enumerating the schema's role names.
    """
    projected = 0
    by_term = categories_by_term(graph)
    grouped: dict[tuple[str, str, str, Any], list[evidence_models.Link]] = {}
    for link in links:
        grouped.setdefault(participation_key(link), []).append(link)

    for (source_ref, target_ref, kind, role), claims in grouped.items():
        category = by_term.get(claims[0].term_id)
        if category is None:
            logger.warning("Participation link %s names a term this graph has no category for; nothing says which edge label it projects to.", claims[0].pk)
            continue

        # A foreign key hands back a base `Category`, which carries every field
        # and none of the kind-specific attributes — the edge labels live on the
        # event proxies.
        category = category.as_kind()

        # Label and direction come from the shared helper rather than from a
        # second copy of this logic, because the reader's copy had drifted — see
        # `edge_pattern_for`.
        label, reversed_edge = edge_pattern_for(category, claims[0])
        is_input = not reversed_edge

        entity_uuid = str(source_ref)
        event_uuid = str(target_ref)

        pattern = f"(entity)-[r:{label}]->(event)" if is_input else f"(event)-[r:{label}]->(entity)"

        result = controller.engine.execute(
            graph,
            f"""
            MATCH (entity) WHERE entity.id = $entity_uuid
            MATCH (event) WHERE event.id = $event_uuid
            MERGE {pattern}
            SET r.role = $role,
                r.category_id = $cid,
                r.__assertion_count = $count
            RETURN id(r) as edge_id
            """,
            {
                "entity_uuid": entity_uuid,
                "event_uuid": event_uuid,
                "role": role,
                "cid": category.pk,
                # Participation is contestable like everything else: two people
                # claiming the same cell went into the same event are two rows
                # and one edge, and the count is what says whether the claim
                # rests on one observer or several.
                "count": len(claims),
            },
        )

        # See `project_edges`: no rows means an endpoint is not in this
        # projection and the `MERGE` never fired, so there is nothing to count.
        if not result:
            logger.warning(
                "Participation %s -> %s (role %r): one or both endpoints are not in this projection, so no edge was drawn.",
                source_ref,
                target_ref,
                role,
            )
            continue

        projected += 1

    return projected


def _write_properties(
    controller: Any,
    graph: core_models.Graph,
    claim_ref: str,
    category: core_models.Category,
    values: dict[str, Any],
) -> bool:
    """Set properties on the AGE node identified by a durable entity ref.

    Matched by the node's stable `id` property rather than by vertex id, because
    vertex ids do not survive a rebuild — which is the whole reason refs are
    keyed on the uuid.

    Returns whether a vertex was actually matched. A `SET` against nothing is a
    silent no-op in Cypher, so without this the caller cannot tell a written
    node from an absent one — and reports both as projected.
    """
    node_uuid = str(claim_ref)

    set_clause = ", ".join(f"e.{controller._validate_property_key(key)} = $u_{key}" for key in values)
    params: dict[str, Any] = {f"u_{key}": value for key, value in values.items()}
    params["node_uuid"] = node_uuid

    result = controller.engine.execute(
        graph,
        f"""
        MATCH (e:{category.age_name}) WHERE e.id = $node_uuid
        SET {set_clause}
        RETURN id(e) as node_id
        """,
        params,
    )
    return bool(result)


def create_vertex(controller: Any, graph: core_models.Graph, node: Any, category: Any) -> None:
    """Draw one node into the projection.

    Shared by `rebuild` and `reproject_node` so that a replayed vertex and a
    freshly re-attested one cannot differ — the same reason `project_edges` is
    shared between creating a relation and replaying one.

    The vertex carries its identity, **what kind of thing it is**, and its label.
    Every other value on it is derived, and `project` is what derives them.

    ``type`` comes from `Instance.kind` — the claim's own account of what it is —
    rather than from the label, which is `category.age_name` and therefore this
    view's private rename of a word. Reading the kind off the label is what made
    every drawn event answer `__typename: Entity`: `RetrievedNode.node_type` fell
    back to matching "Cell" or "Mitosis" against a fixed vocabulary of five words
    it could never be one of. A node's kind is a fact about the claim, so the
    claim is where it is taken from — and it is written here so that a vertex is
    self-describing to any reader, which is what removes the fallback entirely.
    """
    # `MERGE` on the id, not `CREATE`: drawing a node that is already drawn —
    # `attest_node` on a standing node, `project_all` over a populated namespace, an
    # incremental replay — has to converge on one vertex, not add a second. The
    # label is part of the pattern, so a node whose *label* moved still needs its
    # old vertex cleared first; `reproject_node` does that, `rebuild` drops the
    # namespace, and `project_all` relies on one of the two having happened.
    controller.engine.execute(
        graph,
        f"""
        MERGE (e:{category.age_name} {{id: $eid}})
        SET e.category_id = $cid, e.type = $ntype
        RETURN id(e) as db_id
        """,
        {"eid": str(node.ref), "cid": category.pk, "ntype": str(node.kind).upper()},
    )


def unproject(controller: Any, graph: core_models.Graph, instance_refs: Iterable[str]) -> int:
    """Remove nodes from the projection. Returns how many vertices went.

    The counterpart of :func:`project`, and the node-side analogue of the
    `DELETE r` in `controller._reproject_proposition`. A node the evidence says
    is not there does not linger behind a flag: `rebuild` would not recreate it,
    and a projection that disagrees with a replay is the failure this whole layer
    exists to prevent.

    `DETACH`, because an edge to a nonexistent node is not in the view either.
    The `Link` rows behind those edges are claims and survive completely
    untouched — only the drawing goes. If somebody attests the node again, the
    edges are redrawn from those claims, which is exactly what `rebuild` does.
    """
    removed = 0
    for claim_ref in instance_refs:
        # Counted before the delete: AGE reports nothing useful back from
        # `DETACH DELETE`, and a count that always said "1" would be the same
        # kind of lie `project_edges` used to tell.
        found = controller.engine.execute(
            graph,
            "MATCH (e) WHERE e.id = $node_uuid RETURN id(e) as db_id",
            {"node_uuid": str(claim_ref)},
        )
        if not found:
            continue

        controller.engine.execute(
            graph,
            "MATCH (e) WHERE e.id = $node_uuid DETACH DELETE e",
            {"node_uuid": str(claim_ref)},
        )
        removed += 1

    return removed


def reproject_node(controller: Any, graph: core_models.Graph, node: Any) -> bool:
    """Draw a node back into the projection, edges and all.

    Everything `rebuild` would do for this one node, using the same functions —
    if any of it were reattestation-specific, a re-attested node and a replayed
    one could differ, which is the class of failure this layer exists to prevent.

    Returns whether the node was actually drawn. It may not be: a node whose
    claims no longer place it in any of this graph's terms does not come back
    just because somebody says it exists, and `resolve_categories` is what
    decides that.
    """
    # Clear whatever this view drew for the node before, edges and all. The claims
    # may have moved it under another label, and `create_vertex` merges on
    # `(label, id)` — so without this a relabelled node would keep its previous
    # self under the previous label. A node this view no longer admits is thereby
    # erased rather than left standing, which is what the claims say.
    unproject(controller, graph, [str(node.ref)])

    resolved, _ = resolve_categories(graph, [node])
    category = resolved.get(str(node.ref))
    if category is None:
        return False

    create_vertex(controller, graph, node, category)

    # Its edges come from the claims, not from anything remembered about what the
    # vertex used to have. Scoped to this node so re-attesting one entity does
    # not redraw the whole graph.
    project_edges(controller, graph, [link for link in active_relation_links(graph) if node.ref in (str(link.source_ref), str(link.target_ref))])
    project_participation(controller, graph, [link for link in active_participation_links(graph) if node.ref in (str(link.source_ref), str(link.target_ref))])
    project(controller, graph, [str(node.ref)])
    return True


def project_all(controller: Any, graph: core_models.Graph) -> dict[str, int]:
    """Draw everything this graph contains, into whatever is already there.

    The replay half of :func:`rebuild`, without the drop and without the
    organization-wide state refold. Split out for the graph that has just been
    materialized: it needs every node its words admit, but its namespace is
    already empty, and refolding every metric in the organization is not
    something one new view is entitled to do.

    `MERGE`-shaped throughout — `create_vertex` and `project_edges` are the same
    functions `rebuild` calls — so running this over a populated projection
    converges rather than duplicating. (`create_vertex` was a bare `CREATE` for a
    while and this sentence was false; `tests/projector/test_draw_converges.py`
    keeps it true.) One thing it cannot do is move a vertex between labels —
    `MERGE` is per label — which is why a definition change still goes through
    `rebuild`.
    """
    # Every node this graph contains. `Instance` carries no cached "does it exist"
    # column, so which of these actually get a vertex is decided by
    # `resolve_categories`, which folds the claims under this graph's selector.
    nodes = list(selector_module.instances_for(graph).select_related("term"))

    # Which label each node takes is a question about *this graph's* categories,
    # not a fact stored on the node — see `resolve_categories`. Answered before
    # anything is drawn so a definition that admits nothing fails loudly.
    resolved, skipped = resolve_categories(graph, nodes)

    for node in nodes:
        category = resolved.get(str(node.ref))
        if category is None:
            continue
        create_vertex(controller, graph, node, category)

    # Edges after nodes: `MATCH (s) ... MATCH (t)` needs both endpoints to exist.
    edges = project_edges(controller, graph, active_relation_links(graph))
    participations = project_participation(controller, graph, active_participation_links(graph))

    projected = project(controller, graph, [ref for ref in resolved])

    if skipped:
        logger.warning("graph #%s: %d node(s) admitted by no category in this graph and left unprojected.", graph.pk, len(skipped))
        # Each reason, once, here — where somebody can act on it. `resolve_categories`
        # used to log the ambiguous case itself, which meant every read that consults
        # the rule logged it too.
        for ref, reason in skipped.items():
            logger.warning("graph #%s: %s: %s", graph.pk, ref, reason)

    # `unclassified` is reported, not swallowed. A definition that narrows a
    # category also shrinks the graph, and a caller that cannot see by how much
    # cannot tell a deliberate selection from a broken one.
    return {
        "nodes": len(resolved),
        "unclassified": len(skipped),
        "edges": edges,
        "participations": participations,
        "projected": projected,
    }


def refs_drawn_as(graph: core_models.Graph, category: core_models.Category) -> list[str]:
    """The refs this graph currently draws under one category.

    Asked of `resolve_categories` rather than of a column, because which category
    a node takes is this graph's question — a `definition` can move a node between
    categories without anything on the node changing.
    """
    nodes = list(selector_module.instances_for(graph).select_related("term"))
    resolved, _ = resolve_categories(graph, nodes)
    return [ref for ref, resolved_category in resolved.items() if resolved_category.pk == category.pk]


def rematerialize_category(
    controller: Any,
    graph: core_models.Graph,
    category: core_models.Category,
    retired_keys: Iterable[str] = (),
) -> int:
    """Redraw every vertex this category owns, under its current properties.

    The cost of the rule that a read is a graph query. When the projection held
    only the filterable properties, editing a category's properties was free —
    the read folded whatever the definition said *at read time*, so it was never
    stale. Now the vertex is the answer, so changing the question has to rewrite
    it. `derive_properties`' docstring names this as the trade; this is the
    function that pays it.

    **Clear, then redraw.** Cypher `SET` only adds and overwrites, so anything
    the previous pass wrote and this one does not would stay on the vertex
    forever, answering queries with a value no rule in the graph still derives —
    and nothing would ever correct it, because the code that would have is
    exactly the code that stopped running. So every key this category *can* own
    is removed first and `project` immediately re-sets whatever still derives.

    Sweeping the whole owned set rather than the difference is deliberate. Three
    ways a key goes stale, and only the first is a difference:

    - the property was dropped from the definition (`retired_keys` — the caller
      knows what the old definition owned, this function does not);
    - the property stayed but stopped deriving: `derive_properties` writes a key
      only `if value is not None`, so re-pointing a rule at a structure kind with
      no evidence leaves the old value in place;
    - the statistics are conditional: `_property_statistics` omits `spread`,
      `from` and `to` when the state has no bounds, so a value can survive its
      own evidence window.

    Not a `rebuild`: no label moves here. The set of nodes is unchanged and each
    keeps its vertex; only the properties on it are rewritten. A `definition`
    change, which *can* move a node between labels, still needs the full rebuild
    — see `controller.backfill_category`.
    """
    refs = refs_drawn_as(graph, category)
    if not refs:
        return 0

    owned = sorted(set(retired_keys) | derived_property_keys(category))
    if owned:
        remove_clause = ", ".join(f"e.{controller._validate_property_key(key)}" for key in owned)
        controller.engine.execute(
            graph,
            f"""
            MATCH (e:{category.age_name}) WHERE e.id IN $refs
            REMOVE {remove_clause}
            RETURN id(e) as node_id
            """,
            {"refs": [str(ref) for ref in refs]},
        )

    projected = project(controller, graph, refs)
    logger.info(
        "graph #%s: rematerialized '%s' — %d node(s), %d key(s) swept.",
        graph.pk,
        category.key,
        projected,
        len(owned),
    )
    return projected


def rebuild(controller: Any, graph: core_models.Graph) -> dict[str, int]:
    """Drop the projection and replay it from evidence.

    The honesty test. Everything AGE holds for this graph is destroyed and
    reconstructed from Postgres alone; if anything is missing afterwards, it was
    never really derived.

    State vectors are rebuilt too. They are also a cache — statistics folded from
    metrics — so replaying without them would only prove the projection can be
    rebuilt from *another* cache. That refold is organization-wide, which is why
    it lives here and not in :func:`project_all`.

    So are the standing answers, and those come **first**: `CurrentStanding` is what
    every "which of these still count" narrowing reads, so replaying nodes and
    edges before it would replay them against a cache this rebuild has not yet
    proved. Same argument as `refold_state`, one layer down — and the reason it is
    ordered before the drop rather than after.

    The replay itself is `project_all`, unshared with nothing: a rebuilt graph and
    a backfilled one have to be the same graph, and one code path is the only way
    to know they are.
    """
    from core import asserted_terms
    from evidence import identity as identity_module

    organization = graph.organization

    # Every cache the replay reads is refolded or checked **before** the replay
    # reads it, or the rebuild would only prove the projection can be rebuilt from
    # other caches. Three of them, all organization-grain:
    #
    # - `CategoryAssertedTerm` — which words each definition derives from. It is
    #   what `selector.term_ids_for` reads to decide membership, so a stale row
    #   here silently changes which nodes the replay draws. Vocabulary-sized.
    # - `InstanceIdentity` — the SAME_AS components. A retraction only flags a
    #   component; the flagged ones are recomputed here.
    # - `CurrentStanding` — what every "which of these still count" narrowing reads.
    asserted_terms.refold(organization)
    identity_module.recompute_stale(organization)
    claims_current = claims_module.refold_current(organization)

    # The log position this replay is a picture of. Read before enumerating, so an
    # assertion that commits while the replay runs is either in the picture or
    # still in the outbox — never silently counted as applied.
    head = watermark.max_seq(organization)

    # Resolved once here purely to fail *before* the drop. A definition that
    # admits nothing, or one that admits a node under two categories, has to raise
    # while the projection it would replace is still standing — the alternative is
    # an empty namespace and an exception, with nothing left to fall back on.
    # `project_all` resolves again after the drop; one redundant pass is the price
    # of the guarantee, and rebuild is the expensive operation either way.
    resolve_categories(graph, list(selector_module.instances_for(graph).select_related("term")))

    # Marked *before* the drop. A rebuild that dies between here and the end
    # leaves an empty namespace; `REBUILDING` makes the cursor report everything
    # as outstanding instead of "caught up" over nothing.
    watermark.mark_rebuilding(graph)

    controller.engine.drop_graph(graph.age_name, cascade=True)
    controller.engine.create_graph(age_name=graph.age_name)

    counts = project_all(controller, graph)
    counts["claims"] = claims_current
    counts["states"] = refold_state(organization)

    watermark.mark_consistent(graph, through_seq=head, schema_hash=watermark.active_schema_hash(graph), rebuilt=True)
    return counts


def refold_state(organization: Any) -> int:
    """Rebuild every state vector in the organization, from the metrics themselves.

    Deletes the existing rows first rather than merging over them: merging into a
    stale row would double-count, and the point of a rebuild is to depend on
    nothing that came before it.

    **Organization-wide, and no selector.** Two things were wrong with the
    per-graph version, and they were the same thing twice.

    It applied `graph.selector` to the metrics while `state.merge` — the
    incremental path — did not, so a rebuild and an ingest produced different
    rows from the same evidence. Worse, `recompute` did not apply it either and
    ran lazily on any row a retraction marked stale, so one retraction after a
    rebuild silently re-admitted out-of-scope metrics into a row that had just
    been made correct. State is organization grain now and nothing folds under a
    selector, so there is no longer anything for the three writers to disagree
    about. Which metrics a *view* counts is answered at read time, in
    :func:`derive_properties`.

    And it scoped the rows by `informs_links_for(graph)`, which only matches
    nodes — so state keyed on an *edge* (`_attach_supporting_evidence` keys those
    on a bare `Link` pk) was neither deleted nor refolded. Those rows were the one
    cache a rebuild could not rebuild, which made this module's central claim
    false for every relation carrying supporting evidence. Folding the
    organization covers them by construction.

    Called from `rebuild`, which is per-graph — so a graph rebuild touches rows
    the whole organization shares. That is a deliberate widening: the operation is
    idempotent and the rows have one correct value, so doing it more often than
    strictly needed costs time and cannot cost correctness.

    **One transaction**, and that is what keeps the widening honest. The delete
    empties the organization's statistics before the refold puts them back, so a
    failure partway through the loop would otherwise leave *every* graph in the
    tenant without derived values rather than the one being rebuilt — turning a
    per-graph operation into a tenant-wide outage at exactly the moment something
    is already going wrong.
    """
    from django.db import transaction

    with transaction.atomic():
        evidence_models.State.objects.for_organization(organization).delete()

        folded = 0
        # Ordered by the log's own order, not by world time. Most of `state.merge`
        # is a genuine monoid and does not care — min, max, sum and n commute, and
        # first/last compare `measured_at` rather than trusting arrival. Two things
        # do care, and both were nondeterministic under `order_by("measured_at")`,
        # which has no tiebreak: `last_ts` uses `>=`, so metrics sharing an exact
        # observation time resolve to whichever was folded last; and
        # `high_water_assertion` is assigned unconditionally, so it ended up naming
        # an arbitrary assertion rather than the furthest one. `assertion.seq` is
        # arrival order, cannot tie, and makes the name true.
        for metric in claims_module.standing(evidence_models.Metric.objects.for_organization(organization), "metric").select_related("structure", "structure__kind", "assertion").order_by("assertion__seq"):
            refs = refs_informed_by(organization, [metric.structure_id])
            if refs:
                state_module.merge(metric, refs)
                folded += 1

    return folded


def refold_stale(organization: Any) -> int:
    """Rebuild every state row a retraction left stale. Returns how many were fixed.

    Lives here rather than in `evidence.state` because it is an operational sweep
    rather than part of the fold, and operators want it. `state.recompute_stale`
    was its previous home and had no production caller at all.
    """
    return state_module.recompute_stale(organization)


# ---------------------------------------------------------------------------
# Incremental replay: apply what the outbox says is owed.
# ---------------------------------------------------------------------------


def touched_refs(organization: Any, assertion_ids: Iterable[Any], since_seq: int | None = None) -> tuple[set[str], bool]:
    """Every node ref whose drawing one of these assertions could have changed.

    Returns ``(refs, saw_same_as)``. The closure is taken per claim table, each
    a single `assertion` join — the log's own shape — and every claim kind maps
    to the node(s) whose vertex, edges or derived properties it can move:

    - an `Instance` — itself;
    - a `Link` — its node endpoints by kind: RELATION, PARTICIPATES_*, SAME_AS on
      both sides; CLASSIFIES, INFORMS, MEASUREMENT on the node side only (the
      other end is a term or a structure). STRUCTURE_RELATION touches no node;
    - a `Structure` or a `Metric` — every node the structure informs
      (`refs_informed_by`), since that is what its derived properties fold over;
    - a `Standing` — by what it is about: a node, a link's endpoints, or the nodes
      a metric's or structure's structure informs. A comment's standing moves no
      drawing.

    `since_seq` widens the set belt-and-braces to every claim at or after the
    lowest outstanding seq, so a replay also repairs a drawing that went wrong
    without leaving an outbox row. A ref that names no `Instance` (an INFORMS onto
    a link, say) is harmless: it resolves to no node and is never drawn.
    """
    ids = list(assertion_ids)
    if not ids and since_seq is None:
        return set(), False

    predicate = Q(assertion_id__in=ids)
    if since_seq is not None:
        predicate |= Q(assertion__seq__gte=since_seq)

    refs: set[str] = set()
    saw_same_as = False

    refs.update(str(pk) for pk in evidence_models.Instance.objects.for_organization(organization).filter(predicate).values_list("id", flat=True))

    both = {evidence_models.Link.Kind.RELATION, evidence_models.Link.Kind.PARTICIPATES_AS_INPUT, evidence_models.Link.Kind.PARTICIPATES_AS_OUTPUT, evidence_models.Link.Kind.SAME_AS}
    source_side = {evidence_models.Link.Kind.CLASSIFIES}
    target_side = {evidence_models.Link.Kind.INFORMS, evidence_models.Link.Kind.MEASUREMENT}

    def _link_refs(links: Iterable[Any]) -> None:
        nonlocal saw_same_as
        for kind, source_ref, target_ref in links:
            if kind in both:
                refs.add(str(source_ref))
                refs.add(str(target_ref))
                if kind == evidence_models.Link.Kind.SAME_AS:
                    saw_same_as = True
            elif kind in source_side:
                refs.add(str(source_ref))
            elif kind in target_side:
                refs.add(str(target_ref))

    _link_refs(evidence_models.Link.objects.for_organization(organization).filter(predicate).values_list("kind", "source_ref", "target_ref"))

    structure_ids: set[Any] = set(evidence_models.Structure.objects.for_organization(organization).filter(predicate).values_list("id", flat=True))
    structure_ids.update(evidence_models.Metric.objects.for_organization(organization).filter(predicate).values_list("structure_id", flat=True))

    standings = list(evidence_models.Standing.objects.for_organization(organization).filter(predicate).values_list("target_type", "target_id"))
    by_type: dict[str, set[str]] = {}
    for target_type, target_id in standings:
        by_type.setdefault(str(target_type), set()).add(str(target_id))
    refs.update(by_type.get("node", set()))
    if by_type.get("link"):
        _link_refs(evidence_models.Link.objects.for_organization(organization).filter(id__in=by_type["link"]).values_list("kind", "source_ref", "target_ref"))
    if by_type.get("metric"):
        structure_ids.update(evidence_models.Metric.objects.for_organization(organization).filter(id__in=by_type["metric"]).values_list("structure_id", flat=True))
    if by_type.get("structure"):
        structure_ids.update(by_type["structure"])

    if structure_ids:
        refs.update(str(ref) for ref in refs_informed_by(organization, list(structure_ids)))

    return refs, saw_same_as


def converge(controller: Any, graph: core_models.Graph, refs: Iterable[str]) -> dict[str, int]:
    """Make this graph's drawing of these nodes equal what a rebuild would draw.

    Per node, exactly what `reproject_node` does; batched so the category
    resolution and the edge scans happen once for the set. Clear first, then
    redraw from the claims: a node the view no longer admits is erased, one whose
    label moved lands under the new one, and every edge touching the set is
    re-merged from the active links with its `__assertion_count` recomputed.
    Folds of untouched nodes cannot have moved — derived properties fold per node
    over Postgres and read nothing from a neighbour — so nothing else is touched.
    """
    touched = {str(ref) for ref in refs}
    if not touched:
        return {"nodes": 0, "edges": 0, "participations": 0, "projected": 0, "erased": 0}

    nodes = list(evidence_models.Instance.objects.for_organization(graph.organization).filter(id__in=touched).select_related("term"))
    erased = unproject(controller, graph, [str(node.ref) for node in nodes])

    resolved, _ = resolve_categories(graph, nodes)
    for node in nodes:
        category = resolved.get(str(node.ref))
        if category is not None:
            create_vertex(controller, graph, node, category)

    edges = project_edges(controller, graph, [link for link in active_relation_links(graph) if str(link.source_ref) in touched or str(link.target_ref) in touched])
    participations = project_participation(controller, graph, [link for link in active_participation_links(graph) if str(link.source_ref) in touched or str(link.target_ref) in touched])
    projected = project(controller, graph, list(resolved))

    return {"nodes": len(resolved), "edges": edges, "participations": participations, "projected": projected, "erased": erased}


def replay(controller: Any, organization: Any) -> dict[str, Any]:
    """Apply every outstanding assertion of the organization to every consistent graph.

    The incremental counterpart of :func:`rebuild`. Organization-scoped by
    construction: an outbox row is organization-grain, and a CLASSIFIES claim can
    widen membership in any view, so there is no per-graph slice of "what is
    owed" to replay. Graphs that are `NEEDS_BACKFILL` or `REBUILDING` are skipped
    and named — they need a full `rebuild`, and a partial redraw of an undrawn
    graph would only make its lag dishonest.

    Settles **exactly** the outbox rows it read, by id, after applying them to
    every graph it processed. A row committed after the snapshot is left for the
    next replay; a row whose assertion has no claims (a crash between the two
    transactions of `create_entity`) is settled with nothing to draw.
    """
    from evidence import identity as identity_module
    from graph_engine import models as projection_models

    pending = list(projection_models.PendingProjection.objects.filter(organization=organization).select_related("assertion"))
    pending_ids = [row.pk for row in pending]
    lowest = min((int(row.assertion.seq) for row in pending), default=None)
    head = watermark.max_seq(organization)

    refs, saw_same_as = touched_refs(organization, pending_ids, since_seq=lowest)

    if saw_same_as:
        # Merges were applied in their own transactions; retractions only flag.
        # Recompute the flagged components, then widen to every member of the
        # components the touched nodes sit in — sameness is a property of the
        # component, and `_reproject_claim` redraws all of them for the same reason.
        identity_module.recompute_stale(organization)
        for members in identity_module.component_refs(organization, list(refs)).values():
            refs.update(str(ref) for ref in members)

    graphs = list(core_models.Graph.objects.filter(organization=organization).order_by("id"))
    rows = {row.graph_id: row for row in projection_models.Projection.objects.filter(graph__in=graphs)}
    processed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for graph in graphs:
        row = rows.get(graph.pk) or watermark.projection_for(graph)
        if row.status != projection_models.Projection.Status.CONSISTENT:
            skipped.append({"graph": graph, "status": str(row.status)})
            continue
        counts = converge(controller, graph, refs)
        watermark.mark_consistent(graph, through_seq=head, schema_hash=row.schema_hash)
        processed.append({"graph": graph, **counts})

    settled = watermark.settle_many(pending_ids)

    return {
        "pending": len(pending_ids),
        "settled": settled,
        "lowest_seq": lowest,
        "head": head,
        "refs": len(refs),
        "graphs": processed,
        "skipped": skipped,
    }
