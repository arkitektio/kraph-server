"""Root queries over the organization's vocabulary.

Explicit resolvers, not bare `django_field`s, and that is the whole point. The
old `structureCategories` / `metricCategories` fields had no resolver at all —
their only tenant fence was the client happening to pass `CategoryFilter.graph`.
Kinds have no graph to filter on, so scoping has to happen here or not at all.

The three list resolvers apply their `filters` and `pagination` and take no
`ordering`. They used to accept all three and apply none — the exact silent
no-op `metrics(metricKindId:)` was stripped of, recorded in
`api/queries/metric.py` — and the order is canonical (a vocabulary reads in word
order), so the honest signature offers the two that are implemented.
"""

from typing import List

from django.db.models import Model, QuerySet

import strawberry
import strawberry_django
from kante.types import Info

from api import context, filters, pagination, types
from evidence import models as evidence_models


def _page[Row: Model](queryset: QuerySet[Row], page: pagination.VocabularyPaginationInput | None) -> list[Row]:
    """The offset/limit window — first hundred by default, clamped at `pagination.MAX_LIMIT`."""
    return pagination.slice_window(queryset, page)


def terms(
    info: Info,
    filters: filters.TermFilter | None = None,
    pagination: pagination.VocabularyPaginationInput | None = None,
) -> List[types.Term]:
    """Every word this organization uses.

    Its vocabulary, independent of any graph — which is the point: a claim names
    one of these, so the list is the same whichever view you ask from.
    """
    organization = context.get_active_organization(info)
    queryset = evidence_models.Term.objects.for_organization(organization).order_by("kind", "key")
    queryset = strawberry_django.filters.apply(filters, queryset, info)
    return _page(queryset, pagination)


def term(info: Info, id: strawberry.ID) -> types.Term:
    """One word, if the caller may see it."""
    organization = context.get_active_organization(info)
    found = evidence_models.Term.objects.for_organization(organization).filter(id=id).first()
    if found is None:
        raise ValueError(f"Term not found with id {id}")
    return found


def structure_kinds(
    info: Info,
    filters: filters.StructureKindFilter | None = None,
    pagination: pagination.VocabularyPaginationInput | None = None,
) -> List[types.StructureKind]:
    """Every kind of external datum this organization knows about."""
    organization = context.get_active_organization(info)
    queryset = evidence_models.StructureKind.objects.for_organization(organization).order_by("identifier")
    queryset = strawberry_django.filters.apply(filters, queryset, info)
    return _page(queryset, pagination)


def structure_kind(info: Info, id: strawberry.ID) -> types.StructureKind:
    """One structure kind, if the caller may see it."""
    organization = context.get_active_organization(info)
    kind = evidence_models.StructureKind.objects.for_organization(organization).filter(id=id).first()
    if kind is None:
        raise ValueError(f"Structure kind not found with id {id}")
    return kind


def metric_kinds(
    info: Info,
    filters: filters.MetricKindFilter | None = None,
    pagination: pagination.VocabularyPaginationInput | None = None,
) -> List[types.MetricKind]:
    """Every kind of measurement this organization knows about."""
    organization = context.get_active_organization(info)
    queryset = evidence_models.MetricKind.objects.for_organization(organization).select_related("structure_kind").order_by("key")
    queryset = strawberry_django.filters.apply(filters, queryset, info)
    return _page(queryset, pagination)


def metric_kind(info: Info, id: strawberry.ID) -> types.MetricKind:
    """One metric kind, if the caller may see it."""
    organization = context.get_active_organization(info)
    kind = evidence_models.MetricKind.objects.for_organization(organization).filter(id=id).first()
    if kind is None:
        raise ValueError(f"Metric kind not found with id {id}")
    return kind
