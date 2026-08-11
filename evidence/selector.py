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
      "observed_window":  ["2025-01-01", "2025-12-31"]   # measured_at range
    }

``as_of`` is the one that matters scientifically: "the graph as we believed it on
March 3rd" stops being a fork of the data and becomes a filter.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Q, QuerySet

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


def metric_filter(selector: dict[str, Any] | None) -> Q:
    """The predicate a metric must satisfy to be in a projection's scope."""
    predicate = Q()
    if not selector:
        return predicate

    # Structure identifiers, not category keys — a structure kind has no key.
    category_keys = selector.get("category_keys")
    if category_keys:
        predicate &= Q(structure__identifier__in=category_keys)

    assertion_filter = selector.get("assertion_filter") or {}
    for field, column in (("subjects", "assertion__subject__in"), ("app_ids", "assertion__app_id__in"), ("action_names", "assertion__action_name__in")):
        values = assertion_filter.get(field)
        if values:
            predicate &= Q(**{column: values})

    as_of = selector.get("as_of")
    if as_of:
        predicate &= Q(asserted_at__lte=as_of)

    observed_from, observed_to = _parse_window(selector.get("observed_window"))
    if observed_from:
        predicate &= Q(measured_at__gte=observed_from)
    if observed_to:
        predicate &= Q(measured_at__lte=observed_to)

    return predicate


def metrics_for(graph: Any) -> QuerySet[Any]:
    """Every active metric this graph projects, in observation order."""
    return evidence_models.Metric.objects.for_organization(graph.organization).filter(metric_filter(graph.selector), status=evidence_models.LifecycleStatus.ACTIVE).select_related("structure", "structure__kind", "assertion").order_by("measured_at")


def informs_links_for(graph: Any) -> QuerySet[Any]:
    """Every active INFORMS link whose target is a node of this graph.

    Entities are still projection-scoped, so their refs carry the graph name.
    Filtering on that prefix is what keeps one graph's rebuild from touching
    another's nodes.
    """
    return evidence_models.Link.objects.for_organization(graph.organization).filter(
        kind=evidence_models.Link.Kind.INFORMS,
        target_ref__startswith=f"{graph.age_name}:",
        status=evidence_models.LifecycleStatus.ACTIVE,
    )


def entity_refs_informed_by(graph: Any, structure_ids: list[Any]) -> list[str]:
    """Which of this graph's entities the given structures are evidence for.

    The fan-out a new metric triggers, and the reason dirty tracking is cheap:
    one indexed lookup on `(organization, kind, source_ref)` rather than a
    traversal.
    """
    return list(informs_links_for(graph).filter(source_ref__in=[str(structure_id) for structure_id in structure_ids]).values_list("target_ref", flat=True).distinct())
