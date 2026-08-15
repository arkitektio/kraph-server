"""Root queries over the organization's vocabulary.

Explicit resolvers, not bare `django_field`s, and that is the whole point. The
old `structureCategories` / `metricCategories` fields had no resolver at all —
their only tenant fence was the client happening to pass `CategoryFilter.graph`.
Kinds have no graph to filter on, so scoping has to happen here or not at all.
"""

from typing import List

import strawberry
from kante.types import Info

from api import context, filters, order, pagination, types
from evidence import models as evidence_models


def terms(
    info: Info,
    filters: filters.TermFilter | None = None,
    ordering: List[order.TermOrder] | None = None,
    pagination: pagination.StructurePaginationInput | None = None,
) -> List[types.Term]:
    """Every word this organization uses.

    Its vocabulary, independent of any graph — which is the point: a claim names
    one of these, so the list is the same whichever view you ask from.
    """
    organization = context.get_active_organization(info)
    return evidence_models.Term.objects.for_organization(organization).order_by("kind", "key")


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
    ordering: List[order.StructureKindOrder] | None = None,
    pagination: pagination.StructurePaginationInput | None = None,
) -> List[types.StructureKind]:
    """Every kind of external datum this organization knows about."""
    organization = context.get_active_organization(info)
    return evidence_models.StructureKind.objects.for_organization(organization).order_by("identifier")


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
    ordering: List[order.MetricKindOrder] | None = None,
    pagination: pagination.StructurePaginationInput | None = None,
) -> List[types.MetricKind]:
    """Every kind of measurement this organization knows about."""
    organization = context.get_active_organization(info)
    return evidence_models.MetricKind.objects.for_organization(organization).select_related("structure_kind").order_by("key")


def metric_kind(info: Info, id: strawberry.ID) -> types.MetricKind:
    """One metric kind, if the caller may see it."""
    organization = context.get_active_organization(info)
    kind = evidence_models.MetricKind.objects.for_organization(organization).filter(id=id).first()
    if kind is None:
        raise ValueError(f"Metric kind not found with id {id}")
    return kind
