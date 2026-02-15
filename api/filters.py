from typing import List, Optional
import strawberry
from core import models, enums
import strawberry_django as kante
from django.db.models import Q
import kante
from graph_engine import scalars, input_models


@kante.pydantic_input(input_models.PropertyMatch, all_fields=True, description="A property match condition for filtering entities")
class PropertyMatch:
    """The condition to match for a specific property when filtering entities."""


@kante.pydantic_input(input_models.EntityFilters, description="Filter options for querying entities")
class EntityFilter:
    """Filter options for entity queries."""

    ids: Optional[List[scalars.GraphID]] = kante.field(default=None, description="Filter by specific entity IDs")
    has_property: Optional[str] = kante.field(default=None, description="Filter entities that have a specific property")
    search: Optional[str] = kante.field(default=None, description="Full-text search over entity properties")
    matches: Optional[List[PropertyMatch]] = kante.field(default=None, description="Filter entities that match specific property conditions")


@kante.pydantic_input(input_models.EntityPagination, all_fields=True, description="Pagination options for querying entities")
class EntityPaginationInput:
    """Filter options for entity queries."""


@kante.pydantic_input(input_models.StructureFilters, description="Filter options for querying structures")
class StructureFilter:
    """Filter options for structure queries."""

    ids: Optional[List[scalars.GraphID]] = kante.field(default=None, description="Filter by specific structure IDs")
    has_property: Optional[str] = kante.field(default=None, description="Filter structures that have a specific property")
    search: Optional[str] = kante.field(default=None, description="Full-text search over structure properties")
    matches: Optional[List[PropertyMatch]] = kante.field(default=None, description="Filter structures that match specific property conditions")


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

    @kante.filter_field(description="Filter by list of IDs")
    def ids(self, value: list[strawberry.ID], prefix: str) -> Q:
        return Q(**{f"{prefix}__id__in": value})

    @kante.filter_field(description="Full-text search over label and description")
    def search(self, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}label__search": value}) | Q(**{f"{prefix}description__search": value})


@kante.filter_type(models.GraphTableQuery)
class GraphTableQueryFilter(GraphQueryFilter):
    pass

    @kante.filter_field(description="Full-text search over label and description")
    def search(self, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}label__search": value}) | Q(**{f"{prefix}description__search": value})


@kante.filter_type(models.GraphNodesQuery)
class GraphNodesQueryFilter(GraphQueryFilter):
    pass

    @kante.filter_field(description="Full-text search over label and description")
    def search(self, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}label__search": value}) | Q(**{f"{prefix}description__search": value})


@kante.filter_type(models.GraphPairsQuery)
class GraphPairsQueryFilter(GraphQueryFilter):
    pass

    @kante.filter_field(description="Full-text search over label and description")
    def search(self, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}label__search": value}) | Q(**{f"{prefix}description__search": value})


@kante.filter_type(models.GraphPathQuery)
class GraphPathQueryFilter(GraphQueryFilter):
    pass

    @kante.filter_field(description="Full-text search over label and description")
    def search(self, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}label__search": value}) | Q(**{f"{prefix}description__search": value})
