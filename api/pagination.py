from typing import Any, Optional

import kante

from graph_engine import input_models

#: Every list defaults to the first hundred and is clamped at a thousand — the
#: same ceiling `changes(afterSeq:)` has always had. `limit` used to be unbounded
#: everywhere else, so `limit: 10000000` was accepted as written.
DEFAULT_LIMIT = input_models.DEFAULT_LIMIT
MAX_LIMIT = input_models.MAX_LIMIT


def window(page: Any, *, default: int = DEFAULT_LIMIT, maximum: int = MAX_LIMIT) -> tuple[int, int]:
    """`(offset, limit)` from a pagination input, its pydantic model, or None.

    Clamped: `offset >= 0`, `1 <= limit <= maximum`. A client asking for more than
    the ceiling gets the ceiling, not an error — a page is a page.
    """
    model = page.to_pydantic() if hasattr(page, "to_pydantic") else page
    offset = max(0, int(getattr(model, "offset", 0) or 0))
    limit = int(getattr(model, "limit", default) or default)
    return offset, max(1, min(limit, maximum))


def slice_window(queryset: Any, page: Any) -> list:
    """`window` applied to a queryset (or any sliceable)."""
    offset, limit = window(page)
    return list(queryset[offset : offset + limit])


@kante.pydantic_input(input_models.EntityPagination, all_fields=True, description="Pagination options for querying entities")
class EntityPaginationInput:
    """Filter options for entity queries."""

    limit: Optional[int] = kante.field(default=100, description="Maximum number of items to return")
    offset: Optional[int] = kante.field(default=0, description="Number of items to skip before starting to collect the result set")


@kante.pydantic_input(input_models.NodePagination, all_fields=True, description="Pagination options for querying nodes")
class NodePaginationInput:
    """Filter options for node queries."""

    limit: Optional[int] = kante.field(default=100, description="Maximum number of items to return")
    offset: Optional[int] = kante.field(default=0, description="Number of items to skip before starting to collect the result set")


@kante.pydantic_input(input_models.StructurePagination, all_fields=True, description="Pagination options for querying structures")
class StructurePaginationInput:
    """Filter options for structure queries."""

    limit: Optional[int] = kante.field(default=100, description="Maximum number of items to return")
    offset: Optional[int] = kante.field(default=0, description="Number of items to skip before starting to collect the result set")


# `MetricPaginationInput` used to sit here, referenced by no root field — see
# `api/queries/metric.py` for why the metric lists take no such arguments.


@kante.pydantic_input(input_models.NaturalEventPagination, all_fields=True, description="Pagination options for querying natural events")
class NaturalEventPaginationInput:
    """Pagination options for natural event queries."""


@kante.pydantic_input(input_models.ProtocolEventPagination, all_fields=True, description="Pagination options for querying protocol events")
class ProtocolEventPaginationInput:
    """Pagination options for protocol event queries."""


@kante.pydantic_input(input_models.MeasurementPagination, all_fields=True, description="Pagination options for querying measurements")
class MeasurementPaginationInput:
    """Pagination options for measurement queries."""


@kante.pydantic_input(input_models.StructureRelationPagination, all_fields=True, description="Pagination options for querying structure relations")
class StructureRelationPaginationInput:
    """Pagination options for structure relation queries."""


@kante.pydantic_input(input_models.RelationPagination, all_fields=True, description="Pagination options for querying relations")
class RelationPaginationInput:
    """Pagination options for relation queries."""


@kante.pydantic_input(input_models.RelationPagination, all_fields=True, description="Pagination options for querying participation claims")
class ParticipationPaginationInput:
    """Pagination options for participation queries — see `filters.ParticipationFilter`."""


@kante.pydantic_input(input_models.StructurePagination, all_fields=True, description="Pagination options for querying the organization's vocabulary")
class VocabularyPaginationInput:
    """Pagination for `terms`, `structureKinds` and `metricKinds`.

    All three took `StructurePaginationInput`, which named the wrong concept:
    a term is a word the organization uses, not a structure. Backed by the same
    pydantic model — the shape is `limit`/`offset` either way — so this is the
    name being made true rather than a behaviour change.
    """

    limit: Optional[int] = kante.field(default=100, description="Maximum number of items to return")
    offset: Optional[int] = kante.field(default=0, description="Number of items to skip before starting to collect the result set")


@kante.pydantic_input(input_models.StructurePagination, all_fields=True, description="Pagination options for reading the log")
class LogPaginationInput:
    """Pagination for `assertions` and `standings` (RFC 0020). The same `limit`/`offset` shape as the vocabulary lists."""

    limit: Optional[int] = kante.field(default=100, description="Maximum number of items to return")
    offset: Optional[int] = kante.field(default=0, description="Number of items to skip before starting to collect the result set")


@kante.input(description="Pagination options for graph queries")
class GraphPaginationInput:
    """Pagination options for graph queries."""

    limit: Optional[int] = kante.field(default=100, description="Maximum number of items to return")
    offset: Optional[int] = kante.field(default=0, description="Number of items to skip before starting to collect the result set")
