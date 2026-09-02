"""Turning a graph's selector into the evidence it projects.

A ``Graph`` is a view over its organization's evidence, and ``Graph.selector``
says which part. Evaluating it produces a queryset, never a stored membership
flag: writes stay projection-agnostic, so ingesting a metric does not have to
know about every graph that might one day want it. That is what keeps bulk
ingest O(N) instead of O(N x projections).

Selector shape (every key optional; an empty selector means "everything this
organization knows")::

    {
      "category_keys":    ["ROI", "Image"],       # which structure kinds are in scope
      "assertion_filter": {                        # whose evidence counts
          "subjects":     ["AI_Model_X"],
          "app_ids":      ["mikro"],
          "action_names": ["segment"]
      },
      "as_of":            "2026-03-03T00:00:00Z",  # asserted_at upper bound
      "since":            "2026-01-01T00:00:00Z",  # asserted_at lower bound
      "observed_window":  ["2025-01-01", "2025-12-31"]   # measured_at range
    }

``as_of`` is the one that matters scientifically: "the graph as we believed it on
March 3rd" stops being a fork of the data and becomes a filter.
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


#: The assertion columns a filter may name, shared by all three filters so the
#: three siblings cannot drift apart in what "whose claims count" means.
_ASSERTION_FILTER_COLUMNS = (
    ("subjects", "assertion__subject__in"),
    ("app_ids", "assertion__app_id__in"),
    ("action_names", "assertion__action_name__in"),
)


def _assertion_predicate(source: dict[str, Any], *, asserted_at_column: str = "assertion__asserted_at") -> Q:
    """The who-and-when half of one clause or selector.

    `assertion_filter` (subjects / app_ids / action_names, each an *any of*
    list, ANDed across fields), `as_of` (asserted_at upper bound) and `since`
    (asserted_at lower bound). `metric_filter` passes its denormalized
    `asserted_at` column; everything else filters through the assertion join.
    """
    predicate = Q()
    assertion_filter = source.get("assertion_filter") or {}
    for field, column in _ASSERTION_FILTER_COLUMNS:
        values = assertion_filter.get(field)
        if values:
            predicate &= Q(**{column: values})

    as_of = source.get("as_of")
    if as_of:
        predicate &= Q(**{f"{asserted_at_column}__lte": as_of})

    since = source.get("since")
    if since:
        predicate &= Q(**{f"{asserted_at_column}__gte": since})

    return predicate


def _clauses(definition: dict[str, Any] | None) -> list[dict[str, Any]]:
    """A definition as its list of clauses.

    The flat form is one clause; `any_of` is several, one level deep. **Every
    reader of a definition must consume this** — the predicate
    (`classification_filter`) and the vocabulary (`asserted_as_keys`) walking
    the shape differently is exactly how a definition comes to match claims the
    graph cannot see. The read side is permissive: when both `any_of` and flat
    keys are present (refused at every write path, but definitions are JSON),
    `any_of` wins whole, so both readers still agree and the failure mode is a
    dead flat half, never divergence. Non-dict entries are skipped.
    """
    if not definition:
        return []
    any_of = definition.get("any_of")
    if any_of is not None:
        return [clause for clause in any_of if isinstance(clause, dict)]
    return [definition]


def _clause_words(clause: dict[str, Any]) -> list[str]:
    """One clause's `asserted_as`, bare string accepted."""
    asserted_as = clause.get("asserted_as")
    if not asserted_as:
        return []
    if isinstance(asserted_as, str):
        return [asserted_as]
    return [str(key) for key in asserted_as]


def metric_filter(selector: dict[str, Any] | None) -> Q:
    """The predicate a metric must satisfy to be in a projection's scope.

    Belief-time bounds are ``as_of`` (upper) and ``since`` (lower), both on the
    `asserted_at` column denormalized onto `Metric`; observation time is the
    two-sided ``observed_window`` over `measured_at`.
    """
    predicate = Q()
    if not selector:
        return predicate

    # Structure identifiers, not category keys — a structure kind has no key.
    category_keys = selector.get("category_keys")
    if category_keys:
        predicate &= Q(structure__identifier__in=category_keys)

    predicate &= _assertion_predicate(selector, asserted_at_column="asserted_at")

    observed_from, observed_to = _parse_window(selector.get("observed_window"))
    if observed_from:
        predicate &= Q(measured_at__gte=observed_from)
    if observed_to:
        predicate &= Q(measured_at__lte=observed_to)

    return predicate


def asserted_as_keys(definition: dict[str, Any] | None) -> list[str]:
    """The words a definition derives from — the union over its clauses.

    One place, because two read it — the predicate that matches claims, and
    `term_ids_for`, which has to widen a graph's membership to cover them. Those
    disagreeing would make a definition that matches claims the graph cannot see.
    Everything downstream of the vocabulary — `CategoryAssertedTerm`, membership,
    `refs_admitted_by`, `backfill_category`'s rebuild decision — reads the shape
    only through here.

    Accepts a bare string as well as a list, per clause. Definitions are
    hand-written JSON, and one word is the common case. Order is clause order,
    first occurrence wins.
    """
    seen: dict[str, None] = {}
    for clause in _clauses(definition):
        for key in _clause_words(clause):
            seen.setdefault(key, None)
    return list(seen)


def definition_matches_every_word(definition: dict[str, Any] | None) -> bool:
    """Whether some clause of this definition names no words at all.

    Such a clause matches claims of *any* word (see `classification_filter`), so
    a candidate narrowing keyed on `asserted_as_keys` would silently drop the
    nodes it admits — the caller must skip the narrowing instead. This is the
    read-side tolerance; every write path requires `asserted_as` per clause.
    """
    clauses = _clauses(definition)
    return any(not _clause_words(clause) for clause in clauses)


def classification_filter(definition: dict[str, Any] | None) -> Q:
    """The predicate a classification claim must satisfy to mean a defined category.

    The sibling of :func:`metric_filter`, and deliberately the same shape: a
    category's definition and a graph's selector are the same kind of statement —
    "which claims count" — asked about different tables. `metric_filter` asks it
    of `Metric`, this asks it of `Link(kind=CLASSIFIES)` joined to its assertion.

    A definition is a **union of clauses** (RFC 0007). Each clause binds its own
    words, annotators and time bounds, and the definition matches a claim iff
    *any* clause does — which is what makes "'Cell' means what Peter called Cell,
    and what Karl called StemCell after Dec 5" one category::

        {
          "any_of": [
            {"asserted_as": ["Cell"],     "assertion_filter": {"subjects": ["peter"]}},
            {"asserted_as": ["StemCell"], "assertion_filter": {"subjects": ["karl"]},
             "since": "2026-12-05T00:00:00Z"}
          ]
        }

    The flat form is still accepted and means a single clause (every key
    optional; an empty definition means the category is *primitive* and
    membership is whatever was asserted)::

        {
          "asserted_as":      ["Pyramidal", "Interneuron"],   # which words were claimed
          "assertion_filter": {"subjects": ["johannes"], "app_ids": [...], "action_names": [...]},
          "as_of":            "2026-08-15T00:00:00Z",         # asserted_at upper bound
          "since":            "2026-01-01T00:00:00Z"          # asserted_at lower bound
        }

    Flat keys and ``any_of`` together are refused at every write path; here on
    the read side ``any_of`` wins whole (see `_clauses`). Clauses nest one level
    only — a clause has no ``any_of``.

    ``asserted_as`` takes **one word or several**, and several means *any of*
    within the clause. A category is a rule over claims, and there is no reason
    a view's "Neuron" should not be "anything claimed Pyramidal or Interneuron"
    — that is ordinary ontology, and restricting it to a single word made a
    defined category a rename rather than a definition. A bare string is still
    accepted and means the obvious thing. What clauses add is *binding*: a
    subject or a date scoped to one word rather than smeared across all of them
    — the flat cross-product was the reason "Peter's Cells or Karl's late
    StemCells" was inexpressible.

    Note this is separate from the word a category *mints* claims under, which is
    `Category.term` and is genuinely singular: creating an entity of this category
    claims exactly one word. A category derives from many and asserts as one.

    There is no `observed_window` counterpart: a classification is a claim about
    a thing, not a measurement of it, so it has only belief time. `as_of`/`since`
    filter `Assertion.asserted_at` through the join, where `metric_filter` can
    use the column denormalized onto `Metric`.

    Two edge cases are handled explicitly because Django collapses the empty
    ``Q()`` in an OR (``Q() | Q(x)`` is ``Q(x)``, and a naive fold over zero
    clauses returns the match-everything ``Q()``):

    - ``any_of: []`` (refused at the write) reads as **matches nothing**.
    - a clause with no constraints reads as **matches everything** the graph's
      vocabulary can see — the generalization of a flat ``{"as_of": …}``-only
      definition, which always meant every word.
    """
    if not definition:
        return Q()

    clauses = _clauses(definition)
    if not clauses:
        # An explicitly empty union matches nothing — never the collapsed Q().
        return Q(pk__in=[])

    predicates = []
    for clause in clauses:
        predicate = Q()
        words = _clause_words(clause)
        if words:
            predicate &= Q(term__key__in=words)
        predicate &= _assertion_predicate(clause)
        predicates.append(predicate)

    if any(not predicate.children for predicate in predicates):
        # One unconstrained clause admits every claim; OR-ing it would silently
        # vanish, so say it outright.
        return Q()

    combined = predicates[0]
    for predicate in predicates[1:]:
        combined |= predicate
    return combined


def claim_filter(selector: dict[str, Any] | None) -> Q:
    """Whose existence claims a graph counts.

    The third member of the family, alongside :func:`metric_filter` and
    :func:`classification_filter` — the same "which claims count" question asked
    of :class:`~evidence.models.Standing`. That symmetry is the point: whether a
    node exists is contestable in exactly the way its category is, so a graph
    scoped to one annotator gets that annotator's answer about what is there.

    No ``observed_window``: a claim about whether a thing exists is not a
    measurement of it, so it has belief time only. ``as_of`` (upper) and
    ``since`` (lower) filter through the assertion, as `classification_filter`
    does.
    """
    if not selector:
        return Q()
    return _assertion_predicate(selector)


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
    return claims_module.standing(
        evidence_models.Link.objects.for_organization(graph.organization).filter(
            kind=evidence_models.Link.Kind.CLASSIFIES,
            term__in=term_ids_for(graph),
        ),
        "link",
    ).select_related("term", "assertion")


def metrics_for(graph: Any) -> QuerySet[Any]:
    """Every active metric this graph projects, in observation order."""
    standing = claims_module.standing(
        evidence_models.Metric.objects.for_organization(graph.organization).filter(metric_filter(graph.selector)),
        "metric",
    )
    return standing.select_related("structure", "structure__kind", "assertion").order_by("measured_at")


def informs_links_for(graph: Any) -> QuerySet[Any]:
    """Every active INFORMS link whose target is a node of this graph.

    Membership comes from :func:`instances_for`, not from a prefix on the ref.
    That also keeps edge-targeted INFORMS links out — the ones
    `_attach_supporting_evidence` writes against a `Link` pk — because an edge
    ref is not among this graph's node ids. The old prefix test excluded them
    by accident; this excludes them on purpose.
    """
    return claims_module.standing(
        evidence_models.Link.objects.for_organization(graph.organization).filter(
            kind=evidence_models.Link.Kind.INFORMS,
            target_ref__in=instance_refs_for(graph),
        ),
        "link",
    )


def instance_refs_informed_by(graph: Any, structure_ids: list[Any]) -> list[str]:
    """Which of this graph's entities the given structures are evidence for.

    The fan-out a new metric triggers, and the reason dirty tracking is cheap:
    one indexed lookup on `(organization, kind, source_ref)` rather than a
    traversal.
    """
    return list(informs_links_for(graph).filter(source_ref__in=[str(structure_id) for structure_id in structure_ids]).values_list("target_ref", flat=True).distinct())
