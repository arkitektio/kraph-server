"""Building a view's drawing — the table projection — from the evidence base.

The projection is a cache. Everything in it is derivable from
:mod:`evidence.models` plus a schema version, which means it can be dropped and
rebuilt at will — and `test_reproject_idempotent` proves that rather than
asserting it. If the graph cannot be rebuilt from the evidence, the evidence is
not the source of truth whatever the documentation says.

Four operations, and nothing else:

- :func:`dirty` — which entities a change invalidates
- :func:`project` — recompute those entities' properties into the drawing
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

import datetime
import logging
import uuid
from collections.abc import Iterable, Mapping, Sequence
from itertools import combinations
from typing import Protocol, runtime_checkable

from authentikate.models import Organization
from django.db.models import Q, QuerySet

from core import models as core_models
from core.enums import ValueKind
from evidence import claims as claims_module
from evidence import models as evidence_models
from evidence import selector as selector_module
from evidence import state as state_module
from evidence import writer as writer_module
from evidence.models import JSONValue
from graph_engine import aggregate
from graph_engine import locks, watermark
from graph_engine.input_models import DerivationRuleInput, DerivationType, PropertyDefinitionInput
from graph_engine.projection.protocol import Projector
from graph_engine.reports import DrawCounts, GraphReplay, ReplayReport, SkippedGraph

logger = logging.getLogger(__name__)


@runtime_checkable
class DrawingHost(Protocol):
    """What this module needs of the controller: the projector it draws through.

    Every function here took `controller: Any`, and what it actually used was
    one attribute — `controller.projector`. Saying so is what makes the claim in
    the module docstring checkable: this module decides *what* to draw and knows
    nothing about how, so it must not be able to reach the controller's writes,
    its authorization, or its evidence transactions. A protocol also keeps
    `GraphController` free to stay the only implementation without this module
    importing it, which would close a cycle.
    """

    @property
    def projector(self) -> Projector:
        """The projection kind this host draws through."""
        ...

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


def dirty(graph: core_models.Graph, structure_ids: Iterable[evidence_models.Ref]) -> list[str]:
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


def is_derived(prop: PropertyDefinitionInput) -> bool:
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


def refs_informed_by(organization: Organization, structure_ids: Iterable[evidence_models.Ref]) -> list[str]:
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


def graphs_for_refs(organization: Organization, refs: Iterable[str]) -> dict[int, list[str]]:
    """Group node refs by the graph that projects them.

    Replaces splitting the ref on `:`. A ref is a bare uuid now, so which view
    it belongs to is a question for the evidence base — and one a ref can answer
    with more than one graph, which the prefix could never express.

    Refs with no `Instance` row simply do not appear: they are edge refs, or nodes
    of a graph that has since been deleted. Both are expected — evidence
    outlives the projections built from it.
    """
    from core import models as core_models

    by_graph_id: dict[int, list[str]] = {}
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


def _derived_properties(category: core_models.Category) -> list[PropertyDefinitionInput]:
    """The property definitions on a category that come from evidence."""
    return [prop for prop in (category.defined_properties or []) if is_derived(prop)]


def _refs(value: str | Iterable[str]) -> list[str]:
    """One ref or several, as a list of strings.

    Every fold below takes the **members** of an individual (RFC 0018): the
    instances a view holds to be one thing, so a measurement informing any of
    them is a measurement of the individual. A single ref is the common case
    and is accepted as itself.
    """
    if isinstance(value, str):
        return [value]
    return [str(ref) for ref in value]


def _structure_ids_informing(graph: core_models.Graph, claim_ref: str | Iterable[str], definition: selector_module.Definition | None = None) -> list[uuid.UUID]:
    """The structure primary keys whose measurements reach this individual — any of its members.

    ``definition`` is the node's category rule (RFC 0009): whose INFORMS claims
    may route evidence under this node is that category's question, so the fold
    paths pass it and the routing folds under its clauses. Without one — the
    dirty fan-out, a primitive category — the routing is organization grain.

    Parsed to real UUIDs rather than left as strings: `source_ref` is an opaque
    CharField, and Postgres will not compare one against a `uuid` column. The
    source of an INFORMS link is always a structure, so every ref here parses —
    a failure means a link was written with the wrong kind, which is worth
    hearing about rather than skipping.
    """
    import uuid as uuid_module

    refs = selector_module.informs_links_for(graph, definition=definition).filter(target_ref__in=_refs(claim_ref)).values_list("source_ref", flat=True).distinct()
    structure_ids = [uuid_module.UUID(str(ref)) for ref in refs]
    if not structure_ids:
        return []
    # Datums that stand (RFC 0023): a retracted structure informs nothing.
    from evidence import claims as claims_module

    return list(claims_module.standing(evidence_models.Structure.objects.for_organization(graph.organization).filter(pk__in=structure_ids), "structure").values_list("pk", flat=True))


def _priority_scoped_value(
    graph: core_models.Graph,
    claim_ref: str | Iterable[str],
    source_kind: evidence_models.StructureKind,
    key: str,
    value_kinds: Iterable[str],
    prop: PropertyDefinitionInput,
    category: core_models.Category,
) -> JSONValue:
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

    structure_ids = _structure_ids_informing(graph, claim_ref, category.definition)
    if not structure_ids:
        return None

    # `value_kind__in` rather than the state grain: this path never reads State,
    # so it has to apply the same narrowing itself or it would rank a STRING
    # measurement against a FLOAT one under the same key. The metric scope is
    # the property's own rule — `rule.evidence` when present, else the owning
    # category's clauses (RFC 0009) — so an excluded source cannot win even
    # when `subject_priority` ranks it first.
    metric_q, standing_predicate = selector_module.metric_scope(category.definition, rule)
    base = claims_module.standing(
        evidence_models.Metric.objects.for_organization(graph.organization).filter(
            metric_q,
            structure_id__in=structure_ids,
            structure__kind=source_kind,
            key=key,
            value_kind__in=list(value_kinds),
        ),
        "metric",
        predicate=standing_predicate,
    )

    for source in ordering:
        latest = base.filter(**{field: source}).order_by("-observed_at").first()
        if latest is not None:
            return latest.value

    if ordering:
        return None

    latest = base.order_by("-observed_at").first()
    return latest.value if latest else None


def _structure_kind_for_rule(graph: core_models.Graph, rule: DerivationRuleInput) -> evidence_models.StructureKind | None:
    """Resolve a rule's `source_node` to one of the organization's structure kinds.

    Identifier only. The old lookup also fell back to `key`, which a structure
    kind does not have — an organization's vocabulary of external data types is
    keyed by the identifier the producing service owns.
    """
    if not rule or not rule.source_node:
        return None
    return evidence_models.StructureKind.objects.for_organization(graph.organization).filter(identifier=rule.source_node).first()


def _value_kinds_for_rule(graph: core_models.Graph, source_kind: evidence_models.StructureKind, key: str, rule: DerivationRuleInput) -> frozenset[str] | None:
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
    claim_ref: str | Iterable[str],
    category: core_models.Category,
) -> dict[str, JSONValue]:
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
    statistics: dict[str, JSONValue] = {}

    for prop in _derived_properties(category):
        rule = prop.rule
        source_kind = _structure_kind_for_rule(graph, rule)
        if source_kind is None:
            continue

        key = rule.key if rule and rule.key else prop.key
        value_kinds = _value_kinds_for_rule(graph, source_kind, key, rule)
        if value_kinds is None:
            continue

        state = _scoped_state(graph, claim_ref, source_kind, key, value_kinds, category, prop) if _rule_constrains(category, prop) else state_module.state_for_many(graph.organization, _refs(claim_ref), source_kind, key, value_kinds)
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
    claim_ref: str | Iterable[str],
    category: core_models.Category,
) -> dict[str, JSONValue]:
    """Compute one individual's derived properties from its members' state vectors.

    `claim_ref` is one instance ref or the whole member list of a drawn
    individual (RFC 0018); the cached path combines one `State` row per member
    (`state.combine` is the monoid this was always meant for), the rule-bound
    path widens its metric filter the same way.

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
    values: dict[str, JSONValue] = {}

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
            value = _priority_scoped_value(graph, claim_ref, source_kind, key, value_kinds, prop, category)
        else:
            state = _scoped_state(graph, claim_ref, source_kind, key, value_kinds, category, prop) if _rule_constrains(category, prop) else state_module.state_for_many(organization, _refs(claim_ref), source_kind, key, value_kinds)

            aggregation = rule.aggregation if rule and rule.aggregation else None
            if prop.derivation == DerivationType.LATEST and aggregation is None:
                from graph_engine.input_models import AggregationFunction

                aggregation = AggregationFunction.LATEST

            value = aggregate.apply(aggregation, state) if aggregation else None

        # Written even when there is no value. A property whose evidence has
        # stopped supporting it — its datum retracted, its metrics withdrawn —
        # must clear the number the vertex carried, not keep it: `write_properties`
        # merges keys, so skipping the key here left a value no surviving
        # evidence supported on the drawing (RFC 0023).
        values[prop.key] = value

    return values


def _rule_constrains(category: core_models.Category, prop: PropertyDefinitionInput) -> bool:
    """Whether this property's fold must bypass the cached org-grain vector.

    True when the property carries its own `rule.evidence`, or the owning
    category's clauses constrain trust. A primitive category with a plain rule
    reads the stored `State` row — the fast path, and the common case. Without
    this, a rule filter on an unconstrained category would be silently inert —
    the class of silence this codebase refuses.
    """
    if getattr(prop.rule, "evidence", None) is not None:
        return True
    return selector_module.trust_predicate(category.definition, kind="MEASUREMENT") is not None


def _scoped_state(
    graph: core_models.Graph,
    claim_ref: str | Iterable[str],
    source_kind: evidence_models.StructureKind,
    key: str,
    value_kinds: Iterable[str],
    category: core_models.Category,
    prop: PropertyDefinitionInput,
) -> evidence_models.State | None:
    """Fold this entity's metrics under the property's rule, without storing it.

    The read-time half of the decision that `State` is organization grain. The
    stored vector counts every live metric, which is the right answer when
    nothing narrows — a primitive category with no `rule.evidence`, the common
    case. A property that counts less cannot share that row, and storing a
    second one per rule is what would put a graph foreign key into `evidence/`
    — the one thing that app may not grow.

    So it pays for the narrowing on read instead: the metrics directly, folded
    into an unsaved vector, under `metric_scope(category.definition, rule)` —
    the property's own evidence filter when it has one, the category's clauses
    otherwise (RFC 0009). The same trade `_priority_scoped_value` makes.
    """
    rule = prop.rule
    structure_ids = _structure_ids_informing(graph, claim_ref, category.definition)
    if not structure_ids:
        return None

    metric_q, standing_predicate = selector_module.metric_scope(category.definition, rule)
    metrics = claims_module.standing(
        evidence_models.Metric.objects.for_organization(graph.organization).filter(
            metric_q,
            structure_id__in=structure_ids,
            structure__kind=source_kind,
            key=key,
            value_kind__in=list(value_kinds),
        ),
        "metric",
        predicate=standing_predicate,
    )

    # `value_kind` is set only to keep the unsaved row well-formed, and it is
    # arbitrary when the family widens (INT and FLOAT fold together, and
    # `value_kinds` is a frozenset). That is safe because nothing reads it here:
    # `aggregate.apply` takes the `StateVector` protocol, which does not include
    # the field. This row is never saved, so no grain depends on it either. If an
    # aggregation ever needs the kind, give it the whole set rather than one.
    vector = evidence_models.State(
        organization=graph.organization,
        claim_ref=min(_refs(claim_ref)),
        source_kind=source_kind,
        key=key,
        value_kind=next(iter(sorted(value_kinds)), ""),
    )
    return state_module.fold(metrics, vector)


def _observation_window(graph: core_models.Graph, claim_ref: str | Iterable[str], category: core_models.Category) -> dict[str, JSONValue]:
    """When the evidence behind this node was observed.

    `valid_from` and `valid_to` are read by six GraphQL fields that have always
    returned null, because nothing ever wrote them. They are the observation
    window of the contributing measurements — `observed_at`, not `asserted_at`:
    a node is valid over the period the world was actually looked at, regardless
    of when somebody got round to saying so.
    """
    from django.db.models import Max, Min

    from evidence import models as evidence_models

    structure_ids = _structure_ids_informing(graph, claim_ref, category.definition)
    if not structure_ids:
        return {"valid_from": None, "valid_to": None}

    # Under the category's clauses, like every other metric read (RFC 0009): a
    # window stretched by a measurement whose assertion the node's category
    # does not trust was the same leak `_priority_scoped_value` had. This is
    # node-grain, so it takes the category default and deliberately **not** any
    # property's `rule.evidence` — the per-property windows are the
    # `__stat__X__from/to` statistics, which inherit the rule in
    # `_property_statistics`.
    trust = selector_module.trust_filter(category.definition, kind="MEASUREMENT", asserted_at_column="asserted_at", include_metric_fields=True)
    window = claims_module.standing(
        evidence_models.Metric.objects.for_organization(graph.organization).filter(
            trust,
            structure_id__in=structure_ids,
        ),
        "metric",
        predicate=selector_module.trust_predicate(category.definition, kind="MEASUREMENT"),
    ).aggregate(earliest=Min("observed_at"), latest=Max("observed_at"))

    return {
        "valid_from": window["earliest"].isoformat() if window["earliest"] else None,
        "valid_to": window["latest"].isoformat() if window["latest"] else None,
    }


def _widen_window(left: dict[str, JSONValue], right: dict[str, JSONValue]) -> dict[str, JSONValue]:
    """The observation window over two categories' evidence: earliest from, latest to (RFC 0019).

    ISO strings compare as timestamps — `_observation_window` renders them in
    one format — and `None` (no bounded evidence) never narrows the other side.
    """
    if not left:
        return dict(right)
    if not right:
        return dict(left)
    froms = [value for value in (left.get("valid_from"), right.get("valid_from")) if value is not None]
    tos = [value for value in (left.get("valid_to"), right.get("valid_to")) if value is not None]
    return {"valid_from": min(froms) if froms else None, "valid_to": max(tos) if tos else None}


def project(
    controller: DrawingHost,
    graph: core_models.Graph,
    instance_refs: Iterable[str],
) -> int:
    """Write derived properties onto the individuals holding the named instances. Returns how many vertices were written.

    Batched deliberately: one call handles a whole dirty set, so a bulk ingest of
    a thousand metrics against one structure triggers a single projection pass
    rather than a thousand. The old design re-derived per fact, which is the
    O(N x P) regression `test_bulk_ingest` guards against.

    Folded **per vertex, over its members** (RFC 0018). The refs name instances;
    the vertex holding each is looked up in the drawing and every property is
    derived over the whole member list — an ROI informing either observation of
    one individual informs the individual. Two refs held by one vertex are one
    fold and one write, and a ref the drawing does not hold is reported as
    behind, exactly as an undrawn instance always was.
    """
    projected = 0

    # The graph's active schema is the version that derived these values.
    # `NodeCategory.schema_hash` hashes one category's properties, which is a
    # different question and cannot identify the schema a value came from.
    active_schema = core_models.GraphSchema.active_for(graph)
    schema_version = active_schema.hash if active_schema else None

    refs = [str(ref) for ref in instance_refs]
    nodes = list(evidence_models.Instance.objects.for_organization(graph.organization).filter(id__in=refs))
    # Which categories a node projects under is this graph's question to answer,
    # and the properties are theirs. Resolved once for the batch rather than per
    # node.
    resolved, _ = resolve_categories(graph, nodes)

    # The grouping is the drawing's: which vertex holds each ref, and what else
    # it holds. `create_vertex` decided that from the claims a moment before
    # this runs, and a fold that grouped differently from the vertex it writes
    # onto would report one individual's values under another's id.
    records = controller.projector.drawn_nodes(graph, refs)
    written: set[str] = set()

    for claim_ref in refs:
        categories = resolved.get(claim_ref)
        if not categories:
            # Either no such node, or no category in this graph admits it. Either
            # way there is no vertex to write onto.
            continue
        labels = sorted(category.age_name for category in categories)

        record = records.get(claim_ref)
        if record is None:
            # The node has a `Instance` row and a category this graph admits, but no
            # vertex — the projection is behind the log. `reproject` is the fix;
            # counting it as projected would hide that it is needed.
            logger.warning(
                "%s: no vertex labelled %s to write onto; the projection is behind the evidence. Run `manage.py reproject --graph %s`.",
                claim_ref,
                ", ".join(labels),
                graph.pk,
            )
            continue

        if sorted(record.labels) != labels:
            # Drawn, but not under what the claims now admit: a label the view
            # gained or lost since the vertex was drawn. The values below are
            # the categories' union either way, but a reader of the drawing sees
            # the old label set, and `reproject` is what fixes that.
            logger.warning(
                "%s: drawn under %s, but its categories are %s; the projection is behind the evidence. Run `manage.py reproject --graph %s`.",
                claim_ref,
                ", ".join(sorted(record.labels)),
                ", ".join(labels),
                graph.pk,
            )

        representative = str(record.properties["id"])
        if representative in written:
            continue
        members = list(record.members) or [claim_ref]

        # **Every** derived property, not just the filterable ones. A read is a
        # graph query: whatever a client can ask for is on the vertex before the
        # query runs. The old split wrote only `index=True` properties and left
        # the rest to `api/types._derive_unindexed`, which folded state per node
        # on every read — and since `index` defaults to False, that was almost
        # all of them.
        # The union over the node's categories (RFC 0019). `resolve_categories`
        # has refused any pair that defines one key differently, so the union
        # is a union of disjoint keys, plus keys the pair defines identically.
        values: dict[str, JSONValue] = {}
        window: dict[str, JSONValue] = {}
        for category in categories:
            values.update(derive_properties(graph, members, category))
            values.update(_property_statistics(graph, members, category))
            window = _widen_window(window, _observation_window(graph, members, category))
        values.update(window)
        values["__schema_version"] = schema_version
        # No `__last_derived` any more. It was a wall-clock millisecond on every
        # vertex — the one projected value `reproject` could not reproduce, so the
        # rebuild tests excluded it by hand — and it answered a per-graph question
        # per node. "When was this view last derived" is `Projection.derived_at`,
        # stamped once per call below.

        if not _write_properties(controller, graph, representative, values):
            logger.warning(
                "%s: no vertex labelled %s to write onto; the projection is behind the evidence. Run `manage.py reproject --graph %s`.",
                claim_ref,
                ", ".join(labels),
                graph.pk,
            )
            continue

        written.add(representative)
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
def proposition_key(link: evidence_models.Link, canon: Mapping[str, str] | None = None) -> tuple[str, str, uuid.UUID | None]:
    """What makes two relation assertions claims about the same edge.

    The two endpoints and the *word* — not a graph's category for it. Two views
    that both declare "IS_CONNECTED_TO" are looking at one proposition, and each
    draws it under its own label.

    ``canon`` maps a member ref to its individual's representative in one view
    (RFC 0018): two claims naming two observations of one cell are one edge
    there, and its `__assertion_count` is the sum. Without it — the no-view
    answer — the endpoints are the instances themselves."""
    canon = canon or {}
    source, target = str(link.source_ref), str(link.target_ref)
    return (canon.get(source, source), canon.get(target, target), link.term_id)


def representatives_for(controller: DrawingHost, graph: core_models.Graph, refs: Iterable[str]) -> dict[str, str]:
    """Member ref → the representative of the individual this view draws it as.

    Asked of the drawing — the one legitimate cache read on the write path,
    because the question is "which vertex do I attach this edge to", and an edge
    can only attach to a vertex that exists. Nodes converge before edges
    (`converge`, and `_members_drawn_as` on the correction paths), so by the
    time this is asked the vertex is the one the rule describes. A ref the view
    has not drawn maps to nothing, and its caller falls back to the ref itself —
    which then fails to match an endpoint, exactly as an undrawn node always did.
    """
    records = controller.projector.drawn_nodes(graph, {str(ref) for ref in refs})
    return {ref: str(record.properties["id"]) for ref, record in records.items()}


def _admitted_by(categories: Iterable[core_models.Category], base: QuerySet[evidence_models.Link]) -> dict[int, list[evidence_models.Link]]:
    """Each category → the standing claims from `base` it admits, under its own rule.

    The one implementation of "which claims draw this category's edges" (RFC 0009):
    a defined category admits the claims its classification filter matches and
    folds their standings under its trust; a primitive category admits every
    claim naming its word, standings organization grain. `active_relation_links`,
    `active_participation_links`, `project_edges`, `project_participation`, the
    correction paths and the API's edge lists all read through here, so none of
    them can disagree about which claims exist.
    """
    admitted: dict[int, list[evidence_models.Link]] = {}
    for category in categories:
        if category.definition:
            claims = base.filter(selector_module.classification_filter(category.definition), term__kind=str(category.kind))
            predicate = selector_module.trust_predicate(category.definition, kind="EXISTENCE")
        else:
            claims = base.filter(term_id=category.term_id)
            predicate = None
        admitted[category] = list(claims_module.standing(claims, "link", predicate=predicate).select_related("term"))
    return admitted


def admitting_categories(categories: Iterable[core_models.Category], base: QuerySet[evidence_models.Link]) -> dict[uuid.UUID, tuple[evidence_models.Link, list[core_models.Category]]]:
    """Link pk → `(link, every category admitting it)`, over `base`.

    A claim is drawn under **every** category that admits it — edges included
    (RFC 0021). Two defined relation categories deriving from one word each get
    their edge; a claim no category admits is absent here, which is the ordinary
    "this view does not speak that word" and not an error.
    """
    out: dict[uuid.UUID, tuple[evidence_models.Link, list[core_models.Category]]] = {}
    for category, links in _admitted_by(categories, base).items():
        for link in links:
            out.setdefault(link.pk, (link, []))[1].append(category)
    return out


def relation_categories(graph: core_models.Graph) -> list[core_models.RelationCategory]:
    """This view's relation categories that declare a word."""
    return list(core_models.RelationCategory.objects.filter(graph=graph, term_id__isnull=False))


def event_categories(graph: core_models.Graph) -> list[core_models.Category]:
    """This view's event categories that declare a word, both kinds."""
    return list(core_models.NaturalEventCategory.objects.filter(graph=graph, term_id__isnull=False)) + list(core_models.ProtocolEventCategory.objects.filter(graph=graph, term_id__isnull=False))


def categories_drawing(graph: core_models.Graph, kind: str) -> list[core_models.Category]:
    """The categories of this view that can draw a link of `kind`."""
    if kind == evidence_models.Link.Kind.RELATION:
        return relation_categories(graph)
    if kind in PARTICIPATION_KINDS:
        return event_categories(graph)
    return list(core_models.Category.objects.filter(graph=graph, term_id__isnull=False))


def active_relation_links(graph: core_models.Graph) -> list[evidence_models.Link]:
    """Every live relation claim this graph projects — admitted by at least one of
    its relation categories, under that category's rule (RFC 0009)."""
    base = evidence_models.Link.objects.for_organization(graph.organization).filter(kind=evidence_models.Link.Kind.RELATION)
    return [link for link, _ in admitting_categories(relation_categories(graph), base).values()]


def project_edges(
    controller: DrawingHost,
    graph: core_models.Graph,
    links: Iterable[evidence_models.Link],
) -> int:
    """Draw relation edges from their claims — under every category that admits each.

    Shared by `create_relation`, the correction paths and `rebuild` so that the
    edge a fresh assertion produces and the edge a replay produces cannot drift
    apart — the failure this whole layer exists to prevent.

    An upsert keyed on `(source, target, label)`: replaying twice must not double
    an edge, and a second assertion of the same relation must land on the one
    already there. Endpoints are canonicalised to the individuals this view draws
    (RFC 0018) before grouping, so claims naming different observations of one
    cell fold into one edge with one summed `__assertion_count`. A relation
    between two members of one individual is a self-edge — it is what the claims
    say.

    One edge per admitting **category** (RFC 0021), not per word: two relation
    categories that both derive from a claim's word each draw their own edge,
    the way a node carries every admitting category's label. Which categories
    admit a claim is asked of `admitting_categories`, never of a term→category
    map — that map could only ever answer for one of them.
    """
    links = list(links)
    if not links:
        return 0

    base = evidence_models.Link.objects.for_organization(graph.organization).filter(kind=evidence_models.Link.Kind.RELATION, pk__in=[link.pk for link in links])
    admitted = admitting_categories(relation_categories(graph), base)
    for link in links:
        if link.pk not in admitted:
            # Either the claim names no word this graph speaks, or every category
            # that speaks it refuses this claim under its rule — so there is no
            # label to draw it under, and an unlabelled edge is unreachable by
            # every query the schema generates.
            logger.warning("Relation link %s is admitted by no relation category of graph #%s; it cannot be projected here.", link.pk, graph.pk)

    canon = representatives_for(controller, graph, [ref for link, _ in admitted.values() for ref in (link.source_ref, link.target_ref)])
    grouped: dict[tuple[str, str, uuid.UUID | None], tuple[core_models.Category, list[evidence_models.Link]]] = {}
    for link, categories in admitted.values():
        source_ref, target_ref, _ = proposition_key(link, canon)
        for category in categories:
            grouped.setdefault((source_ref, target_ref, category.pk), (category, []))[1].append(link)

    projected = 0
    for (source_ref, target_ref, _), (category, assertions) in grouped.items():
        # Converging on `(source, target, label)`; `__assertion_count` is the
        # edge-side analogue of `State.n` — how many live claims stand behind this
        # edge, one number that says whether a relation rests on one annotator or
        # on four independent ones.
        drawn = controller.projector.draw_edge(
            graph,
            str(source_ref),
            str(target_ref),
            category.age_name,
            {"category_id": category.pk, "__assertion_count": len(assertions)},
        )

        # An unmatched endpoint draws nothing. This used to count regardless,
        # which made the number a claim about how many edges were written that
        # nothing checked — and once a node can leave the projection while its
        # `Link` rightly survives, that is a normal occurrence rather than an
        # impossible one.
        if not drawn:
            logger.warning(
                "Relation %s -> %s (%s): one or both endpoints are not in this projection, so no edge was drawn.",
                source_ref,
                target_ref,
                category.age_name,
            )
            continue

        projected += 1

    return projected


def property_conflicts(categories: Iterable[core_models.Category]) -> dict[frozenset[int], str]:
    """Which pairs of categories cannot draw one node together, and why (RFC 0019).

    A node drawn under two categories carries the union of their properties, so
    a key both define has to mean one thing. It does when the two property
    definitions are equal **and** the two categories' `definition`s are equal:
    a property's value is a fold — which structures inform it, whose metrics it
    counts — and the category's rule is part of that fold, so two categories
    with the same `avg_length` rule but different trust would derive two
    different numbers for one key. Keyed by the unordered pair of category
    pks; a pair with no entry may share a node.
    """
    conflicts: dict[frozenset[int], str] = {}
    listed = [(category, category.property_map) for category in categories]
    for index, (left, left_props) in enumerate(listed):
        for right, right_props in listed[index + 1 :]:
            for key in sorted(set(left_props) & set(right_props)):
                same_property = left_props[key].model_dump() == right_props[key].model_dump()
                same_rule = (left.definition or None) == (right.definition or None)
                if same_property and same_rule:
                    continue
                first, second = sorted((left.key, right.key))
                conflicts[frozenset((left.pk, right.pk))] = f"property {key!r} is defined by both {first} and {second} and would not mean one thing on one vertex"
                break
    return conflicts


def resolve_categories(graph: core_models.Graph, nodes: list[evidence_models.Instance]) -> tuple[dict[str, list[core_models.Category]], dict[str, str]]:
    """Which categories each node projects under, and why some project under none.

    Returns `(ref -> categories, ref -> reason)`. A ref appears in exactly one of
    the two, and every list is non-empty, sorted by category pk.

    This is what makes a category's meaning a property of the *graph* rather than
    of the entity. A category with an empty `definition` is **primitive**:
    membership is whatever was asserted under its word, which is the old
    behaviour and stays the default. A category carrying a definition is
    **defined** — necessary and sufficient conditions over classification claims
    — so the same node can be an `AIS` in one graph and an `AISproximal` in
    another with no evidence rewritten.

    **A node is drawn under every category that admits it** (RFC 0019). The
    categories are a union: every defined category whose definition matches,
    and every primitive category declaring a word a standing classification
    names (its own term, when nothing classifies it). A view that declares Pyramidal and
    Excitatory draws a cell that is both once, under both; a view that declares
    AIS primitively beside a defined AISproximal draws an AIS the definition
    admits under both too, because "anything claimed AIS" is what a primitive
    category means. There is no ordering between defined and primitive and no
    refusal for matching two definitions — one vertex has room for every label,
    which the table projection always had (Apache AGE happened to allow one
    label per vertex, and the old one-category rule was that limit dressed as
    policy).

    Three refusals remain, all deliberate:

    - **The claims say it does not exist — under every category.** Existence
      folds *per category* (RFC 0009 and 0019): each category is what says whose
      retractions count for its nodes, so a retraction somebody one category
      trusts and another does not removes the first label and keeps the second.
      A node with no label left is not in the view — there is no such thing as
      a node that is present but flagged.
    - **No category admits it** — the node is not in the view. A graph is a
      selection; a node satisfying nothing in it does not belong to it. The
      caller reports the count, because a definition silently shrinking a graph
      is the class of silence this codebase treats as a defect.
    - **Two of its categories define one property differently**
      (:func:`property_conflicts`). One vertex carries one value per key, and
      choosing which category's fold to write would bury the disagreement, so
      the node is refused with a reason naming the key and both categories.
      Identical definitions under identical rules are fine.
    """
    from evidence import claims as claims_module
    from evidence import selector as selector_module

    # This graph's categories, indexed by the organization term each declares.
    # That index is the whole join: a claim names a word, and this is where the
    # word becomes *this view's* rule for it.
    categories = list(core_models.Category.objects.filter(graph=graph).select_related("term"))
    defined = [category for category in categories if category.definition]
    by_term = {category.term_id: category for category in categories}

    # The unfolded claim base, built once. A defined category folds the claims
    # *and their standings* under its own clauses; a primitive category folds
    # standing organization-grain — the old unscoped behaviour.
    claim_base = selector_module.classification_claims(graph)
    standing_claims = claims_module.standing(claim_base, "link")

    claims_by_ref: dict[str, list[evidence_models.Link]] = {}
    for claim in standing_claims:
        claims_by_ref.setdefault(str(claim.source_ref), []).append(claim)

    # Evaluate each definition once against the whole claim set rather than once
    # per node: a definition is a queryset predicate, so asking it N times would
    # be N queries to answer one question.
    # Matched on the word's **kind** as well as its key. A `Term` is identified by
    # `(organization, kind, key)` and a definition sits on a category of one kind,
    # so "anything claimed Mitosis" on an *entity* category means the entity word
    # Mitosis, not the natural-event word that happens to share the key — matching
    # on the key alone let an entity definition admit events.
    # Standing folds under *this category's* trust (RFC 0009): a classification
    # retracted by somebody the category does not count still admits here.
    matched_by_definition: dict[int, set[str]] = {}
    for category in defined:
        matched = claims_module.standing(
            claim_base.filter(selector_module.classification_filter(category.definition), term__kind=str(category.kind)),
            "link",
            predicate=selector_module.trust_predicate(category.definition, kind="CLASSIFICATION"),
        )
        matched_by_definition[category.pk] = {str(ref) for ref in matched.values_list("source_ref", flat=True)}

    by_pk = {category.pk: category for category in categories}
    conflicts = property_conflicts(categories)
    resolved: dict[str, list[core_models.Category]] = {}
    skipped: dict[str, str] = {}

    for node in nodes:
        ref = str(node.ref)

        admitted: dict[int, core_models.Category] = {}
        for pk, refs in matched_by_definition.items():
            if ref in refs:
                admitted[pk] = by_pk[pk]

        # A *primitive* category this graph declares for a word the node was
        # claimed under — a graph with no definitions at all therefore behaves
        # exactly as it did before any of this existed. The word the node was
        # minted under (`Instance.term`) is what it falls back on only when
        # **no** classification of it stands: a node whose every claim is
        # retracted is not thereby a node under a word nobody claims, but a
        # node nothing has classified needs a word to be drawn at all.
        claims = claims_by_ref.get(ref, [])
        for claim in claims:
            category = by_term.get(claim.term_id)
            if category is not None and not category.definition:
                admitted[category.pk] = category
        own = by_term.get(node.term_id)
        if not claims and own is not None and not own.definition:
            admitted[own.pk] = own

        if not admitted:
            skipped[ref] = "no category in this graph admits it: every term it was asserted as is defined, and none of those definitions match"
            continue

        conflict = next((conflicts[pair] for pair in (frozenset(pks) for pks in combinations(sorted(admitted), 2)) if pair in conflicts), None)
        if conflict is not None:
            # Reported, not logged. This is read by the *read* paths too
            # (`refs_admitted_by`), and a warning here would fire on every list
            # query for as long as the conflict existed — the same line
            # `project_all` already emits at rebuild. Whoever can act on it does
            # the logging.
            skipped[ref] = f"drawn under categories that disagree: {conflict}"
            continue

        resolved[ref] = [admitted[pk] for pk in sorted(admitted)]

    # Existence last, per category, in bulk per category (RFC 0009): the
    # category is what says whose retractions count for its nodes, so it has to
    # be known before the fold. One query per category rather than per node — a
    # rebuild resolves every node in the graph. A retraction one category counts
    # takes that category's label and leaves the others (RFC 0019).
    refs_by_category: dict[int, list[str]] = {}
    for ref, admitted_categories in resolved.items():
        for category in admitted_categories:
            refs_by_category.setdefault(category.pk, []).append(ref)

    for category_pk, refs in refs_by_category.items():
        category = by_pk[category_pk]
        retracted = claims_module.retracted_ids(
            graph.organization,
            "node",
            refs,
            # Over `Standing` rows: world time is the standing's own `at`.
            selector_module.trust_filter(category.definition, kind="EXISTENCE", observed_at_column="at"),
        )
        for ref in retracted:
            remaining = [category for category in resolved.get(ref, []) if category.pk != category_pk]
            if remaining:
                resolved[ref] = remaining
            else:
                resolved.pop(ref, None)
                skipped[ref] = "the claims this node's categories count say it does not exist"

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

    # Every written rule names its words (RFC 0010 refuses one that does not),
    # so the wordless-matches-everything branch is gone with the clause shape.
    asserted_as = selector_module.asserted_as_keys(category.definition) if category.definition else []
    if asserted_as:
        claimed = standing_claims.filter(term__key__in=asserted_as)
    else:
        claimed = standing_claims.filter(term_id=category.term_id)
    claimed_refs = {str(ref) for ref in claimed.values_list("source_ref", flat=True)}

    candidates = list(selector_module.instances_for(graph).filter(Q(term_id=category.term_id) | Q(id__in=claimed_refs)).select_related("term"))
    resolved, _ = resolve_categories(graph, candidates)

    # A node counts in every category it holds (RFC 0019).
    return {ref for ref, drawn_as in resolved.items() if any(drawn.pk == category.pk for drawn in drawn_as)}


def representatives_admitted_by(category: core_models.Category) -> set[str]:
    """Every individual this category draws, by representative (RFC 0018).

    :func:`refs_admitted_by` folded once more through the view's sameness
    (`identity.component_refs_for_view`) — the same fold `project_all` draws
    with — so `entities(category:)` lists one row per individual rather than one
    per observation. Folded through the frontier walk rather than
    `view_components` over this category's refs alone: a member may hold this
    category and another, and a sameness claim the other one trusts joins it to
    an individual whose representative this category never admitted on its own
    (RFC 0019). The representative is the individual's, whichever of its
    categories the caller asked through.
    """
    from evidence import identity as identity_module

    admitted = refs_admitted_by(category)
    components = identity_module.component_refs_for_view(category.graph, sorted(admitted))
    return {min(str(member) for member in members) for members in components.values()}


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


def representatives_in_graph(graph: core_models.Graph) -> set[str]:
    """Every individual this graph holds, by representative (RFC 0018).

    :func:`refs_in_graph` folded through `identity.view_components`, so
    `nodes(graph:)` lists one row per individual. Same cost caveat as
    `refs_in_graph`: the whole view is resolved to answer for a page.
    """
    from evidence import identity as identity_module

    nodes = list(selector_module.instances_for(graph).select_related("term"))
    resolved, _ = resolve_categories(graph, nodes)
    return set(identity_module.view_components(graph, resolved))


def representative_in_graph(graph: core_models.Graph, ref: str) -> str:
    """The representative of the individual this view draws ``ref`` as.

    The lowest member of the ref's view-scoped component
    (`identity.component_refs_for_view`), the rule `create_vertex` draws by.
    A ref no sameness claim the view trusts touches is its own representative.
    Asked of the claims, not the drawing, so `node(id: <member>)` answers the
    same whether or not the projection has caught up.
    """
    from evidence import identity as identity_module

    members = identity_module.component_refs_for_view(graph, [str(ref)]).get(str(ref)) or [str(ref)]
    return min(str(member) for member in members)


#: The two participation kinds, and which way the projected edge points. An input
#: runs entity → event ("this cell went through mitosis"); an output runs event →
#: entity ("mitosis produced this cell"). Keeping the direction in the projection
#: rather than only in the kind is what lets a path query traverse a protocol in
#: the order it happened.
PARTICIPATION_KINDS = (
    evidence_models.Link.Kind.PARTICIPATES_AS_INPUT,
    evidence_models.Link.Kind.PARTICIPATES_AS_OUTPUT,
)


def edge_pattern_for(category: core_models.Category, link: evidence_models.Link) -> tuple[str, bool]:
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


def participation_key(link: evidence_models.Link, canon: Mapping[str, str] | None = None) -> tuple[str, str, str, uuid.UUID | None]:
    """What makes two participation claims claims about the same thing.

    The entity, the event, which side, and the role. Not the category: an event
    has exactly one, and folding it in would let a schema edit look like a
    different proposition. ``canon`` is the view's member → representative map,
    as in :func:`proposition_key`.
    """
    canon = canon or {}
    source, target = str(link.source_ref), str(link.target_ref)
    return (canon.get(source, source), canon.get(target, target), str(link.kind), link.role)


def active_participation_links(graph: core_models.Graph) -> list[evidence_models.Link]:
    """Every live participation claim this graph projects — admitted by at least
    one of its event categories, under that category's rule (RFC 0009)."""
    base = evidence_models.Link.objects.for_organization(graph.organization).filter(kind__in=PARTICIPATION_KINDS)
    return [link for link, _ in admitting_categories(event_categories(graph), base).values()]


def project_participation(
    controller: DrawingHost,
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
    links = list(links)
    if not links:
        return 0

    # Which event categories admit each claim (RFC 0021). The label is a constant
    # of the event *kind* (`AGE_INPUT_EDGE` / `AGE_OUTPUT_EDGE`), not of the
    # category, so every category admitting a claim draws the same edge — the
    # first names it, and the claims are grouped once per drawn edge.
    base = evidence_models.Link.objects.for_organization(graph.organization).filter(kind__in=PARTICIPATION_KINDS, pk__in=[link.pk for link in links])
    admitted = admitting_categories(event_categories(graph), base)
    for link in links:
        if link.pk not in admitted:
            logger.warning("Participation link %s is admitted by no event category of graph #%s; nothing says which edge label it projects to.", link.pk, graph.pk)

    projected = 0
    canon = representatives_for(controller, graph, [ref for link, _ in admitted.values() for ref in (link.source_ref, link.target_ref)])
    grouped: dict[tuple[str, str, str, uuid.UUID | None], tuple[core_models.Category, list[evidence_models.Link]]] = {}
    for link, categories in admitted.values():
        grouped.setdefault(participation_key(link, canon), (categories[0], []))[1].append(link)

    for (source_ref, target_ref, kind, role), (category, claims) in grouped.items():
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
        left, right = (entity_uuid, event_uuid) if is_input else (event_uuid, entity_uuid)

        # Participation is contestable like everything else: two people claiming
        # the same cell went into the same event are two rows and one edge, and
        # the count is what says whether the claim rests on one observer or several.
        drawn = controller.projector.draw_edge(
            graph,
            left,
            right,
            label,
            {"role": role, "category_id": category.pk, "__assertion_count": len(claims)},
        )

        # See `project_edges`: an endpoint not in this projection draws nothing,
        # so there is nothing to count.
        if not drawn:
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
    controller: DrawingHost,
    graph: core_models.Graph,
    claim_ref: str,
    values: dict[str, JSONValue],
) -> bool:
    """Set properties on the drawn vertex holding a durable instance ref.

    Matched by membership rather than by vertex id, because vertex ids do not
    survive a rebuild — which is the whole reason refs are keyed on the uuid.
    Any member of an individual addresses its vertex (RFC 0018).

    Returns whether a vertex was actually matched. A `SET` against nothing is a
    silent no-op in Cypher, so without this the caller cannot tell a written
    node from an absent one — and reports both as projected.
    """
    return controller.projector.write_properties(graph, str(claim_ref), values)


def create_vertex(controller: DrawingHost, graph: core_models.Graph, nodes: list[evidence_models.Instance], categories: Sequence[core_models.Category]) -> str:
    """Draw one individual into the projection: one vertex for these member instances.

    Shared by `rebuild` and `reproject_refs` so that a replayed vertex and a
    freshly re-attested one cannot differ — the same reason `project_edges` is
    shared between creating a relation and replaying one.

    ``nodes`` are the `Instance` rows of one view-scoped component
    (`identity.view_components`) — most often exactly one. The vertex's `ref`
    is the lowest member uuid, arrival-independent, the same rule the
    organization-grain identity cache uses; every member is written beside it so
    any of them addresses the vertex. Returns that representative.

    The vertex carries its identity, **what kind of thing it is**, and its
    labels — one per category in ``categories``, the union of what admitted its
    members (RFC 0019). Every other value on it is derived, and `project` is
    what derives them.

    ``type`` comes from `Instance.kind` — the claim's own account of what it is —
    rather than from the label, which is `category.age_name` and therefore this
    view's private rename of a word. Reading the kind off the label is what made
    every drawn event answer `__typename: Entity`: `RetrievedNode.node_type` fell
    back to matching "Cell" or "Mitosis" against a fixed vocabulary of five words
    it could never be one of. A node's kind is a fact about the claim, so the
    claim is where it is taken from — and it is written here so that a vertex is
    self-describing to any reader, which is what removes the fallback entirely.
    Members share at least one category, so they share a kind.
    """
    members = sorted(str(node.ref) for node in nodes)
    representative = members[0]
    by_pk = {category.pk: category for category in categories}
    labelled = [(category.age_name, category.pk) for _, category in sorted(by_pk.items())]
    # Converging: drawing an individual that is already drawn — `attest_node` on
    # a standing node, `project_all` over a populated namespace, an incremental
    # replay — leaves one vertex. One whose *label* or *membership* moved still
    # needs its old vertex cleared first; `reproject_refs` does that, `rebuild`
    # drops the namespace, and `project_all` relies on one of the two having
    # happened.
    controller.projector.draw_node(graph, representative, labelled, str(nodes[0].kind).upper(), members)
    return representative


def draw_components(controller: DrawingHost, graph: core_models.Graph, nodes: Iterable[evidence_models.Instance], resolved: Mapping[str, Sequence[core_models.Category]]) -> dict[str, list[str]]:
    """Draw every individual among the resolved nodes; returns representative → members.

    The one place the component fold meets the drawing: `identity.view_components`
    says which resolved nodes this view holds to be one thing, and each component
    becomes one `create_vertex`, labelled by the **union** of its members'
    categories (RFC 0019). Nodes `resolve_categories` skipped are not in
    `resolved`, so they are drawn nowhere and bridge nothing.
    """
    from evidence import identity as identity_module

    by_ref = {str(node.ref): node for node in nodes}
    components = identity_module.view_components(graph, resolved)
    for representative, members in components.items():
        categories = {category.pk: category for member in members for category in resolved[member]}
        create_vertex(controller, graph, [by_ref[member] for member in members], [categories[pk] for pk in sorted(categories)])
    return components


def unproject(controller: DrawingHost, graph: core_models.Graph, instance_refs: Iterable[str]) -> int:
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
    return controller.projector.erase_nodes(graph, [str(ref) for ref in instance_refs])


def reproject_refs(controller: DrawingHost, graph: core_models.Graph, refs: Iterable[str]) -> bool:
    """Draw these nodes back into the projection, individuals, edges and all.

    Everything `rebuild` would do for these nodes, using the same functions —
    if any of it were reattestation-specific, a re-attested node and a replayed
    one could differ, which is the class of failure this layer exists to prevent.
    The body is :func:`converge`, which widens the set to every individual the
    refs belong to (RFC 0018): re-attesting one observation redraws the whole
    thing it is an observation of, and a sameness claim redraws both sides'
    former individuals as one.

    Returns whether anything was drawn. It may not be: a node whose claims no
    longer place it in any of this graph's terms does not come back just because
    somebody says it exists, and `resolve_categories` is what decides that.
    """
    return converge(controller, graph, refs).nodes > 0


def project_all(controller: DrawingHost, graph: core_models.Graph) -> DrawCounts:
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

    # One vertex per individual (RFC 0018): the resolved nodes are folded into
    # components once, over the whole view, and each component is one draw.
    components = draw_components(controller, graph, nodes, resolved)

    # Edges after nodes: `MATCH (s) ... MATCH (t)` needs both endpoints to exist.
    edges = project_edges(controller, graph, active_relation_links(graph))
    participations = project_participation(controller, graph, active_participation_links(graph))

    projected = project(controller, graph, list(components))

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
    return DrawCounts(
        nodes=len(resolved),
        individuals=len(components),
        unclassified=len(skipped),
        edges=edges,
        participations=participations,
        projected=projected,
    )


def refs_drawn_as(graph: core_models.Graph, category: core_models.Category) -> list[str]:
    """The refs this graph currently draws under one category.

    Asked of `resolve_categories` rather than of a column, because which category
    a node takes is this graph's question — a `definition` can move a node between
    categories without anything on the node changing.
    """
    nodes = list(selector_module.instances_for(graph).select_related("term"))
    resolved, _ = resolve_categories(graph, nodes)
    return [ref for ref, categories in resolved.items() if any(drawn.pk == category.pk for drawn in categories)]


def rematerialize_category(
    controller: DrawingHost,
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
        controller.projector.clear_properties(graph, category.age_name, refs, owned)

    projected = project(controller, graph, refs)
    logger.info(
        "graph #%s: rematerialized '%s' — %d node(s), %d key(s) swept.",
        graph.pk,
        category.key,
        projected,
        len(owned),
    )
    return projected


def rebuild(controller: DrawingHost, graph: core_models.Graph) -> DrawCounts:
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

    # Under the organization's projection lock (`graph_engine/locks.py`): the
    # runner's `replay` and this must not interleave on one organization.
    with locks.organization_projection_lock(organization, wait=True):
        # Every cache the replay reads is refolded or checked **before** the replay
        # reads it, or the rebuild would only prove the projection can be rebuilt from
        # other caches. All organization-grain:
        #
        # - `CategoryAssertedTerm` — which words each definition derives from. It is
        #   what `selector.term_ids_for` reads to decide membership, so a stale row
        #   here silently changes which nodes the replay draws. Vocabulary-sized.
        # - `InstanceIdentity` — the SAME_AS components. A retraction only flags a
        #   component; the flagged ones are recomputed here.
        # - `CurrentStanding` — what every "which of these still count" narrowing reads.
        #
        # Four, with the metrics' fold below.
        asserted_terms.refold(organization)
        identity_module.recompute_stale(organization)
        claims_current = claims_module.refold_current(organization)
        # - `State` — the folded metrics an unconstrained property reads
        #   (`derive_properties` → `state_for_many`). This used to be refolded
        #   *after* the replay, so a rebuild derived every plain property from the
        #   cache it was about to rebuild: a metric whose `merge` never ran was
        #   missing from the drawing until the *next* rebuild.
        states = refold_state(organization)

        # The log position this replay is a picture of. Read before enumerating, so an
        # assertion that commits while the replay runs is either in the picture or
        # still in the outbox — never silently counted as applied.
        head = watermark.max_seq(organization)

        # Resolved once here purely to fail *before* the drop. A definition that
        # admits nothing has to raise
        # while the projection it would replace is still standing — the alternative is
        # an empty namespace and an exception, with nothing left to fall back on.
        # `project_all` resolves again after the drop; one redundant pass is the price
        # of the guarantee, and rebuild is the expensive operation either way.
        resolve_categories(graph, list(selector_module.instances_for(graph).select_related("term")))

        # Marked *before* the drop. A rebuild that dies between here and the end
        # leaves an empty namespace; `REBUILDING` makes the cursor report everything
        # as outstanding instead of "caught up" over nothing.
        watermark.mark_rebuilding(graph)

        controller.projector.drop_namespace(graph)
        controller.projector.refresh_namespace(graph)

        counts = project_all(controller, graph).with_refolds(claims=claims_current, states=states)

        watermark.mark_consistent(graph, through_seq=head, schema_hash=watermark.active_schema_hash(graph), rebuilt=True)
        return counts


def refold_state(organization: Organization) -> int:
    """Rebuild every state vector in the organization, from the metrics themselves.

    Deletes the existing rows first rather than merging over them: merging into a
    stale row would double-count, and the point of a rebuild is to depend on
    nothing that came before it.

    **Organization-wide, and no selector.** Two things were wrong with the
    per-graph version, and they were the same thing twice.

    It applied the view's scope to the metrics while `state.merge` — the
    incremental path — did not, so a rebuild and an ingest produced different
    rows from the same evidence. Worse, `recompute` did not apply it either and
    ran lazily on any row a retraction marked stale, so one retraction after a
    rebuild silently re-admitted out-of-scope metrics into a row that had just
    been made correct. State is organization grain now and nothing folds under a
    view-level scope, so there is no longer anything for the three writers to
    disagree about. Which metrics a *property* counts is answered at read time,
    in :func:`derive_properties` via `metric_scope` (RFC 0009).

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
        # first/last compare `observed_at` rather than trusting arrival. Two things
        # do care, and both were nondeterministic under `order_by("observed_at")`,
        # which has no tiebreak: `last_ts` uses `>=`, so metrics sharing an exact
        # observation time resolve to whichever was folded last; and
        # `high_water_assertion` is assigned unconditionally, so it ended up naming
        # an arbitrary assertion rather than the furthest one. `assertion.seq` is
        # arrival order, cannot tie, and makes the name true.
        # A metric reaches an individual through a datum, and only a datum that
        # stands informs anything (RFC 0023): the write path refolds without a
        # retracted structure's metrics (`state.refold` → `_structures_informing`),
        # and this fold has to agree with it. It used to filter the metric's own
        # standing only, so a rebuild fed every retracted datum back in.
        standing_metrics = claims_module.standing(evidence_models.Metric.objects.for_organization(organization), "metric")
        standing_structures = claims_module.standing(evidence_models.Structure.objects.for_organization(organization), "structure").values("pk")
        for metric in standing_metrics.filter(structure__in=standing_structures).select_related("structure", "structure__kind", "assertion").order_by("assertion__seq"):
            refs = refs_informed_by(organization, [metric.structure_id])
            if refs:
                state_module.merge(metric, refs)
                folded += 1

    return folded


def refold_stale(organization: Organization) -> int:
    """Rebuild every state row a retraction left stale. Returns how many were fixed.

    Lives here rather than in `evidence.state` because it is an operational sweep
    rather than part of the fold, and operators want it. `state.recompute_stale`
    was its previous home and had no production caller at all.
    """
    return state_module.recompute_stale(organization)


# ---------------------------------------------------------------------------
# Incremental replay: apply what the outbox says is owed.
# ---------------------------------------------------------------------------


def touched_refs(organization: Organization, assertion_ids: Iterable[uuid.UUID], since_seq: int | None = None) -> tuple[set[str], bool]:
    """Every node ref whose drawing one of these assertions could have changed.

    Returns ``(refs, saw_same_as)``. The closure is taken per claim table, each
    a single `assertion` join — the log's own shape — and every claim kind maps
    to the node(s) whose vertex, edges or derived properties it can move:

    - an `Instance` — itself;
    - a `Link` — its node endpoints by kind: RELATION, PARTICIPATES_*, SAME_AS and
      DIFFERENT_FROM on both sides; CLASSIFIES, INFORMS, MEASUREMENT on the node side only (the
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
    from evidence import identity as identity_module

    ids = list(assertion_ids)
    if not ids and since_seq is None:
        return set(), False

    predicate = Q(assertion_id__in=ids)
    if since_seq is not None:
        predicate |= Q(assertion__seq__gte=since_seq)

    refs: set[str] = set()
    saw_same_as = False

    refs.update(str(pk) for pk in evidence_models.Instance.objects.for_organization(organization).filter(predicate).values_list("id", flat=True))

    both = {evidence_models.Link.Kind.RELATION, evidence_models.Link.Kind.PARTICIPATES_AS_INPUT, evidence_models.Link.Kind.PARTICIPATES_AS_OUTPUT, *identity_module.IDENTITY_KINDS}
    source_side = {evidence_models.Link.Kind.CLASSIFIES}
    target_side = {evidence_models.Link.Kind.INFORMS, evidence_models.Link.Kind.MEASUREMENT}

    def _link_refs(links: Iterable[tuple[str, str, str]]) -> None:
        """The `(kind, source_ref, target_ref)` triples of a `values_list`, not `Link` rows — the query is narrowed to three columns on purpose."""
        nonlocal saw_same_as
        for kind, source_ref, target_ref in links:
            if kind in both:
                refs.add(str(source_ref))
                refs.add(str(target_ref))
                if kind in identity_module.IDENTITY_KINDS:
                    saw_same_as = True
            elif kind in source_side:
                refs.add(str(source_ref))
            elif kind in target_side:
                refs.add(str(target_ref))

    _link_refs(evidence_models.Link.objects.for_organization(organization).filter(predicate).values_list("kind", "source_ref", "target_ref"))

    structure_ids: set[uuid.UUID] = set(evidence_models.Structure.objects.for_organization(organization).filter(predicate).values_list("id", flat=True))
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


def converge(controller: DrawingHost, graph: core_models.Graph, refs: Iterable[str]) -> DrawCounts:
    """Make this graph's drawing of these nodes equal what a rebuild would draw.

    The body of `reproject_refs`; batched so the category resolution and the
    edge scans happen once for the set. Clear first, then redraw from the
    claims: a node the view no longer admits is erased, one whose label moved
    lands under the new one, and every edge touching the set is re-merged from
    the active links with its `__assertion_count` recomputed.

    **The set is widened to whole individuals first** (RFC 0018). A vertex
    stands for a component, so touching one member means redrawing the
    component: the touched refs grow to every member of every vertex currently
    holding one of them (the drawing's answer — what has to be erased) and to
    every ref the view's sameness claims now connect them to
    (`identity.component_refs_for_view` — what has to be drawn). Nothing outside
    the touched individuals moved: derived properties fold per individual over
    Postgres and read nothing from a neighbour, and an edge to a neighbour is
    redrawn from the claims because it touches the set.
    """
    from evidence import identity as identity_module

    touched = {str(ref) for ref in refs}
    if not touched:
        return DrawCounts()

    for record in controller.projector.drawn_nodes(graph, touched).values():
        touched.update(str(member) for member in record.members)
    for members in identity_module.component_refs_for_view(graph, list(touched)).values():
        touched.update(str(member) for member in members)

    nodes = list(evidence_models.Instance.objects.for_organization(graph.organization).filter(id__in=touched).select_related("term"))
    erased = unproject(controller, graph, touched)

    resolved, _ = resolve_categories(graph, nodes)
    components = draw_components(controller, graph, nodes, resolved)

    edges = project_edges(controller, graph, [link for link in active_relation_links(graph) if str(link.source_ref) in touched or str(link.target_ref) in touched])
    participations = project_participation(controller, graph, [link for link in active_participation_links(graph) if str(link.source_ref) in touched or str(link.target_ref) in touched])
    projected = project(controller, graph, list(components))

    return DrawCounts(nodes=len(resolved), individuals=len(components), edges=edges, participations=participations, projected=projected, erased=erased)


def replay(controller: DrawingHost, organization: Organization, *, older_than: datetime.timedelta | None = None) -> ReplayReport:
    """Apply every outstanding assertion of the organization to every consistent graph.

    The incremental counterpart of :func:`rebuild`. Organization-scoped by
    construction: an outbox row is organization-grain, and a CLASSIFIES claim can
    widen membership in any view, so there is no per-graph slice of "what is
    owed" to replay. Graphs that are `NEEDS_BACKFILL` or `REBUILDING` are skipped
    and named — they need a full `rebuild`, and a partial redraw of an undrawn
    graph would only make its lag dishonest.

    Settles **exactly** the outbox rows it read, by id, after applying them to
    every graph it processed. A row committed after the snapshot is left for the
    next replay; a row whose assertion has no claims (one `redact` emptied, or
    one an older writer recorded before the act became a single transaction) is
    settled with nothing to draw.
    """
    from django.utils import timezone

    from evidence import identity as identity_module
    from graph_engine import models as projection_models

    # `older_than` is the runner's grace: a row younger than that belongs to a
    # request that may still be drawing, and is left for the next pass. Rows
    # are still settled exactly as read.
    outstanding = projection_models.PendingProjection.objects.filter(organization=organization)
    if older_than is not None:
        outstanding = outstanding.filter(created_at__lt=timezone.now() - older_than)
    pending = list(outstanding.select_related("assertion"))
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
    processed: list[GraphReplay] = []
    skipped: list[SkippedGraph] = []

    for graph in graphs:
        row = rows.get(graph.pk) or watermark.projection_for(graph)
        if row.status != projection_models.Projection.Status.CONSISTENT:
            skipped.append(SkippedGraph(graph=graph, status=str(row.status)))
            continue
        counts = converge(controller, graph, refs)
        watermark.mark_consistent(graph, through_seq=head, schema_hash=row.schema_hash)
        processed.append(GraphReplay(graph=graph, counts=counts))

    settled = watermark.settle_many(pending_ids)

    return ReplayReport(
        pending=len(pending_ids),
        settled=settled,
        lowest_seq=lowest,
        head=head,
        refs=len(refs),
        graphs=tuple(processed),
        skipped=tuple(skipped),
    )
