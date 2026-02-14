from typing import Optional
import kante


@kante.input(description="Pagination options for graph queries")
class GraphPaginationInput:
    """Pagination options for graph queries."""

    limit: Optional[int] = kante.field(default=100, description="Maximum number of items to return")
    offset: Optional[int] = kante.field(default=0, description="Number of items to skip before starting to collect the result set")
