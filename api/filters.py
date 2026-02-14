from typing import List, Optional
import strawberry
from core import models, enums
import strawberry_django as kante
from django.db.models import Q
import kante
from graph_engine import scalars


@strawberry.input(description="Filter options for querying entities")
class EntityFilter:
    """Filter options for entity queries."""

    category: Optional[str] = strawberry.field(default=None, description="Filter by entity kind/type")
    ids: Optional[List[scalars.GraphID]] = strawberry.field(default=None, description="Filter by specific entity IDs")
    has_property: Optional[str] = strawberry.field(default=None, description="Filter entities that have a specific property")
    search: Optional[str] = strawberry.field(default=None, description="Full-text search over entity properties")


@strawberry.input(description="Filter options for querying entities")
class EntityPaginationInput:
    """Filter options for entity queries."""

    offset: Optional[int] = strawberry.field(default=0, description="Number of items to skip")
    limit: Optional[int] = strawberry.field(default=100, description="Maximum number of items to return")


@kante.filter_type(models.Graph)
class GraphFilter:
    id: strawberry.auto
    name: strawberry.auto
    description: strawberry.auto

    @kante.filter_field(description="Filter by list of IDs")
    def ids(self, value: list[strawberry.ID], prefix: str) -> Q:
        return Q(**{f"{prefix}__id__in": value})

    @kante.filter_field(description="Filter by list of IDs")
    def search(self, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}name__search": value}) | Q(**{f"{prefix}description__search": value})


@kante.filter_type(models.CategoryTag)
class CategoryTagFilter:
    id: strawberry.auto

    @kante.filter_field(description="Filter by list of IDs")
    def search(self, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}name__search": value}) | Q(**{f"{prefix}description__search": value})


@kante.filter_type(models.Category)
class CategoryFilter:
    graph: GraphFilter | None
    id: strawberry.auto
    label: strawberry.auto

    @kante.filter_field(description="Filter by list of IDs")
    def ids(self, value: list[strawberry.ID], prefix: str) -> Q:
        return Q(**{f"{prefix}__id__in": value})

    @kante.filter_field(description="Filter by list of IDs")
    def pinned(self, info: kante.Info, value: bool, prefix: str) -> Q:
        return Q(**{f"{prefix}__pinned_by": info.context.request.user})

    @kante.filter_field(description="Filter by list of IDs")
    def search(self, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}label__search": value})


@kante.filter_type(models.EntityCategory)
class EntityCategoryFilter(CategoryFilter):
    pass


@kante.filter_type(models.MetricCategory)
class MetricCategoryFilter(CategoryFilter):
    value_kind: enums.ValueKind


@kante.filter_type(models.RelationCategory)
class RelationCategoryFilter(CategoryFilter):
    pass


@kante.filter_type(models.MeasurementCategory)
class MeasurementCategoryFilter(CategoryFilter):
    pass


@kante.filter_type(models.NaturalEventCategory)
class NaturalEventCategoryFilter(CategoryFilter):
    pass


@kante.filter_type(models.ProtocolEventCategory)
class ProtocolEventCategoryFilter(CategoryFilter):
    pass


@kante.filter_type(models.StructureCategory)
class StructureCategoryFilter(CategoryFilter):
    pass


@kante.filter_type(models.StructureRelationCategory)
class StructureRelationCategoryFilter(CategoryFilter):
    pass


@kante.filter_type(models.MaterializedEdge)
class MaterializedEdgeFilter:
    pass


@kante.filter_type(models.GraphQuery)
class GraphQueryFilter:
    pass


@kante.filter_type(models.GraphTableQuery)
class GraphTableQueryFilter:
    pass


@kante.filter_type(models.GraphNodesQuery)
class GraphNodesQueryFilter:
    pass


@kante.filter_type(models.GraphPairsQuery)
class GraphPairsQueryFilter:
    pass


@kante.filter_type(models.GraphPathQuery)
class GraphPathQueryFilter:
    pass
