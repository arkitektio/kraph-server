from typing import Optional
import kante
from graph_engine import input_models


@kante.pydantic_input(input_models.EntityPagination, all_fields=True, description="Pagination options for querying entities")
class EntityPaginationInput:
    """Filter options for entity queries."""

    limit: Optional[int] = kante.field(default=100, description="Maximum number of items to return")
    offset: Optional[int] = kante.field(default=0, description="Number of items to skip before starting to collect the result set")


@kante.pydantic_input(input_models.StructurePagination, all_fields=True, description="Pagination options for querying structures")
class StructurePaginationInput:
    """Filter options for structure queries."""

    limit: Optional[int] = kante.field(default=100, description="Maximum number of items to return")
    offset: Optional[int] = kante.field(default=0, description="Number of items to skip before starting to collect the result set")


@kante.input(description="Pagination options for graph queries")
class GraphPaginationInput:
    """Pagination options for graph queries."""

    limit: Optional[int] = kante.field(default=100, description="Maximum number of items to return")
    offset: Optional[int] = kante.field(default=0, description="Number of items to skip before starting to collect the result set")
