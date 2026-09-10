"""Traversal in a view: the edges a view draws to and from one individual, and who is at the other end.

`Node.connections` answers at organization grain — every standing claim in the
log — and cannot say what *this* view draws. This module answers for the view:
the drawn edges incident to the node's vertex (`Projector.drawn_edges_incident`,
one vertex per individual, RFC 0018), and the claims behind them.

**The claims are recovered by admission, not stored on the edge.** A drawn edge
is the fold of every admitted claim for one proposition (RFC 0021) and carries no
claim ref, so the `Link` rows are found the way `project_edges` found them — the
view's admitting categories over the claims touching the individual's members —
and matched to the drawn set on the drawn key: `(source representative, target
representative, label[, role])`. One `RetrievedEdge` per link; when several
categories admit one claim the view drew several edges and the link is reported
once, under the lowest-pk admitting category among those asked for
(`Link.drawings` lists all of them).

A drawn edge whose claims no longer admit — the drawing behind the rule — is
absent from `incident_edges` and present in `neighbor_refs`, which reads the
drawing alone. That is the same gap `drawings_for_instance` has, and is not
papered over here: the drawing is a cache, the rule is the answer.

No storage words: this module speaks to `controller.projector.*` and the
admission helpers of `graph_engine.projector`, never to the projection tables.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Iterable

from django.db.models import Q

from evidence import models as evidence_models
from graph_engine.projection import IncidentEdge, IncidentEdgesSpec
from graph_engine.retrieved import RetrievedEdge, RetrievedNode

RELATION = str(evidence_models.Link.Kind.RELATION)
INPUT = str(evidence_models.Link.Kind.PARTICIPATES_AS_INPUT)
OUTPUT = str(evidence_models.Link.Kind.PARTICIPATES_AS_OUTPUT)
DRAWN_KINDS = (RELATION, INPUT, OUTPUT)


@dataclass(frozen=True)
class TraversalSpec:
    """What to list: which drawn kinds, which end, under which of the view's categories."""

    kinds: tuple[str, ...] = DRAWN_KINDS
    direction: str = "BOTH"
    #: Relation and event categories of *this* graph; empty means every one.
    category_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        unknown = [kind for kind in self.kinds if kind not in DRAWN_KINDS]
        if unknown:
            raise ValueError(f"Only drawn kinds can be traversed ({', '.join(DRAWN_KINDS)}); not {', '.join(unknown)}")
        if self.direction not in ("IN", "OUT", "BOTH"):
            raise ValueError(f"direction must be IN, OUT or BOTH, not {self.direction!r}")


def _categories(graph: Any, spec: TraversalSpec) -> tuple[list[Any], list[Any]]:
    """The view's relation categories and event categories the spec allows."""
    from graph_engine import projector

    relations = projector.relation_categories(graph) if RELATION in spec.kinds else []
    events = projector.event_categories(graph) if (INPUT in spec.kinds or OUTPUT in spec.kinds) else []
    if spec.category_ids:
        wanted = {str(pk) for pk in spec.category_ids}
        relations = [category for category in relations if str(category.pk) in wanted]
        events = [category for category in events if str(category.pk) in wanted]
    return relations, events


def _labels(relations: Iterable[Any], events: Iterable[Any], spec: TraversalSpec) -> tuple[str, ...]:
    labels: list[str] = [str(category.age_name) for category in relations]
    for category in events:
        kinded = category.as_kind()
        if INPUT in spec.kinds:
            labels.append(str(kinded.AGE_INPUT_EDGE))
        if OUTPUT in spec.kinds:
            labels.append(str(kinded.AGE_OUTPUT_EDGE))
    return tuple(dict.fromkeys(labels))


def drawn_incident(controller: Any, graph: Any, nodes: Iterable[RetrievedNode], spec: TraversalSpec) -> dict[str, list[IncidentEdge]]:
    """The drawn edges touching each node's vertex, keyed by the node's id. Undrawn nodes answer `[]`."""
    nodes = list(nodes)
    reps = [node.unique_id for node in nodes if not node.is_row_backed]
    relations, events = _categories(graph, spec)
    labels = _labels(relations, events, spec)
    if not reps or (spec.category_ids and not labels):
        return {node.unique_id: [] for node in nodes}
    drawn = controller.projector.drawn_edges_incident(graph, reps, IncidentEdgesSpec(labels=labels, direction=spec.direction))
    return {node.unique_id: list(drawn.get(node.unique_id, [])) for node in nodes}


def incident_edges(controller: Any, graph: Any, nodes: Iterable[RetrievedNode], spec: TraversalSpec) -> dict[str, list[RetrievedEdge]]:
    """The claims behind the edges the view draws to or from each node, keyed by the node's id.

    Each list is ordered like every claim list: newest act first, then id.
    """
    from graph_engine import projector

    nodes = list(nodes)
    out: dict[str, list[RetrievedEdge]] = {node.unique_id: [] for node in nodes}
    drawn = drawn_incident(controller, graph, nodes, spec)
    if not any(drawn.values()):
        return out

    relations, events = _categories(graph, spec)
    members: set[str] = set()
    for node in nodes:
        members.add(node.unique_id)
        members.update(str(member) for member in node.members)
    touching = Q(source_ref__in=members) | Q(target_ref__in=members)
    organization = graph.organization

    # (source rep, target rep, label[, role]) → the drawn edge, for the whole asked set.
    index: dict[tuple[Any, ...], IncidentEdge] = {}
    for edges in drawn.values():
        for edge in edges:
            index[(edge.source_ref, edge.target_ref, edge.label, edge.properties.get("role"))] = edge
            index[(edge.source_ref, edge.target_ref, edge.label)] = edge
    rep_of_node = {node.unique_id: node for node in nodes}

    def attach(link: Any, edge: IncidentEdge, category: Any) -> None:
        retrieved = RetrievedEdge.from_link(controller, link, graph_name=graph.age_name, category=category)
        retrieved = dataclasses.replace(retrieved, edge_id=edge.edge_id, left_id=edge.source_id, right_id=edge.target_id)
        for rep in (edge.source_ref, edge.target_ref):
            node = rep_of_node.get(rep)
            if node is not None and not any(existing.row_id == retrieved.row_id for existing in out[rep]):
                out[rep].append(retrieved)

    if relations and RELATION in spec.kinds:
        base = evidence_models.Link.objects.for_organization(organization).filter(kind=evidence_models.Link.Kind.RELATION).filter(touching)
        admitted = projector.admitting_categories(relations, base)
        refs = {str(ref) for link, _ in admitted.values() for ref in (link.source_ref, link.target_ref)}
        canon = projector.representatives_for(controller, graph, refs) if refs else {}
        for link, categories in admitted.values():
            source, target, _ = projector.proposition_key(link, canon)
            for category in sorted(categories, key=lambda c: int(c.pk)):
                edge = index.get((source, target, str(category.age_name)))
                if edge is not None:
                    attach(link, edge, category)
                    break

    wanted_kinds = [kind for kind in (INPUT, OUTPUT) if kind in spec.kinds]
    if events and wanted_kinds:
        base = evidence_models.Link.objects.for_organization(organization).filter(kind__in=wanted_kinds).filter(touching)
        admitted = projector.admitting_categories(events, base)
        refs = {str(ref) for link, _ in admitted.values() for ref in (link.source_ref, link.target_ref)}
        canon = projector.representatives_for(controller, graph, refs) if refs else {}
        for link, categories in admitted.values():
            for category in sorted(categories, key=lambda c: int(c.pk)):
                label, reversed_edge = projector.edge_pattern_for(category, link)
                left, right = (str(link.target_ref), str(link.source_ref)) if reversed_edge else (str(link.source_ref), str(link.target_ref))
                edge = index.get((canon.get(left, left), canon.get(right, right), str(label), link.role))
                if edge is not None:
                    attach(link, edge, category)
                    break

    for edges in out.values():
        edges.sort(key=lambda edge: (-(edge.created_at.timestamp() if edge.created_at else 0.0), edge.row_id or ""))
    return out


def neighbor_refs(controller: Any, graph: Any, nodes: Iterable[RetrievedNode], spec: TraversalSpec) -> dict[str, list[str]]:
    """The other end of each drawn edge, as representatives — deduplicated, self excluded — keyed by the node's id.

    From the drawing alone: whoever is at the other end of a drawn edge is a
    drawn individual of this view, whatever the claims say today.
    """
    nodes = list(nodes)
    out: dict[str, list[str]] = {}
    for node, edges in ((node, edges) for node in nodes for edges in [drawn_incident(controller, graph, [node], spec)[node.unique_id]]):
        seen: dict[str, None] = {}
        for edge in edges:
            other = edge.target_ref if edge.source_ref == node.unique_id else edge.source_ref
            if other != node.unique_id:
                seen.setdefault(other, None)
        out[node.unique_id] = list(seen)
    return out
