"""Folding sameness claims into components.

Three operations, and the asymmetry between them is the whole design — the same
asymmetry :mod:`evidence.state` has, for the same reason:

- :func:`merge` unions two components when a `SAME_AS` claim is written. Cheap,
  incremental, no traversal.
- :func:`retract` cannot undo a union. Union-find has no split, so a retraction
  flags the component instead of fixing it.
- :func:`recompute` rebuilds one component from the claims that survive. The
  expensive path, reached only when a retraction may have broken it apart.

Nothing here decides *whether* a claim counts. The fold counts every standing
`SAME_AS`; a view that refuses one (a category's KIND SAMENESS rule, RFC 0011) applies that on read — which is
:func:`component_refs_for_view` (RFC 0008): a walk of the trusted claims for the
scoped view, the cached component for everyone else. The *cache* stays
organization grain on purpose; `CLAUDE.md` records what the alternative costs:
`merge`, `recompute` and `refold_state` once disagreed about which metrics
counted, so ingest and replay produced different numbers from the same evidence
— and a per-view cache would put a graph foreign key into `evidence/`, which
this app may not grow.

**A `DIFFERENT_FROM` vetoes the direct `SAME_AS`** (RFC 0019). The one rule
every fold here applies, through :func:`admitted_sameness`: a standing
`DIFFERENT_FROM(a, b)` — trusted under the same `SAMENESS` rule as the claim it
contradicts, wherever a view is in scope — removes every `SAME_AS` between
exactly a and b, in either orientation, from the fold. It does nothing else. If
a and b are still connected through a third instance the component stays whole:
the fold does not guess which of the other claims to drop, and the panel
reports the difference as a *conflict* for a person to settle by retracting
one. Local to the pair by design, so a frontier walk that loads the claims
touching a ref sees both the sameness and its veto in the same query.

**The representative is the lowest uuid in the component.** Not the first
asserted — identity must not depend on arrival order, and a deterministic rule is
what lets a replay land where the original write did.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any, Iterable

from django.db import transaction
from django.db.models import Q

from evidence import claims as claims_module
from evidence import models as evidence_models

#: What a component is folded from. Kept as a name rather than inlined so the
#: fold, the rebuild and the consistency test cannot drift apart about it.
SAME_AS = evidence_models.Link.Kind.SAME_AS
#: What subtracts from it.
DIFFERENT_FROM = evidence_models.Link.Kind.DIFFERENT_FROM
#: Both, in the order a fold reads them: everything the identity fold is about.
IDENTITY_KINDS: tuple[Any, ...] = (SAME_AS, DIFFERENT_FROM)


def _standing_identity(organization: Any, kinds: Sequence[Any] = IDENTITY_KINDS) -> Any:
    """Every sameness and difference claim that still stands in this organization."""
    return claims_module.standing(
        evidence_models.Link.objects.for_organization(organization).filter(kind__in=list(kinds)),
        "link",
    )


def _pair(link: Any) -> frozenset[str]:
    return frozenset((str(link.source_ref), str(link.target_ref)))


def vetoed_pairs(links: Iterable[Any]) -> set[frozenset[str]]:
    """The unordered endpoint pairs the `DIFFERENT_FROM` claims among `links` name."""
    return {_pair(link) for link in links if link.kind == DIFFERENT_FROM}


def admitted_sameness(links: Iterable[Any]) -> list[Any]:
    """The `SAME_AS` claims among `links` that no `DIFFERENT_FROM` among them
    vetoes — the one place the veto rule is written. `links` must already be
    the standing, trusted set for whatever scope is folding."""
    links = list(links)
    vetoed = vetoed_pairs(links)
    return [link for link in links if link.kind == SAME_AS and _pair(link) not in vetoed]


def _adjacency(links: Iterable[Any]) -> dict[str, set[str]]:
    """Symmetric adjacency over the admitted sameness among `links`."""
    adjacency: dict[str, set[str]] = defaultdict(set)
    for link in admitted_sameness(links):
        source, target = str(link.source_ref), str(link.target_ref)
        adjacency[source].add(target)
        adjacency[target].add(source)
    return adjacency


def standing_adjacency(organization: Any) -> dict[str, set[str]]:
    """The organization's whole sameness graph, vetoes applied — what
    :func:`refold` writes and what `manage.py rebuild_identity --check`
    compares the cache against. One query."""
    return _adjacency(_standing_identity(organization).only("id", "kind", "source_ref", "target_ref"))


def canonical_for(organization: Any, node_ref: str) -> str:
    """The representative of this node's component.

    Returns the node itself when nothing has been merged with it — a component of
    one has no row, because materializing those would make the table as large as
    `Instance` and say nothing.
    """
    return canonical_for_many(organization, [node_ref])[str(node_ref)]


def canonical_for_many(organization: Any, node_refs: Iterable[str]) -> dict[str, str]:
    """Representatives for many nodes at once. One query.

    Batched because the panel asks about a page of structures, and asking per
    node is how a read that should be one seek becomes N.
    """
    refs = [str(ref) for ref in node_refs]
    rows = evidence_models.InstanceIdentity.objects.for_organization(organization).filter(instance_id__in=refs).values_list("instance_id", "canonical_id")

    found = {str(instance_id): str(canonical_id) for instance_id, canonical_id in rows}
    return {ref: found.get(ref, ref) for ref in refs}


def component_refs(organization: Any, node_refs: Iterable[str]) -> dict[str, list[str]]:
    """Every node in the component of each given node, keyed by the node asked about.

    Two queries regardless of how many nodes are asked about: one to find the
    representatives, one to expand them. The expansion is the indexed
    `(organization, canonical)` seek this table exists for.
    """
    refs = [str(ref) for ref in node_refs]
    canonical = canonical_for_many(organization, refs)

    members: dict[str, list[str]] = defaultdict(list)
    rows = evidence_models.InstanceIdentity.objects.for_organization(organization).filter(canonical_id__in=set(canonical.values())).values_list("canonical_id", "instance_id")
    for canonical_id, instance_id in rows:
        members[str(canonical_id)].append(str(instance_id))

    # An unmerged node has no rows under its own id, so the default stands: a
    # component of one, which is what "nobody has merged this" means.
    return {ref: sorted(members.get(canonical[ref], [ref])) for ref in refs}


def _trusted_in_view(graph: Any, links: list[Any], resolved: Mapping[str, Sequence[Any]]) -> list[Any]:
    """The identity claims among `links` a view counts, given where their
    endpoints resolved.

    RFC 0011: sameness is **within a category, across words** (an AIS and an
    AxonInitialSegment may be one individual; an AIS and a Cell may not — a
    thing is one kind of thing). A node holds several categories in a view
    (RFC 0019), so a claim counts here when the two endpoints **share** a
    category and the claim and its standing fold under that shared category's
    `KIND SAMENESS` trust — any shared one: a category that holds both nodes
    and counts the claim is a view's reason to draw them as one. A primitive
    category trusts everybody, but still never unions across categories.
    `DIFFERENT_FROM` is read under exactly the same rule (RFC 0019): the
    category that decides whose "these are one" counts decides whose "these
    are two" does.
    """
    from evidence import selector as selector_module

    by_category: dict[Any, list[Any]] = defaultdict(list)
    categories: dict[Any, Any] = {}
    for link in links:
        source = {category.pk: category for category in resolved.get(str(link.source_ref), ())}
        target = {category.pk for category in resolved.get(str(link.target_ref), ())}
        for pk in sorted(set(source) & target):
            by_category[pk].append(link)
            categories[pk] = source[pk]

    surviving: dict[Any, Any] = {}
    for category_pk, candidate_links in by_category.items():
        category = categories[category_pk]
        admitted = claims_module.standing(
            evidence_models.Link.objects.for_organization(graph.organization)
            .filter(pk__in=[link.pk for link in candidate_links])
            .filter(selector_module.trust_filter(category.definition, kind="SAMENESS")),
            "link",
            predicate=selector_module.trust_predicate(category.definition, kind="SAMENESS"),
        )
        for link in admitted:
            # Once, however many shared categories count it.
            surviving.setdefault(link.pk, link)
    return list(surviving.values())


def view_identity_links(graph: Any, refs: Iterable[str], kinds: Sequence[Any] = IDENTITY_KINDS) -> list[Any]:
    """The sameness and difference claims a view counts that touch these refs
    — one hop, resolved and trusted per category (:func:`_trusted_in_view`).
    The veto is *not* applied: this is the list of claims, for the panel; a
    fold takes :func:`admitted_sameness` of it."""
    from graph_engine import projector as projector_module

    wanted = [str(ref) for ref in refs]
    if not wanted:
        return []

    touching = evidence_models.Link.objects.for_organization(graph.organization).filter(kind__in=list(kinds)).filter(Q(source_ref__in=wanted) | Q(target_ref__in=wanted))
    links = list(touching.only("id", "kind", "source_ref", "target_ref"))
    if not links:
        return []

    endpoint_refs = {str(link.source_ref) for link in links} | {str(link.target_ref) for link in links}
    nodes = list(evidence_models.Instance.objects.for_organization(graph.organization).filter(id__in=endpoint_refs).select_related("term"))
    resolved, _ = projector_module.resolve_categories(graph, nodes)
    return _trusted_in_view(graph, links, resolved)


def view_sameness_links(graph: Any, refs: Iterable[str]) -> list[Any]:
    """The `SAME_AS` claims a view counts that touch these refs — vetoed ones
    included, because a claim the fold outweighs is still a claim somebody made
    and may want to retract."""
    return view_identity_links(graph, refs, kinds=(SAME_AS,))


def view_difference_links(graph: Any, refs: Iterable[str]) -> list[Any]:
    """The `DIFFERENT_FROM` claims a view counts that touch these refs."""
    return view_identity_links(graph, refs, kinds=(DIFFERENT_FROM,))


def component_refs_for_view(graph: Any, node_refs: Iterable[str]) -> dict[str, list[str]]:
    """One view's components: sameness folded under each category's rule.

    The rule-driven successor of the selector walk RFC 0009 deleted (RFC 0011):
    the frontier loop `recompute` uses, but each hop keeps only the claims
    :func:`view_identity_links` admits — same-category endpoints, the
    category's `KIND SAMENESS` trust for the claim and its standing — with the
    difference veto applied per hop, which is exact because a veto is local to
    its pair. The organization-grain cache (`component_refs`) remains the
    no-view answer.
    """
    refs = [str(ref) for ref in node_refs]

    adjacency: dict[str, set[str]] = defaultdict(set)
    seen: set[str] = set()
    frontier = set(refs)
    while frontier:
        seen |= frontier
        discovered: set[str] = set()
        for link in admitted_sameness(view_identity_links(graph, frontier)):
            source, target = str(link.source_ref), str(link.target_ref)
            adjacency[source].add(target)
            adjacency[target].add(source)
            discovered |= {source, target}
        frontier = discovered - seen

    return {ref: sorted(_reachable(ref, adjacency)) for ref in refs}


def view_components(graph: Any, resolved: Mapping[str, Sequence[Any]]) -> dict[str, list[str]]:
    """The individuals a view draws among these already-resolved nodes (RFC 0018).

    `resolved` maps a ref to the categories it resolved to in this view
    (`projector.resolve_categories`); the answer maps each component's
    **representative** — its lowest member uuid — to its sorted members, every
    ref appearing in exactly one. The fold is the one :func:`view_sameness_links`
    applies — a shared category at both ends, that category's `KIND SAMENESS`
    trust for the claim and its standing — but over the whole set at once: one
    link query, one standing fold per category, and a union-find in memory, so
    a rebuild does not walk a frontier per node. Two nodes holding different
    category sets may be one individual when the sets intersect (RFC 0019);
    the vertex is then drawn under the union.

    Closed over `resolved` on purpose: a sameness claim to a node the view does
    not admit (unclassified here, retracted under its category's rule, skipped
    as ambiguous) is not a bridge. That node is not in this view, so it cannot
    hold two of its individuals together.
    """
    refs = sorted(str(ref) for ref in resolved)
    if not refs:
        return {}

    links = list(evidence_models.Link.objects.for_organization(graph.organization).filter(kind__in=list(IDENTITY_KINDS), source_ref__in=refs, target_ref__in=refs).only("id", "kind", "source_ref", "target_ref"))

    parent: dict[str, str] = {ref: ref for ref in refs}

    def find(ref: str) -> str:
        while parent[ref] != ref:
            parent[ref] = parent[parent[ref]]
            ref = parent[ref]
        return ref

    for link in admitted_sameness(_trusted_in_view(graph, links, resolved)):
        left, right = find(str(link.source_ref)), find(str(link.target_ref))
        if left != right:
            # Union under the lower root: the root is then the representative.
            parent[max(left, right)] = min(left, right)

    components: dict[str, list[str]] = defaultdict(list)
    for ref in refs:
        components[find(ref)].append(ref)
    return {representative: sorted(members) for representative, members in components.items()}


@transaction.atomic
def merge(organization: Any, left_ref: str, right_ref: str) -> str:
    """Union the components of two nodes. Returns the surviving representative.

    Idempotent: a second claim that two already-merged nodes are the same adds
    agreement to the log and changes nothing here, which is the correct
    behaviour — the fold records *which nodes are one thing*, not how many people
    said so. How many said so is a question for the claims.

    A standing `DIFFERENT_FROM` between exactly these two vetoes the union (RFC
    0019): the claim is in the log, the cache does not move, and what is
    returned is the left node's representative as it stands.
    """
    left, right = str(left_ref), str(right_ref)
    current = canonical_for_many(organization, [left, right])
    left_canonical, right_canonical = current[left], current[right]

    if _standing_identity(organization, kinds=(DIFFERENT_FROM,)).filter(Q(source_ref=left, target_ref=right) | Q(source_ref=right, target_ref=left)).exists():
        return left_canonical

    members = set(component_members(organization, left_canonical)) | set(component_members(organization, right_canonical)) | {left, right}
    canonical = min(members)

    _write_component(organization, members, canonical)
    return canonical


def component_members(organization: Any, canonical_ref: str) -> list[str]:
    """Every node currently recorded under this representative."""
    return [str(instance_id) for instance_id in evidence_models.InstanceIdentity.objects.for_organization(organization).filter(canonical_id=str(canonical_ref)).values_list("instance_id", flat=True)]


def _write_component(organization: Any, members: set[str], canonical: str) -> None:
    """Point every member at one representative, replacing whatever was there.

    Deletes first rather than updating in place: a union can absorb rows that
    belonged to a different representative, and `unique` is on `node`, so a
    delete-then-create is both simpler and correct where an `update` would have
    to know which rows it was allowed to touch.
    """
    evidence_models.InstanceIdentity.objects.for_organization(organization).filter(instance_id__in=members).delete()

    if len(members) < 2:
        # A component of one is the absence of a row. Nothing is merged, so there
        # is nothing to say.
        return

    evidence_models.InstanceIdentity.all_objects.bulk_create(
        [
            evidence_models.InstanceIdentity(
                organization=organization,
                instance_id=member,
                canonical_id=canonical,
            )
            for member in sorted(members)
        ]
    )


@transaction.atomic
def retract(organization: Any, link: evidence_models.Link) -> None:
    """Flag the component a withdrawn sameness claim may have split.

    Union-find cannot un-union, so this does not try. It marks, and
    :func:`recompute` rebuilds — the same division of labour `state.retract` and
    `state.recompute` already use for the statistics a retraction invalidates.

    Marking the whole component rather than guessing which half moved is
    deliberate: whether the claim was a bridge or a redundant edge inside an
    already-connected set is exactly what the rebuild determines, and guessing it
    here would be a second implementation of the same question.
    """
    canonical = canonical_for(organization, str(link.source_ref))
    evidence_models.InstanceIdentity.objects.for_organization(organization).filter(canonical_id=canonical).update(needs_recompute=True)


@transaction.atomic
def separate(organization: Any, left_ref: str, right_ref: str) -> list[str]:
    """Apply a newly written `DIFFERENT_FROM` to the cache (RFC 0019).

    The mirror of :func:`merge` with :func:`retract`'s shape: a veto can only
    ever *remove* a union, and union-find has no split, so when the two nodes
    share a component it is flagged and rebuilt on the spot — the rebuild is
    what decides whether the vetoed claim was the bridge. Two nodes in
    different components need nothing; the veto is enforced by :func:`merge`
    from now on. Returns the representatives that exist afterwards.
    """
    left, right = str(left_ref), str(right_ref)
    current = canonical_for_many(organization, [left, right])
    if current[left] != current[right]:
        return []
    evidence_models.InstanceIdentity.objects.for_organization(organization).filter(canonical_id=current[left]).update(needs_recompute=True)
    return recompute(organization, current[left])


@transaction.atomic
def recompute(organization: Any, canonical_ref: str) -> list[str]:
    """Rebuild one component from the sameness claims that still stand,
    less the ones a standing difference vetoes.

    The correctness backstop: whatever incremental maintenance did, this is what
    the answer should have been. A retraction can split one component into
    several, so this returns the representatives that now exist where one did.

    Walks only the claims touching this component's members, not the whole
    organization — a retraction somewhere else has not moved anything here.
    """
    members = set(component_members(organization, str(canonical_ref))) or {str(canonical_ref)}

    # Grow the working set until it closes: a claim may reach a node that was not
    # recorded under this representative, and dropping it would silently split a
    # component that is still whole.
    adjacency: dict[str, set[str]] = defaultdict(set)
    seen: set[str] = set()
    frontier = set(members)
    while frontier:
        links = _standing_identity(organization).filter(Q(source_ref__in=frontier) | Q(target_ref__in=frontier)).only("id", "kind", "source_ref", "target_ref")
        seen |= frontier
        discovered: set[str] = set()
        for source, neighbours in _adjacency(links).items():
            adjacency[source] |= neighbours
            discovered.add(source)
            discovered |= neighbours
        frontier = discovered - seen

    members |= seen

    representatives: list[str] = []
    unassigned = set(members)
    while unassigned:
        start = min(unassigned)
        component = _reachable(start, adjacency)
        unassigned -= component
        canonical = min(component)
        _write_component(organization, component, canonical)
        if len(component) > 1:
            representatives.append(canonical)

    return representatives


def _reachable(start: str, adjacency: dict[str, set[str]]) -> set[str]:
    """Every node reachable from `start` through standing sameness claims."""
    component = {start}
    frontier = [start]
    while frontier:
        node = frontier.pop()
        for neighbour in adjacency.get(node, ()):  # noqa: B007 - adjacency is symmetric
            if neighbour not in component:
                component.add(neighbour)
                frontier.append(neighbour)
    return component


def recompute_stale(organization: Any, limit: int | None = None) -> int:
    """Rebuild every component a retraction left flagged. Returns how many were rebuilt."""
    stale = evidence_models.InstanceIdentity.objects.for_organization(organization).filter(needs_recompute=True).values_list("canonical_id", flat=True).distinct()
    canonicals = [str(canonical) for canonical in stale]
    if limit is not None:
        canonicals = canonicals[:limit]

    for canonical in canonicals:
        recompute(organization, canonical)
    return len(canonicals)


def refold(organization: Any) -> int:
    """Rebuild every component in the organization from scratch. Returns how many exist.

    The honesty test, and what `manage.py rebuild_identity` runs. If this
    disagrees with what incremental maintenance produced, the incremental path is
    wrong — which is the whole reason it exists separately.
    """
    adjacency = standing_adjacency(organization)

    evidence_models.InstanceIdentity.objects.for_organization(organization).delete()

    components = 0
    unassigned = set(adjacency)
    while unassigned:
        component = _reachable(min(unassigned), adjacency)
        unassigned -= component
        _write_component(organization, component, min(component))
        components += 1
    return components
