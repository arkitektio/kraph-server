"""Everything the log knows about a thing, read in a constant number of queries.

The UI wants one panel per subject: what has anyone called this, who else says it
is the same thing, what is it connected to. Answered naively that is a fold of the
claim log per subject, and a page of subjects is a page of folds.

It does not have to be. Every one of those questions is a range on an index
`Link` already carries — `(organization, kind, source_ref)` and its target twin —
so each is one seek, and each takes **every** ref on the page at once. Nothing
here is per subject:

- :func:`labels_for` — one grouped query. Aggregated in the database, not folded
  in Python, so two annotators agreeing produce one row with
  ``assertion_count = 2`` while two disagreeing produce two rows. That is the
  distinction the panel exists to show, and it is the same one
  `__assertion_count` draws on a projected edge.
- :func:`sameness_for` and :func:`connections_for` — one query each, both
  directions in one predicate, because sameness and most relations are read from
  either end.

**Everything is asked about a whole component, never a single node.** Every
observation mints its own instance, so what is known about a thing is spread
across the nodes somebody has claimed are one — see :mod:`evidence.identity`.
Asking about the bare node would show one observation's half of the story and
call it the answer.

Organization grain throughout, like `State`: the fold counts every standing
claim, and which of them a *view* counts is applied on read. `CLAUDE.md` records
what the alternative costs.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from django.db.models import Count, Max, Q

from evidence import claims as claims_module
from evidence import identity as identity_module
from evidence import models as evidence_models

#: What "connected to" means. Enumerated positively rather than as an exclusion
#: of `CLASSIFIES` and `SAME_AS` — those two are claims *about* a node, not
#: connections from it, and both are answered elsewhere — because the index is
#: `(organization, kind, source_ref)` and a query naming no kind cannot seek on
#: the ref. An `exclude` reads more naturally and scans.
#:
#: A kind added to `Link.Kind` is therefore invisible here until it is listed,
#: which is the safer direction: a new kind of claim showing up in the panel
#: unannounced is worse than one missing from it.
_CONNECTION_KINDS = (
    evidence_models.Link.Kind.INFORMS,
    evidence_models.Link.Kind.RELATION,
    evidence_models.Link.Kind.STRUCTURE_RELATION,
    evidence_models.Link.Kind.MEASUREMENT,
    evidence_models.Link.Kind.PARTICIPATES_AS_INPUT,
    evidence_models.Link.Kind.PARTICIPATES_AS_OUTPUT,
)


@dataclass(frozen=True)
class Label:
    """A word somebody has called this thing, and how much agreement there is.

    ``assertion_count`` is concurrence, not repetition of a fact: the log records
    every claim, including one that restates a position already held, precisely so
    that a second annotator independently saying "this is an AIS" is countable.
    Two annotators claiming *different* words give two of these, which is the
    conflict represented rather than resolved.
    """

    node_ref: str
    term_id: Any
    assertion_count: int
    latest_assertion_id: Any


# Labels and connections are **organization grain** (RFC 0009): they answer
# "what does the log say", whoever said it. Components and sameness fold per
# view again since RFC 0011 — rule-driven, within each node's category — while
# the claim-grain reads (no graph) keep the organization's cached answer.


def components_for(organization: Any, refs: Iterable[str], graph: Any = None) -> dict[str, list[str]]:
    """The component each ref belongs to. Two queries for the whole page — or,
    with a view in scope, the per-category walk (RFC 0011)."""
    if graph is not None:
        return identity_module.component_refs_for_view(graph, refs)
    return identity_module.component_refs(organization, refs)


def _touching(refs: Iterable[str]) -> Q:
    """Claims with either end among these refs.

    One predicate rather than two queries unioned: both `(organization, kind,
    source_ref)` and `(organization, kind, target_ref)` are indexed, so Postgres
    can take this as a bitmap-or of two seeks.
    """
    wanted = [str(ref) for ref in refs]
    return Q(source_ref__in=wanted) | Q(target_ref__in=wanted)


def labels_for(organization: Any, refs: Iterable[str]) -> dict[str, list[Label]]:
    """What anyone has called each of these nodes, grouped by node.

    Two queries for the whole page, however many nodes it holds: the grouped
    aggregate, and one lookup turning the winning `seq` values into assertion ids.

    Aggregated rather than listed: the panel's question is "what has this been
    called, and by how many people", and returning one row per claim would make
    the client count. Provenance for the *whole* history of a label is a separate
    question with a separate query; what is carried here is the latest assertion,
    which is what "who says so" means when several people do.
    """
    wanted = [str(ref) for ref in refs]
    if not wanted:
        return {}

    rows = (
        claims_module.standing(
            evidence_models.Link.objects.for_organization(organization)
            .filter(
                kind=evidence_models.Link.Kind.CLASSIFIES,
                source_ref__in=wanted,
            )
            ,
            "link",
        )
        .values("source_ref", "term_id")
        # Distinct **assertions**, not rows: an assertion is the unit of
        # authorship, so two claims of the same word under one assertion are one
        # person saying it once, and counting rows would report that as agreement
        # between two.
        #
        # Latest by `seq`, not by `asserted_at`. `seq` is the log's total order
        # and cannot tie; two claims written in one request share a timestamp
        # often enough that "latest" would otherwise be whichever row Postgres
        # happened to return.
        .annotate(assertion_count=Count("assertion_id", distinct=True), latest_seq=Max("assertion__seq"))
        .order_by("-assertion_count", "term_id")
    )

    # `seq` identifies the assertion but is not its primary key, so the winning
    # ids come back in a second lookup rather than a correlated subquery. One
    # query for the whole page either way.
    by_seq: dict[int, Any] = {}
    seqs = [row["latest_seq"] for row in rows if row["latest_seq"] is not None]
    if seqs:
        by_seq = {int(seq): assertion_id for seq, assertion_id in evidence_models.Assertion.objects.for_organization(organization).filter(seq__in=seqs).values_list("seq", "id")}

    grouped: dict[str, list[Label]] = defaultdict(list)
    for row in rows:
        grouped[str(row["source_ref"])].append(
            Label(
                node_ref=str(row["source_ref"]),
                term_id=row["term_id"],
                assertion_count=int(row["assertion_count"]),
                latest_assertion_id=by_seq.get(int(row["latest_seq"])) if row["latest_seq"] is not None else None,
            )
        )
    return dict(grouped)


def sameness_for(organization: Any, refs: Iterable[str], graph: Any = None) -> dict[str, list[Any]]:
    """The standing sameness claims touching each ref. One query — or, with a
    view in scope, the claims its categories admit (RFC 0011).

    Exposed alongside the component rather than folded into it, so a merge is
    visible and contestable instead of silent: the panel can say *who* said two
    observations were one thing, and the claim can be retracted.
    """
    wanted = [str(ref) for ref in refs]
    if not wanted:
        return {}

    if graph is not None:
        links = identity_module.view_sameness_links(graph, wanted)
    else:
        links = claims_module.standing(
            evidence_models.Link.objects.for_organization(organization).filter(_touching(wanted), kind=evidence_models.Link.Kind.SAME_AS),
            "link",
        ).select_related("assertion")

    return _group_by_endpoint(links, wanted)


def connections_for(organization: Any, refs: Iterable[str]) -> dict[str, list[Any]]:
    """Every standing claim connecting these refs to something else. One query.

    Relations, participations and INFORMS alike — they are all `Link` rows, and
    the drawing of them in Apache AGE is a projection that can be dropped. So
    "where is this connected" needs no graph query at all, which is the finding
    that made this panel affordable in the first place.

    Classifications and sameness are excluded: they are claims *about* the node,
    not connections from it, and they are already answered by :func:`labels_for`
    and :func:`sameness_for`.
    """
    wanted = [str(ref) for ref in refs]
    if not wanted:
        return {}

    links = claims_module.standing(
        evidence_models.Link.objects.for_organization(organization).filter(_touching(wanted), kind__in=list(_CONNECTION_KINDS)),
        "link",
    ).select_related("assertion", "term")

    return _group_by_endpoint(links, wanted)


def informed_nodes(structure_refs: Iterable[str]) -> list[list[Any]]:
    """The nodes each structure is evidence for. Two queries for the whole page.

    Batched rather than resolved per structure, and that is what makes the rest of
    the panel batch too: a DataLoader dispatches once per event-loop tick, so a
    per-structure `sync_to_async` here would resolve each structure's entities at a
    different moment and every downstream loader would then see a batch of one.

    Organization-wide, like `projector.refs_informed_by`: ingest names no graph, so
    a structure informs whatever it informs regardless of which view is asking.

    Refs naming no `Instance` are dropped — `_attach_supporting_evidence` writes INFORMS
    links against edge primary keys too, and an edge is not something a structure
    "informs" in the sense this answers.
    """
    wanted = [str(ref) for ref in structure_refs]
    if not wanted:
        return []

    # Scoped by organization even though the refs are globally unique uuids: the
    # index is `(organization, kind, source_ref)`, and skipping its leading column
    # turns a seek into a scan. One lookup to find the tenants, which a page of
    # subjects shares.
    organization_ids = set(evidence_models.Structure.all_objects.filter(pk__in=wanted).values_list("organization_id", flat=True))
    if not organization_ids:
        return [[] for _ in wanted]

    links = claims_module.standing(
        evidence_models.Link.all_objects.filter(
            organization_id__in=organization_ids,
            kind=evidence_models.Link.Kind.INFORMS,
            source_ref__in=wanted,
        ),
        "link",
    ).values_list("source_ref", "target_ref")

    refs_by_structure: dict[str, list[str]] = defaultdict(list)
    every_target: set[str] = set()
    for source_ref, target_ref in links:
        refs_by_structure[str(source_ref)].append(str(target_ref))
        every_target.add(str(target_ref))

    nodes = {str(node.pk): node for node in evidence_models.Instance.all_objects.filter(pk__in=every_target).select_related("term", "organization").order_by("created_at")}

    return [[nodes[ref] for ref in refs_by_structure.get(structure_ref, ()) if ref in nodes] for structure_ref in wanted]


@dataclass(frozen=True)
class Known:
    """Everything the log has to say about one node, over its whole component."""

    node_ref: str
    component: list[str]
    labels: list[Label]
    sameness: list[Any]
    connections: list[Any]


def known_about(refs: Iterable[str], graph: Any = None) -> list[Known]:
    """The whole panel, for a page of nodes, in a constant number of queries.

    Batched as one function rather than four loaders because all four questions
    need the same components, and computing them four times is the cost this is
    here to avoid. Positional correspondence with ``refs``, because a DataLoader
    requires it.

    The organization is looked up from the `Instance` rows rather than passed in: the
    caller has already authorized each node it is asking about, and threading a
    tenant through a batch that may legitimately span two of them would be a
    second, weaker copy of the check the resolver already made.

    A ref with no `Instance` row gets an empty answer rather than an error — it is an
    edge ref, or a node whose organization has since gone. Both are ordinary;
    evidence outlives the projections built from it.
    """
    wanted = [str(ref) for ref in refs]
    if not wanted:
        return []

    by_organization: dict[Any, list[str]] = defaultdict(list)
    organizations: dict[Any, Any] = {}
    for node in evidence_models.Instance.all_objects.filter(pk__in=wanted).select_related("organization"):
        by_organization[node.organization_id].append(str(node.pk))
        organizations[node.organization_id] = node.organization

    known: dict[str, Known] = {}
    for organization_id, node_refs in by_organization.items():
        organization = organizations[organization_id]

        components = components_for(organization, node_refs, graph=graph)
        # Every member of every component on the page, asked for once. The three
        # reads below are one query each regardless of how many nodes that is.
        every_member = sorted({member for members in components.values() for member in members})

        labels = labels_for(organization, every_member)
        sameness = sameness_for(organization, every_member, graph=graph)
        connections = connections_for(organization, every_member)

        for ref in node_refs:
            members = components[ref]
            known[ref] = Known(
                node_ref=ref,
                component=members,
                labels=[label for member in members for label in labels.get(member, ())],
                sameness=_distinct_links(sameness, members),
                connections=_distinct_links(connections, members),
            )

    return [known.get(ref, Known(node_ref=ref, component=[ref], labels=[], sameness=[], connections=[])) for ref in wanted]


def _distinct_links(grouped: dict[str, list[Any]], members: Iterable[str]) -> list[Any]:
    """The links touching any member of one component, each listed once.

    De-duplicated here and not in :func:`_group_by_endpoint`: a claim with both
    ends inside the *same* component is one fact about that component, so
    reporting it twice would double-count exactly the relations a merge creates.
    """
    seen: dict[Any, Any] = {}
    for member in members:
        for link in grouped.get(member, ()):
            seen.setdefault(link.pk, link)
    return list(seen.values())


def _group_by_endpoint(links: Any, wanted: list[str]) -> dict[str, list[Any]]:
    """Index links by whichever of their ends the caller asked about.

    A claim with *both* ends in the page appears under both, which is correct: it
    is a fact about each of them, and de-duplicating would make the answer depend
    on what else happened to be on the page.
    """
    asked = set(wanted)
    grouped: dict[str, list[Any]] = defaultdict(list)
    for link in links:
        for ref in (str(link.source_ref), str(link.target_ref)):
            if ref in asked:
                grouped[ref].append(link)
    return dict(grouped)
