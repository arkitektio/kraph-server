"""Assertions about a view's drawing, for tests.

Tests used to assert on the drawing by running Cypher through the Apache AGE
engine. These helpers read the projection tables instead. Tests may: the
one-module fence in `tests/projector/test_projector_protocol.py` scans
production packages only, and a test that checks what a write *drew* is asking
exactly the question these tables answer. Production code goes through the
`Projector` protocol, always.

A vertex stands for one individual as the view sees it (RFC 0018): its `ref`
is the representative, and `ProjectionMember` lists every instance it stands
for. Every helper that takes a ref accepts **any member**, so "does the view
draw this observation" keeps its answer whether or not the observation was
merged into a larger individual.
"""

from __future__ import annotations

from typing import Any

from graph_engine import models


def _vertex_holding(graph: Any, ref: str) -> models.ProjectionVertex | None:
    member = models.ProjectionMember.objects.filter(graph=graph, ref=str(ref)).select_related("vertex").first()
    return member.vertex if member is not None else None


def vertices_with_ref(graph: Any, ref: str) -> int:
    """How many vertices this view draws holding one ref as a member — 0 or 1 by constraint."""
    return models.ProjectionMember.objects.filter(graph=graph, ref=str(ref)).count()


def representative_of(graph: Any, ref: str) -> str | None:
    """The ref of the vertex that stands for `ref` in this view, or None if undrawn."""
    vertex = _vertex_holding(graph, ref)
    return str(vertex.ref) if vertex is not None else None


def members_of(graph: Any, ref: str) -> list[str]:
    """Every instance ref the vertex holding `ref` stands for, sorted; `[]` if undrawn."""
    vertex = _vertex_holding(graph, ref)
    if vertex is None:
        return []
    return sorted(str(member) for member in models.ProjectionMember.objects.filter(vertex=vertex).values_list("ref", flat=True))


def vertex_count(graph: Any, label: str | None = None) -> int:
    queryset = models.ProjectionVertex.objects.filter(graph=graph)
    if label is not None:
        queryset = queryset.filter(label=str(label))
    return queryset.count()


def edge_count(graph: Any, label: str | None = None) -> int:
    queryset = models.ProjectionEdge.objects.filter(graph=graph)
    if label is not None:
        queryset = queryset.filter(label=str(label))
    return queryset.count()


def edges_between(graph: Any, source_ref: str, target_ref: str, label: str | None = None) -> int:
    """Edges between the vertices holding the two refs — either ref may be any member."""
    queryset = models.ProjectionEdge.objects.filter(graph=graph, source__members__ref=str(source_ref), target__members__ref=str(target_ref))
    if label is not None:
        queryset = queryset.filter(label=str(label))
    return queryset.distinct().count()


def edge_properties_between(graph: Any, source_ref: str, target_ref: str, label: str) -> list[dict[str, Any]]:
    """The properties of every edge drawn between the vertices holding the two refs under `label`."""
    queryset = models.ProjectionEdge.objects.filter(graph=graph, label=str(label), source__members__ref=str(source_ref), target__members__ref=str(target_ref)).distinct()
    return [dict(edge.properties or {}) for edge in queryset]


def refs_with_label(graph: Any, label: str) -> list[str]:
    """The **representative** ref of every vertex this view draws under `label`."""
    return [str(ref) for ref in models.ProjectionVertex.objects.filter(graph=graph, label=str(label)).values_list("ref", flat=True)]


def all_vertex_properties(graph: Any) -> dict[str, dict[str, Any]]:
    """Every drawn record's properties, keyed by representative ref — the whole-drawing snapshot."""
    return {record["properties"]["id"]: record["properties"] for record in (vertex_record(graph, ref) for ref in models.ProjectionVertex.objects.filter(graph=graph).values_list("ref", flat=True))}


def edge_property_values(graph: Any, label: str, key: str) -> list[Any]:
    """The value of one property on every edge this view draws under `label`."""
    return [(edge.properties or {}).get(key) for edge in models.ProjectionEdge.objects.filter(graph=graph, label=str(label))]


def vertex_record(graph: Any, ref: str) -> dict[str, Any] | None:
    """The drawn record for the vertex holding `ref` — `{id, label, properties}` — or None if undrawn.

    `properties["id"]` is the representative, which may differ from the ref asked for.
    """
    row = _vertex_holding(graph, ref)
    if row is None:
        return None
    properties = dict(row.properties or {})
    properties["id"] = str(row.ref)
    properties["category_id"] = row.category_pk
    properties["type"] = row.kind
    return {"id": int(row.pk), "label": row.label, "properties": properties}


def vertex_properties(graph: Any, ref: str) -> dict[str, Any]:
    """The drawn record's properties, or `{}` if the view does not draw the ref."""
    record = vertex_record(graph, ref)
    return record["properties"] if record is not None else {}
