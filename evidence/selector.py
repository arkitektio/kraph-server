"""Turning a view's rules into the evidence it projects.

A ``Graph`` is a view over its organization's evidence, and since RFC 0009 the
rules saying which part are **per category**: a category's ``definition`` — the
union of clauses RFC 0007 built — is the complete rule for its word, and a
derived property's ``rule.evidence`` is that property's own metric rule. There
is no graph-level selector any more; nothing here reads one.

Evaluating a rule produces a queryset, never a stored membership flag: writes
stay projection-agnostic, so ingesting a metric does not have to know about
every graph that might one day want it. That is what keeps bulk ingest O(N)
instead of O(N x projections).

One rule is a list of (field, operator, value) conditions (RFC 0010) — the same
triple-with-operator language the saved-query plans use. A claim counts if any
rule matches; a rule matches when all its ``when`` conditions hold and no
``unless`` group does; a group holds when all its conditions do::

    {"rules": [
        {"when": [
            {"field": "WORD",        "operator": "IS",     "value": "AIS"},
            {"field": "SUBJECT",     "operator": "IS",     "value": "peter"},
            {"field": "ASSERTED_AT", "operator": "BEFORE", "value": "2026-12-05T00:00:00Z"}
         ],
         "unless": [{"when": [{"field": "APP", "operator": "IS", "value": "sloppy-import"}]}]}
    ]}

Two readings of the same rules, and the split is the design:

- :func:`classification_filter` — the **whole** rule, WORD conditions included:
  which claims *mean* this category. Applied to CLASSIFIES claims, and (RFC
  0009) to a relation or event category's own link claims.
- :func:`trust_filter` — the who-and-when conditions, WORD ignored: whose
  claims and standings *count* for things already of this category. Applied to
  existence standings, the standings of link claims, INFORMS routing, and (by
  default) the metrics a property folds.
- :func:`rule_metric_filter` — a property's own ``rule.evidence``, the same
  rule list minus WORD and KIND, plus the two fields only a metric row has,
  KEY and MEASURED_AT (RFC 0014).

``as_of`` is the one that matters scientifically: "the category as we believed
it on March 3rd" stops being a fork of the data and becomes a filter.
"""

from __future__ import annotations

from typing import Any

from django.db.models import CharField, Q, QuerySet
from django.db.models.functions import Cast

from evidence import claims as claims_module
from evidence import models as evidence_models


def _parse_window(window: Any) -> tuple[Any, Any]:
    """A two-element window, tolerating either element being absent."""
    if not window:
        return None, None
    if isinstance(window, dict):
        return window.get("from"), window.get("to")
    if isinstance(window, (list, tuple)) and len(window) == 2:
        return window[0], window[1]
    raise ValueError(f"observed_window must be a [from, to] pair or a {{from, to}} object, got {window!r}")


#: How each identity field reaches the database, shared by every compiler below
#: so the readings of "whose claims count" cannot drift apart.
_IDENTITY_COLUMNS = {
    "SUBJECT": "assertion__subject",
    "APP": "assertion__app_id",
    "ACTION": "assertion__action_name",
    "KEY": "key",  # the metric key — only a metric row has one (RFC 0014)
}
#: Fields only a `Metric` row can answer. Skipped unless the caller says the
#: predicate targets metrics — a `Standing` or an `Instance` has neither.
_METRIC_ONLY_FIELDS = frozenset({"MEASURED_AT", "KEY"})

#: `ACTION` is the one nullable column: a human's claim carries no action, and
#: SQL's NOT IN over NULL would silently drop it — compiled around, below.
_NULLABLE_IDENTITY_FIELDS = frozenset({"ACTION"})


def _rules(definition: dict[str, Any] | None) -> list[dict[str, Any]]:
    """A definition as its list of rules — **the** single reader of the stored shape.

    Every consumer of a definition goes through this: the predicates
    (`classification_filter`, `trust_filter`) and the vocabulary
    (`asserted_as_keys`) walking the shape differently is exactly how a
    definition comes to match claims the graph cannot see. Non-dict entries are
    skipped; the pre-RFC-0010 clause shape is not read (cleared by
    `core/migrations/0017`).
    """
    if not definition:
        return []
    rules = definition.get("rules")
    if not isinstance(rules, list):
        return []
    return [rule for rule in rules if isinstance(rule, dict)]


def _conditions(container: dict[str, Any]) -> list[dict[str, Any]]:
    return [condition for condition in (container.get("when") or []) if isinstance(condition, dict)]


def _condition_q(condition: dict[str, Any], *, asserted_at_column: str) -> Q | None:
    """One (field, operator, value) condition as a predicate, or None to skip it.

    WORD is handled by the callers (`classification_filter` includes it,
    `trust_filter` skips it), so it returns None here. An unknown field or
    operator also returns None — read-side tolerance; the write path refuses
    both.
    """
    field = str(condition.get("field", ""))
    operator = str(condition.get("operator", ""))
    value = condition.get("value")

    if field in ("WORD", "KIND"):
        # Meta-conditions: WORD is the callers' business (`classification_filter`
        # includes it, `trust_filter` skips it), KIND decides which rules apply
        # at all (`rule_covers`) — neither is a database predicate.
        return None

    if field in _IDENTITY_COLUMNS:
        column = _IDENTITY_COLUMNS[field]
        values = [value] if isinstance(value, str) else list(value or [])
        if not values:
            return None
        if operator in ("IS", "IN"):
            return Q(**{f"{column}__in": values})
        if operator == "NOT_IN":
            negated = ~Q(**{f"{column}__in": values})
            if field in _NULLABLE_IDENTITY_FIELDS:
                # "Everyone except the bot" must keep claims with no action at
                # all: SQL NOT IN swallows NULL rows, so say the null case out
                # loud instead of inheriting it.
                negated |= Q(**{f"{column}__isnull": True})
            return negated
        return None

    if field == "ASSERTED_AT":
        column = asserted_at_column
    elif field == "MEASURED_AT":
        column = "measured_at"
    else:
        return None

    if operator == "BEFORE":
        return Q(**{f"{column}__lte": value})
    if operator == "SINCE":
        return Q(**{f"{column}__gte": value})
    return None


def _rule_trust_q(rule: dict[str, Any], *, asserted_at_column: str, include_metric_fields: bool = False) -> Q:
    """One rule's who-and-when predicate: AND of `when` (WORD skipped, the
    metric-only fields skipped unless the predicate targets metric rows),
    minus any `unless` group (each group an AND of its conditions)."""
    predicate = Q()
    for condition in _conditions(rule):
        if not include_metric_fields and str(condition.get("field")) in _METRIC_ONLY_FIELDS:
            continue
        compiled = _condition_q(condition, asserted_at_column=asserted_at_column)
        if compiled is not None:
            predicate &= compiled

    for group in rule.get("unless") or []:
        if not isinstance(group, dict):
            continue
        blocked = Q()
        for condition in _conditions(group):
            if not include_metric_fields and str(condition.get("field")) in _METRIC_ONLY_FIELDS:
                continue
            compiled = _condition_q(condition, asserted_at_column=asserted_at_column)
            if compiled is not None:
                blocked &= compiled
        if blocked.children:
            predicate &= ~blocked

    return predicate


def _rule_words(rule: dict[str, Any]) -> list[str]:
    """One rule's WORD-condition values, in order."""
    words: list[str] = []
    for condition in _conditions(rule):
        if str(condition.get("field")) != "WORD":
            continue
        value = condition.get("value")
        if isinstance(value, str):
            words.append(value)
        elif isinstance(value, list):
            words.extend(str(entry) for entry in value)
    return words


def trust_filter(definition: dict[str, Any] | None, *, kind: str, asserted_at_column: str = "assertion__asserted_at", include_metric_fields: bool = False) -> Q:
    """Whose claims of one **kind** count for things of this category.

    ``kind`` is required (a `ClaimKind` value — RFC 0011): only the rules whose
    KIND conditions do not exclude it apply, so "Peter decides what exists,
    only the curator may merge" is two rules in one list. Within an applicable
    rule the reading is the who-and-when one: WORD and KIND conditions are
    skipped (a word says which claims *mean* the category; KIND said which
    rules apply), `unless` groups subtract from their own rule.

    `Q()`-collapse edges, decided once: **no applicable rule for this kind**
    matches nothing — the explicit contradiction, never the collapsed `Q()`
    (strict grants: a kind carved out of every rule was carved out on purpose);
    an applicable rule with no who/when constraints matches everything. An
    empty definition — a *primitive* category — trusts everybody for every
    kind: the old unscoped behaviour, still the default.
    """
    from graph_engine.input_models import rule_covers

    if not definition:
        return Q()

    applicable = [rule for rule in _rules(definition) if rule_covers(rule, kind)]
    if not applicable:
        return Q(pk__in=[])

    predicates = [_rule_trust_q(rule, asserted_at_column=asserted_at_column, include_metric_fields=include_metric_fields) for rule in applicable]
    if any(not predicate.children for predicate in predicates):
        return Q()

    combined = predicates[0]
    for predicate in predicates[1:]:
        combined |= predicate
    return combined


def trust_predicate(definition: dict[str, Any] | None, *, kind: str) -> Q | None:
    """`trust_filter`, spelled for `claims.standing`: ``None`` when the
    definition constrains nobody for this kind, so an unscoped category takes
    the `CurrentStanding` fast path instead of folding the log per row."""
    predicate = trust_filter(definition, kind=kind)
    return predicate if predicate.children else None


def _evidence_rules(rule: Any) -> list[dict[str, Any]] | None:
    """A property's stored ``evidence`` rule list, or None when it has none.

    Accepts the pydantic `DerivationRuleInput` (a live request) or the dict
    `defined_properties` re-parses from `Category.property_definitions`.
    """
    evidence = getattr(rule, "evidence", None) if rule is not None else None
    if evidence is None:
        return None
    stored = evidence.to_stored() if hasattr(evidence, "to_stored") else evidence
    if not isinstance(stored, dict):
        return None
    return [entry for entry in (stored.get("rules") or []) if isinstance(entry, dict)]


def _union(predicates: list[Q]) -> Q:
    combined = Q(pk__in=[])
    for predicate in predicates:
        combined |= predicate
    return combined


def rule_metric_filter(rule: Any) -> Q:
    """The predicate a metric must satisfy for one derived property (RFC 0009).

    Compiles the rule's ``evidence`` — a **rule list** with the definition's
    logic (RFC 0014): any rule admits, all of a rule's `when` conditions must
    hold, `unless` groups subtract; KEY and MEASURED_AT included — with belief
    time on the `asserted_at` column denormalized onto `Metric`. A rule with no
    evidence constrains nothing here; the category's rules are the default,
    see :func:`metric_scope`.
    """
    rules = _evidence_rules(rule)
    if rules is None:
        return Q()
    return _union([_rule_trust_q(entry, asserted_at_column="asserted_at", include_metric_fields=True) for entry in rules])


def metric_scope(definition: dict[str, Any] | None, rule: Any) -> tuple[Q, Q | None]:
    """(claim predicate, standing predicate) for the metrics one property folds.

    **Replacement with a default, not intersection.** When the rule carries
    ``evidence`` rules, they *are* the property's metric rule — the
    category's rules name who may say what exists and what it is called, and
    the people measuring are usually a different population (pipelines,
    instruments), so ANDing the two would routinely produce an empty fold. When
    the rule says nothing, the category's rules apply to the metrics'
    assertions too, and a primitive category folds everything.

    The standing predicate follows the same source — whose retraction of a
    metric counts is decided by whichever rule admitted the metric — but is
    phrased over ``assertion__*`` paths (a `Standing` has no denormalized
    `asserted_at`) and skips ``KEY`` and ``MEASURED_AT``: a position on a claim
    is not a measurement. ``None`` when any admitting rule then constrains
    nobody, the same edge `trust_predicate` takes.
    """
    rules = _evidence_rules(rule)
    if rules is not None:
        claim = rule_metric_filter(rule)
        halves = [_rule_trust_q(entry, asserted_at_column="assertion__asserted_at") for entry in rules]
        if any(not half.children for half in halves):
            return claim, None
        return claim, _union(halves)

    claim = trust_filter(definition, kind="MEASUREMENT", asserted_at_column="asserted_at", include_metric_fields=True)
    return claim, trust_predicate(definition, kind="MEASUREMENT")


def asserted_as_keys(definition: dict[str, Any] | None) -> list[str]:
    """The words a definition derives from — the union over its rules' WORD conditions.

    One place, because two read it — the predicate that matches claims, and
    `term_ids_for`, which has to widen a graph's membership to cover them. Those
    disagreeing would make a definition that matches claims the graph cannot see.
    Everything downstream of the vocabulary — `CategoryAssertedTerm`, membership,
    `refs_admitted_by`, `backfill_category`'s rebuild decision — reads the shape
    only through here. Order is rule order, first occurrence wins.

    Every written rule carries a WORD condition (the write path refuses one
    without), so there is no wordless case any more —
    `definition_matches_every_word` went with the clause shape.
    """
    from graph_engine.input_models import rule_covers

    seen: dict[str, None] = {}
    for rule in _rules(definition):
        if not rule_covers(rule, "CLASSIFICATION"):
            # A SAMENESS- or EXISTENCE-only rule names no vocabulary (RFC 0011);
            # the write path refuses WORD conditions on it anyway.
            continue
        for key in _rule_words(rule):
            seen.setdefault(key, None)
    return list(seen)


def classification_filter(definition: dict[str, Any] | None) -> Q:
    """The predicate a claim must satisfy to *mean* a defined category.

    The whole-rule reading (RFC 0010): WORD conditions included, so this is the
    one that decides which claims a definition admits. A definition matches a
    claim iff **any rule** does; a rule matches when **all** its `when`
    conditions hold and **no** `unless` group does. Applied to
    `Link(kind=CLASSIFIES)` for node categories and to a relation or event
    category's own link claims (RFC 0009) — always joined to the claim's
    assertion.

    An empty definition means the category is *primitive* — membership is
    whatever was asserted — and matches everything its word can see. A stored
    `rules: []` (unspellable at the write; read-side defense) matches nothing —
    the explicit contradiction, never the collapsed ``Q()``.
    """
    from graph_engine.input_models import rule_covers

    if not definition:
        return Q()

    rules = [rule for rule in _rules(definition) if rule_covers(rule, "CLASSIFICATION")]
    if not rules:
        return Q(pk__in=[])

    predicates = []
    for rule in rules:
        predicate = _rule_trust_q(rule, asserted_at_column="assertion__asserted_at")
        words = _rule_words(rule)
        if words:
            predicate &= Q(term__key__in=words)
        predicates.append(predicate)

    if any(not predicate.children for predicate in predicates):
        # A written rule always names words, so this is read-side defense for a
        # hand-stored rule that names nothing: it admits every claim, and OR-ing
        # it would silently vanish, so say it outright.
        return Q()

    combined = predicates[0]
    for predicate in predicates[1:]:
        combined |= predicate
    return combined



# `claim_filter` / `view_predicate` are gone with `Graph.selector` (RFC 0009).
# Whose claims and standings count is the *category's* rule now: use
# `trust_filter` / `trust_predicate` with the category's definition, and
# `classification_filter` where the words matter too.


def term_ids_for(graph: Any) -> set[Any]:
    """Every organization term this graph can see.

    Two sources, and the second is easy to forget:

    - the words its categories **declare** (`Category.term`), and
    - the words their **definitions derive from** (`definition.asserted_as`).

    A category is a rule over claims, so a view's "Neuron" may be defined as
    "anything claimed Pyramidal or Interneuron" without declaring either word
    itself. Counting only the declared ones excluded those nodes from
    `instances_for` — so they never reached `resolve_categories` and the definition
    never fired. The category matched claims the graph could not see.

    Returns a materialized set rather than a subquery, deliberately: it is the
    size of the graph's *vocabulary*, not of its nodes.

    The derived half comes from `core.CategoryAssertedTerm` rather than from
    re-reading every ``definition`` blob — the same table
    :func:`_graph_ids_by_term` reads, so the two cannot come to different
    conclusions about which words a definition names. That mattered enough to
    normalize: a definition that matched claims the graph could not see is the bug
    this function documents having already been fixed once.

    Deliberately reaching into `core` from here: which words a view speaks is a
    fact about the view, and this module is where the two sides are joined.
    Nothing flows the other way — no evidence row names a graph.
    """
    from core import asserted_terms
    from core import models as core_models

    declared: set[Any] = {term_id for term_id in core_models.Category.objects.filter(graph=graph).values_list("term_id", flat=True) if term_id is not None}

    # The derived half is matched on **key and kind**, not key alone. A `Term`'s
    # identity is `(organization, kind, key)` — "Mitosis" the natural-event word
    # and "Mitosis" the entity word are two terms — and a definition is written on
    # a category of one kind, so the words it derives from are words of that kind.
    # Matching on the key alone let an `EntityCategory` defined over the key
    # "Mitosis" admit event instances classified under the *event* word, which
    # the plural lists then wrapped as `Entity`.
    derived = Q()
    for key, kind in asserted_terms.keys_and_kinds_for_graph(graph):
        derived |= Q(key=key, kind=kind)
    if derived:
        declared.update(evidence_models.Term.objects.for_organization(graph.organization).filter(derived).values_list("id", flat=True))

    return declared


def instances_for(graph: Any) -> QuerySet[Any]:
    """The nodes this graph contains.

    **The one place graph membership is decided**, together with its inverse
    :func:`graph_ids_for_instance_ids`. It used to be decided in five, by testing
    whether a ref started with ``{age_name}:`` — which made membership a property
    of a node's *name*, so a node could belong to exactly one view forever and
    the same claim could not be seen twice.

    Membership is a question about derivation rules: a graph contains a node when
    its own terms admit it. Everything routes through these two functions so that
    tightening the rule is one edit rather than five.

    "Its own terms" means the words it declares a `Category` for **and** the words
    those categories' definitions derive from — see :func:`term_ids_for`. The node
    names a term; whether *this* view has anything to say about that word is what
    decides membership, and it is why one node can now be in two graphs.
    """
    return evidence_models.Instance.objects.for_organization(graph.organization).filter(term__in=term_ids_for(graph))


def instance_refs_for(graph: Any) -> QuerySet[Any]:
    """The same membership, shaped for comparison against an opaque ref column.

    A **subquery**, not a materialized list. `Link.source_ref`/`target_ref` are
    CharFields — they have to be, since one column addresses four tables — so
    Postgres will not compare them against a `uuid` column without a cast. Doing
    the cast here keeps the whole thing in the database; the obvious alternative
    inlines every node id in the graph into an `IN (...)` on every call, and
    `_structure_ids_informing` is called once per derived property per entity.
    """
    return instances_for(graph).annotate(ref_str=Cast("id", CharField(max_length=1000))).values("ref_str")


def instance_ids_for(graph: Any) -> list[str]:
    """The nodes this graph contains, as ref strings. Materialized.

    Prefer :func:`instance_refs_for` inside a query. This exists for the callers that
    genuinely need the values in Python.
    """
    return [str(node_id) for node_id in instances_for(graph).values_list("id", flat=True)]


def _graph_ids_by_term(organization: Any) -> dict[Any, list[Any]]:
    """Which graphs speak each of the organization's words.

    The inverse of :func:`term_ids_for`, built for the whole organization in **one
    scan** rather than by calling that function per graph. It has to be one scan:
    `term_ids_for` costs two queries each, and its caller
    :func:`graph_ids_for_instance_ids` runs on every write, so per-graph evaluation
    would turn a fifty-graph organization into a hundred queries per claim.

    Categories are the size of the schemas, not of the evidence, so scanning all
    of them is cheap where scanning them once per graph is not — but only if what
    is scanned is narrow. It was not: the derived half read `definition`, so every
    write pulled every JSON blob in the ontology out of the database and parsed it
    in Python. `core.CategoryAssertedTerm` is that half normalized, and this reads
    two columns from it instead.
    """
    from core import asserted_terms

    declared: dict[Any, list[Any]] = {}
    for graph_id, term_id in core_categories(organization):
        if term_id is not None:
            declared.setdefault(term_id, []).append(graph_id)

    # Still not a join, and deliberately: `asserted_as` names a word without
    # naming its *kind*, while a term's identity is `(organization, kind, key)`.
    # Resolving by key alone is what keeps a definition able to derive from a word
    # whichever kind it was minted under.
    derived = asserted_terms.graph_ids_by_key(organization)
    if derived:
        for term_id, key in evidence_models.Term.objects.for_organization(organization).filter(key__in=list(derived)).values_list("id", "key"):
            for graph_id in derived[str(key)]:
                if graph_id not in declared.setdefault(term_id, []):
                    declared[term_id].append(graph_id)

    return declared


def core_categories(organization: Any) -> Any:
    """Every category in the organization, as `(graph_id, term_id)`.

    Split out so :func:`_graph_ids_by_term` reads as the mapping it builds, and so
    the one place this module reaches into `core` stays one place.

    Two columns, not three. It used to carry `definition` as well, which made the
    only per-write scan in the codebase a scan of every JSON blob in the ontology;
    that half is `core.CategoryAssertedTerm` now.
    """
    from core import models as core_models

    return core_models.Category.objects.filter(graph__organization=organization).values_list("graph_id", "term_id")


def graph_ids_for_instance_ids(organization: Any, refs: Any) -> list[tuple[str, Any]]:
    """Which graphs each of these nodes belongs to — the inverse of :func:`instances_for`.

    **Pairs, not a mapping, because a node can be in more than one graph.** That is
    the whole gain from the log naming a term rather than a category: two views
    declaring the same word both see the node, so a metric recorded once refreshes
    both. A `dict[ref, graph]` could only record the last one, and would drop the
    second view silently.

    Counts the words a graph's definitions **derive from** as well as the ones its
    categories declare, exactly as :func:`term_ids_for` does. It used to join
    `term__categories__graph` alone, which made it a narrower rule than the
    function it claims to invert: a view whose "Neuron" is defined as "anything
    claimed Pyramidal or Interneuron" was found by `instances_for` but not by this, so
    a newly claimed Pyramidal reached that view only on the next rebuild. That is
    the same omission `term_ids_for` documents having already been fixed for
    `instances_for`, and it matters more here — this is the only thing deciding where
    a write lands, now that no caller names a graph.

    Ordered by graph id, so a write that reads itself back through "some admitting
    view" reads back through a *reproducible* one.

    Refs with no `Instance` row simply do not appear: they are edge refs, or nodes
    whose term no graph declares any more. Both are expected, since evidence
    outlives the projections built from it.
    """
    graph_ids_by_term = _graph_ids_by_term(organization)
    if not graph_ids_by_term:
        return []

    pairs: list[tuple[str, Any]] = []
    for node_id, term_id in evidence_models.Instance.objects.for_organization(organization).filter(id__in=[str(ref) for ref in refs]).values_list("id", "term_id"):
        for graph_id in sorted(graph_ids_by_term.get(term_id, ())):
            pairs.append((str(node_id), graph_id))

    return pairs


def classification_claims(graph: Any) -> QuerySet[Any]:
    """Every classification claim in this graph's vocabulary, standing *not*
    folded — the base a per-category fold narrows first
    (`projector.resolve_categories` folds each defined category's matches under
    that category's own `trust_predicate`)."""
    return (
        evidence_models.Link.objects.for_organization(graph.organization)
        .filter(
            kind=evidence_models.Link.Kind.CLASSIFIES,
            term__in=term_ids_for(graph),
        )
        .select_related("term", "assertion")
    )


def classification_claims_for(graph: Any) -> QuerySet[Any]:
    """Every live classification claim stated in this graph's vocabulary.

    Scoped by the word claimed rather than by the node claimed about: a
    ``CLASSIFIES`` link names one of the organization's terms, and this graph
    declares a category for some of them.

    **`standing()`, which this was missing.** The docstring said "live" and the
    queryset returned retracted claims — both siblings below wrap and this one
    did not, so a withdrawn classification still counted towards a defined
    category and still showed as a label. Retraction is a `Standing(stands=False)`
    rather than a delete, so nothing about the row itself says it is gone; the
    anti-join against `CurrentStanding` is the only thing that does.
    """
    # Standing folds organization-grain here (the fast path): which claims mean
    # a *defined* category — and whose retractions of them count — is that
    # category's own question, folded under its clauses where the definition is
    # applied (`projector.resolve_categories`). This queryset serves the
    # primitive fallback and candidate narrowing, where the organization's
    # answer is the right one.
    return claims_module.standing(
        evidence_models.Link.objects.for_organization(graph.organization).filter(
            kind=evidence_models.Link.Kind.CLASSIFIES,
            term__in=term_ids_for(graph),
        ),
        "link",
    ).select_related("term", "assertion")


def metrics_for(graph: Any) -> QuerySet[Any]:
    """Every active metric in this graph's organization, in observation order.

    Organization grain: which metrics one *property* counts is that property's
    rule (`metric_scope`), applied where the fold happens."""
    standing = claims_module.standing(
        evidence_models.Metric.objects.for_organization(graph.organization),
        "metric",
    )
    return standing.select_related("structure", "structure__kind", "assertion").order_by("measured_at")


def informs_links_for(graph: Any, *, definition: dict[str, Any] | None = None) -> QuerySet[Any]:
    """Every active INFORMS link whose target is a node of this graph.

    Membership comes from :func:`instances_for`, not from a prefix on the ref.
    That also keeps edge-targeted INFORMS links out — the ones
    `_attach_supporting_evidence` writes against a `Link` pk — because an edge
    ref is not among this graph's node ids. The old prefix test excluded them
    by accident; this excludes them on purpose.

    Both halves of the trust apply, per category (RFC 0009): the link **claim**
    itself must be by somebody the target node's category trusts — whose claim
    *connects* evidence to a node is that node's rule, so an untrusted annotator
    cannot route their structures under a trusted node — and the link's
    **standing** folds under the same predicate. With no ``definition`` (the
    dirty-tracking fan-out, which runs before any category is in scope, and
    every primitive category) both halves are organization grain.
    """
    definition_trust = trust_filter(definition, kind="EVIDENCE")
    return claims_module.standing(
        evidence_models.Link.objects.for_organization(graph.organization)
        .filter(
            kind=evidence_models.Link.Kind.INFORMS,
            target_ref__in=instance_refs_for(graph),
        )
        .filter(definition_trust),
        "link",
        predicate=trust_predicate(definition, kind="EVIDENCE"),
    )


def instance_refs_informed_by(graph: Any, structure_ids: list[Any]) -> list[str]:
    """Which of this graph's entities the given structures are evidence for.

    The fan-out a new metric triggers, and the reason dirty tracking is cheap:
    one indexed lookup on `(organization, kind, source_ref)` rather than a
    traversal.
    """
    return list(informs_links_for(graph).filter(source_ref__in=[str(structure_id) for structure_id in structure_ids]).values_list("target_ref", flat=True).distinct())
