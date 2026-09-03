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

**The representative is the lowest uuid in the component.** Not the first
asserted — identity must not depend on arrival order, and a deterministic rule is
what lets a replay land where the original write did.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from django.db import transaction
from django.db.models import Q

from evidence import claims as claims_module
from evidence import models as evidence_models

#: What a component is folded from. Kept as a name rather than inlined so the
#: fold, the rebuild and the consistency test cannot drift apart about it.
SAME_AS = evidence_models.Link.Kind.SAME_AS


def _standing_same_as(organization: Any) -> Any:
    """Every sameness claim that still stands in this organization."""
    return claims_module.standing(
        evidence_models.Link.objects.for_organization(organization).filter(kind=SAME_AS),
        "link",
    )


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


def view_sameness_links(graph: Any, refs: Iterable[str]) -> list[Any]:
    """The SAME_AS claims a view counts that touch these refs — one hop.

    RFC 0011: sameness is **within a category, across words** (an AIS and an
    AxonInitialSegment may be one individual; an AIS and a Cell may not — a
    thing is one kind of thing). A claim counts here when both endpoints
    resolve to the *same* category in this view and the claim and its standing
    fold under that category's `KIND SAMENESS` trust. A primitive category
    trusts everybody, but still never unions across categories.
    """
    from django.db.models import Q

    from evidence import models as inner_models
    from evidence import selector as selector_module
    from graph_engine import projector as projector_module

    wanted = [str(ref) for ref in refs]
    if not wanted:
        return []

    touching = inner_models.Link.objects.for_organization(graph.organization).filter(kind=SAME_AS).filter(Q(source_ref__in=wanted) | Q(target_ref__in=wanted))
    links = list(touching.only("id", "source_ref", "target_ref"))
    if not links:
        return []

    endpoint_refs = {str(link.source_ref) for link in links} | {str(link.target_ref) for link in links}
    nodes = list(inner_models.Instance.objects.for_organization(graph.organization).filter(id__in=endpoint_refs).select_related("term"))
    resolved, _ = projector_module.resolve_categories(graph, nodes)

    by_category: dict[Any, list[Any]] = defaultdict(list)
    for link in links:
        source = resolved.get(str(link.source_ref))
        target = resolved.get(str(link.target_ref))
        if source is None or target is None or source.pk != target.pk:
            continue
        by_category[source.pk].append(link)

    categories = {category.pk: category for category in resolved.values()}
    surviving: list[Any] = []
    for category_pk, candidate_links in by_category.items():
        category = categories[category_pk]
        admitted = claims_module.standing(
            inner_models.Link.objects.for_organization(graph.organization)
            .filter(pk__in=[link.pk for link in candidate_links])
            .filter(selector_module.trust_filter(category.definition, kind="SAMENESS")),
            "link",
            predicate=selector_module.trust_predicate(category.definition, kind="SAMENESS"),
        )
        surviving.extend(admitted)
    return surviving


def component_refs_for_view(graph: Any, node_refs: Iterable[str]) -> dict[str, list[str]]:
    """One view's components: sameness folded under each category's rule.

    The rule-driven successor of the selector walk RFC 0009 deleted (RFC 0011):
    the frontier loop `recompute` uses, but each hop keeps only the claims
    :func:`view_sameness_links` admits — same-category endpoints, the
    category's `KIND SAMENESS` trust for the claim and its standing. The
    organization-grain cache (`component_refs`) remains the no-view answer.
    """
    refs = [str(ref) for ref in node_refs]

    adjacency: dict[str, set[str]] = defaultdict(set)
    seen: set[str] = set()
    frontier = set(refs)
    while frontier:
        seen |= frontier
        discovered: set[str] = set()
        for link in view_sameness_links(graph, frontier):
            source, target = str(link.source_ref), str(link.target_ref)
            adjacency[source].add(target)
            adjacency[target].add(source)
            discovered |= {source, target}
        frontier = discovered - seen

    return {ref: sorted(_reachable(ref, adjacency)) for ref in refs}


@transaction.atomic
def merge(organization: Any, left_ref: str, right_ref: str) -> str:
    """Union the components of two nodes. Returns the surviving representative.

    Idempotent: a second claim that two already-merged nodes are the same adds
    agreement to the log and changes nothing here, which is the correct
    behaviour — the fold records *which nodes are one thing*, not how many people
    said so. How many said so is a question for the claims.
    """
    left, right = str(left_ref), str(right_ref)
    current = canonical_for_many(organization, [left, right])
    left_canonical, right_canonical = current[left], current[right]

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
def recompute(organization: Any, canonical_ref: str) -> list[str]:
    """Rebuild one component from the sameness claims that still stand.

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
        links = _standing_same_as(organization).filter(Q(source_ref__in=frontier) | Q(target_ref__in=frontier))
        seen |= frontier
        discovered: set[str] = set()
        for source_ref, target_ref in links.values_list("source_ref", "target_ref"):
            source, target = str(source_ref), str(target_ref)
            adjacency[source].add(target)
            adjacency[target].add(source)
            discovered |= {source, target}
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
    adjacency: dict[str, set[str]] = defaultdict(set)
    for source_ref, target_ref in _standing_same_as(organization).values_list("source_ref", "target_ref"):
        source, target = str(source_ref), str(target_ref)
        adjacency[source].add(target)
        adjacency[target].add(source)

    evidence_models.InstanceIdentity.objects.for_organization(organization).delete()

    components = 0
    unassigned = set(adjacency)
    while unassigned:
        component = _reachable(min(unassigned), adjacency)
        unassigned -= component
        _write_component(organization, component, min(component))
        components += 1
    return components
