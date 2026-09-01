"""Assertions about a view's drawing, for tests.

Tests used to assert on the drawing by running Cypher through the Apache AGE
engine. These helpers read the projection tables instead. Tests may: the
one-module fence in `tests/projector/test_projector_protocol.py` scans
production packages only, and a test that checks what a write *drew* is asking
exactly the question these tables answer. Production code goes through the
`Projector` protocol, always.
"""

from __future__ import annotations

from typing import Any

from graph_engine import models


def vertices_with_ref(graph: Any, ref: str) -> int:
    """How many vertices this view draws for one ref — 0 or 1 by constraint."""
    return models.ProjectionVertex.objects.filter(graph=graph, ref=str(ref)).count()


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
    queryset = models.ProjectionEdge.objects.filter(graph=graph, source__ref=str(source_ref), target__ref=str(target_ref))
    if label is not None:
        queryset = queryset.filter(label=str(label))
    return queryset.count()


def refs_with_label(graph: Any, label: str) -> list[str]:
    """The ref of every vertex this view draws under `label`."""
    return [str(ref) for ref in models.ProjectionVertex.objects.filter(graph=graph, label=str(label)).values_list("ref", flat=True)]


def all_vertex_properties(graph: Any) -> dict[str, dict[str, Any]]:
    """Every drawn record's properties, keyed by ref — the whole-drawing snapshot."""
    return {record["properties"]["id"]: record["properties"] for record in (vertex_record(graph, ref) for ref in models.ProjectionVertex.objects.filter(graph=graph).values_list("ref", flat=True))}


def edge_property_values(graph: Any, label: str, key: str) -> list[Any]:
    """The value of one property on every edge this view draws under `label`."""
    return [(edge.properties or {}).get(key) for edge in models.ProjectionEdge.objects.filter(graph=graph, label=str(label))]


def vertex_record(graph: Any, ref: str) -> dict[str, Any] | None:
    """The drawn record for one ref — `{id, label, properties}` — or None if undrawn."""
    row = models.ProjectionVertex.objects.filter(graph=graph, ref=str(ref)).first()
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
