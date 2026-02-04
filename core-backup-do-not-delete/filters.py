import datetime
import strawberry
from core import models, enums, scalars
from strawberry import auto
import strawberry_django
from django.db.models import Q

print("Test")


@strawberry.input
class IDFilterMixin:
    ids: list[strawberry.ID] | None = strawberry.field(default=None, description="Filter by list of IDs")

    def filter_ids(self, queryset, info):
        if self.ids is None:
            return queryset
        return queryset.filter(id__in=self.ids)


@strawberry.input
class SearchFilterMixin:
    search: str | None = strawberry.field(default=None, description="Search by text")

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(name__contains=self.search)


@strawberry_django.filter(models.EntityCategory)
class EntityCategoryFilter:
    ids: list[strawberry.ID] | None
    id: auto
    search: str | None
    graph: strawberry.ID | None
    ontology: strawberry.ID | None
    pinned: bool | None
    tags: list[str] | None

    def filter_pinned(self, queryset, info):
        if self.pinned is None:
            return queryset
        return queryset.filter(pinned_by=info.context.request.user)

    def filter_ids(self, queryset, info):
        if self.ids is None:
            return queryset
        return queryset.filter(id__in=self.ids)

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(label__contains=self.search)

    def filter_kind(self, queryset, info):
        if self.kind is None:
            return queryset
        return queryset.filter(kind=self.kind)

    def filter_graph(self, queryset, info):
        if self.graph is None:
            return queryset
        return queryset.filter(graph_id=self.graph)

    def filter_tags(self, queryset, info):
        if self.tags is None:
            return queryset
        return queryset.filter(tags__value__in=self.tags)


@strawberry.input
class NodeCategoryFilter:
    ids: list[strawberry.ID] | None
    id: strawberry.ID | None
    search: str | None
    graph: strawberry.ID | None
    ontology: strawberry.ID | None
    pinned: bool | None

    def filter_pinned(self, queryset, info):
        if self.pinned is None:
            return queryset
        return queryset.filter(pinned_by=info.context.request.user)

    def filter_ids(self, queryset, info):
        if self.ids is None:
            return queryset
        return queryset.filter(id__in=self.ids)

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(label__contains=self.search)

    def filter_kind(self, queryset, info):
        if self.kind is None:
            return queryset
        return queryset.filter(kind=self.kind)

    def filter_graph(self, queryset, info):
        if self.graph is None:
            return queryset
        return queryset.filter(graph_id=self.graph)


@strawberry.input
class EdgeCategoryFilter:
    ids: list[strawberry.ID] | None
    id: strawberry.ID | None
    search: str | None
    graph: strawberry.ID | None
    ontology: strawberry.ID | None
    pinned: bool | None

    def filter_pinned(self, queryset, info):
        if self.pinned is None:
            return queryset
        return queryset.filter(pinned_by=info.context.request.user)

    def filter_ids(self, queryset, info):
        if self.ids is None:
            return queryset
        return queryset.filter(id__in=self.ids)

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(label__contains=self.search)

    def filter_kind(self, queryset, info):
        if self.kind is None:
            return queryset
        return queryset.filter(kind=self.kind)

    def filter_graph(self, queryset, info):
        if self.graph is None:
            return queryset
        return queryset.filter(graph_id=self.graph)


@strawberry_django.filter(models.ReagentCategory)
class ReagentCategoryFilter:
    ids: list[strawberry.ID] | None
    id: auto
    search: str | None
    graph: strawberry.ID | None
    ontology: strawberry.ID | None
    pinned: bool | None

    def filter_pinned(self, queryset, info):
        if self.pinned is None:
            return queryset
        return queryset.filter(pinned_by=info.context.request.user)

    def filter_ids(self, queryset, info):
        if self.ids is None:
            return queryset
        return queryset.filter(id__in=self.ids)

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(label__contains=self.search)

    def filter_kind(self, queryset, info):
        if self.kind is None:
            return queryset
        return queryset.filter(kind=self.kind)

    def filter_graph(self, queryset, info):
        if self.graph is None:
            return queryset
        return queryset.filter(graph_id=self.graph)


@strawberry_django.filter(models.RelationCategory)
class RelationCategoryFilter:
    ids: list[strawberry.ID] | None
    id: auto
    search: str | None
    graph: strawberry.ID | None
    ontology: strawberry.ID | None
    pinned: bool | None
    source_entity: strawberry.ID | None
    target_entity: strawberry.ID | None

    def filter_source_entity(self, queryset, info):
        from core import age

        if self.source_entity is None:
            return queryset

        entity_id = age.to_entity_id(self.source_entity)
        graph_id = age.to_graph_id(self.source_entity)

        entity = age.get_age_entity(graph_id, entity_id)

        category = models.EntityCategory.objects.get(id=entity.category_id)

        return queryset.filter(graph__age_name=graph_id).filter(source_definition__category_filters__contains=str(entity.category_id))

    def filter_target_entity(self, queryset, info):
        from core import age

        if self.target_entity is None:
            return queryset

        entity_id = age.to_entity_id(self.target_entity)
        graph_id = age.to_graph_id(self.target_entity)

        print("hallo")
        entity = age.get_age_entity(graph_id, entity_id)
        category = models.EntityCategory.objects.get(id=entity.category_id)

        return queryset.filter(graph__age_name=graph_id).filter(target_definition__category_filters__contains=str(entity.category_id))

    def filter_pinned(self, queryset, info):
        if self.pinned is None:
            return queryset
        return queryset.filter(pinned_by=info.context.request.user)

    def filter_ids(self, queryset, info):
        if self.ids is None:
            return queryset
        return queryset.filter(id__in=self.ids)

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(label__contains=self.search)

    def filter_kind(self, queryset, info):
        if self.kind is None:
            return queryset
        return queryset.filter(kind=self.kind)

    def filter_graph(self, queryset, info):
        if self.graph is None:
            return queryset
        return queryset.filter(graph_id=self.graph)


@strawberry_django.filter(models.StructureRelationCategory)
class StructureRelationCategoryFilter:
    ids: list[strawberry.ID] | None
    id: auto
    search: str | None
    graph: strawberry.ID | None
    ontology: strawberry.ID | None
    pinned: bool | None
    source_identifier: str | None = None
    target_identifier: str | None = None

    def filter_source_identifier(self, queryset, info):
        if self.source_identifier is None:
            return queryset

        return queryset.filter(Q(source_definition__identifier_filters__contains=self.source_identifier)).distinct()

    def filter_target_identifier(self, queryset, info):
        if self.target_identifier is None:
            return queryset

        return queryset.filter(Q(target_definition__identifier_filters__contains=self.target_identifier)).distinct()

    def filter_pinned(self, queryset, info):
        if self.pinned is None:
            return queryset
        return queryset.filter(pinned_by=info.context.request.user)

    def filter_ids(self, queryset, info):
        if self.ids is None:
            return queryset
        return queryset.filter(id__in=self.ids)

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(identifier__search=self.search)

    def filter_graph(self, queryset, info):
        if self.graph is None:
            return queryset
        return queryset.filter(graph_id=self.graph)


@strawberry_django.filter(models.StructureCategory)
class StructureCategoryFilter:
    ids: list[strawberry.ID] | None
    id: auto
    search: str | None
    graph: strawberry.ID | None
    ontology: strawberry.ID | None
    pinned: bool | None

    def filter_pinned(self, queryset, info):
        if self.pinned is None:
            return queryset
        return queryset.filter(pinned_by=info.context.request.user)

    def filter_ids(self, queryset, info):
        if self.ids is None:
            return queryset
        return queryset.filter(id__in=self.ids)

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(identifier__contains=self.search)

    def filter_kind(self, queryset, info):
        if self.kind is None:
            return queryset
        return queryset.filter(kind=self.kind)

    def filter_graph(self, queryset, info):
        if self.graph is None:
            return queryset
        return queryset.filter(ontology=models.Graph.objects.get(id=self.graph).ontology)

    def filter_ontology(self, queryset, info):
        if self.ontology is None:
            return queryset
        return queryset.filter(ontology_id=self.ontology)


@strawberry_django.filter(models.MetricCategory)
class MetricCategoryFilter:
    ids: list[strawberry.ID] | None
    id: auto
    search: str | None
    graph: strawberry.ID | None
    pinned: bool | None

    def filter_pinned(self, queryset, info):
        if self.pinned is None:
            return queryset
        return queryset.filter(pinned_by=info.context.request.user)

    def filter_ids(self, queryset, info):
        if self.ids is None:
            return queryset
        return queryset.filter(id__in=self.ids)

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(label__contains=self.search)

    def filter_kind(self, queryset, info):
        if self.kind is None:
            return queryset
        return queryset.filter(kind=self.kind)

    def filter_graph(self, queryset, info):
        if self.graph is None:
            return queryset
        return queryset.filter(graph_id=self.graph)


@strawberry_django.filter(models.NaturalEventCategory)
class NaturalEventCategoryFilter:
    ids: list[strawberry.ID] | None
    id: auto
    search: str | None
    graph: strawberry.ID | None
    pinned: bool | None

    def filter_pinned(self, queryset, info):
        if self.pinned is None:
            return queryset
        return queryset.filter(pinned_by=info.context.request.user)

    def filter_ids(self, queryset, info):
        if self.ids is None:
            return queryset
        return queryset.filter(id__in=self.ids)

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(label__contains=self.search)

    def filter_kind(self, queryset, info):
        if self.kind is None:
            return queryset
        return queryset.filter(kind=self.kind)

    def filter_graph(self, queryset, info):
        if self.graph is None:
            return queryset
        return queryset.filter(graph_id=self.graph)


@strawberry_django.filter(models.ProtocolEventCategory)
class ProtocolEventCategoryFilter:
    ids: list[strawberry.ID] | None
    id: auto
    search: str | None
    graph: strawberry.ID | None
    pinned: bool | None

    def filter_pinned(self, queryset, info):
        if self.pinned is None:
            return queryset
        return queryset.filter(pinned_by=info.context.request.user)

    def filter_ids(self, queryset, info):
        if self.ids is None:
            return queryset
        return queryset.filter(id__in=self.ids)

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(label__contains=self.search)

    def filter_kind(self, queryset, info):
        if self.kind is None:
            return queryset
        return queryset.filter(kind=self.kind)

    def filter_graph(self, queryset, info):
        if self.graph is None:
            return queryset
        return queryset.filter(graph_id=self.graph)


@strawberry_django.filter(models.MeasurementCategory)
class MeasurementCategoryFilter:
    ids: list[strawberry.ID] | None
    id: auto
    search: str | None
    graph: strawberry.ID | None
    source_identifier: str | None = None

    def filter_source_identifier(self, queryset, info):
        if self.source_identifier is None:
            return queryset

        return queryset.filter(Q(source_definition__identifier_filters__contains=self.source_identifier)).distinct()

    def filter_ids(self, queryset, info):
        if self.ids is None:
            return queryset
        return queryset.filter(id__in=self.ids)

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(label__contains=self.search)

    def filter_kind(self, queryset, info):
        if self.kind is None:
            return queryset
        return queryset.filter(kind=self.kind)

    def filter_graph(self, queryset, info):
        if self.graph is None:
            return queryset
        return queryset.filter(graph_id=self.graph)

    def filter_ontology(self, queryset, info):
        if self.ontology is None:
            return queryset
        return queryset.filter(ontology_id=self.ontology)


@strawberry_django.filter(models.Graph)
class GraphFilter(IDFilterMixin, SearchFilterMixin):
    id: auto
    pinned: bool | None = None

    def filter_pinned(self, queryset, info):
        if self.pinned is None:
            return queryset
        return queryset.filter(pinned_by=info.context.request.user)


@strawberry_django.filter(models.CategoryTag)
class TagFilter(IDFilterMixin, SearchFilterMixin):
    id: auto
    name: str | None = None
    values: list[str] | None = None

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(value__contains=self.search)

    def filter_name(self, queryset, info):
        if self.name is None:
            return queryset
        return queryset.filter(value__contains=self.name)

    def filter_values(self, queryset, info):
        if self.values is None:
            return queryset
        return queryset.filter(value__in=self.values)


@strawberry_django.filter(models.GraphQuery)
class GraphQueryFilter(IDFilterMixin, SearchFilterMixin):
    id: auto
    pinned: bool | None = None
    kind: enums.ViewKind | None = None
    graph: strawberry.ID | None = None
    relevant_for: strawberry.ID | None = None

    def filter_relevant_for(self, queryset, info):
        if self.relevant_for is None:
            return queryset
        return queryset.filter(relevant_for=self.relevant_for)

    def filter_graph(self, queryset, info):
        if self.graph is None:
            return queryset
        return queryset.filter(graph_id=self.graph)

    def filter_pinned(self, queryset, info):
        if self.pinned is None:
            return queryset
        return queryset.filter(pinned_by=info.context.request.user)

    def filter_kind(self, queryset, info):
        if self.kind is None:
            return queryset
        return queryset.filter(kind=self.kind)


@strawberry_django.filter(models.MaterializedEdge, description="Input for creating a new expression")
class MaterializedEdgeFilter(IDFilterMixin):
    source: strawberry.ID | None
    source_identifier: str | None
    target: strawberry.ID | None
    target_identifier: str | None
    relation: strawberry.ID | None
    search: str | None
    pinned_graph: bool | None

    def filter_search(self, queryset, info):
        if self.search is None or self.search == "":
            return queryset
        return queryset.filter(relation__label__contains=self.search)

    def filter_pinned_graph(self, queryset, info):
        if self.pinned_graph is None:
            return queryset
        return queryset.filter(source__graph__pinned_by=info.context.request.user)

    def filter_source(self, queryset, info):
        if self.source is None:
            return queryset
        return queryset.filter(source_id=self.source)

    def filter_target(self, queryset, info):
        if self.target is None:
            return queryset
        return queryset.filter(target_id=self.target)

    def filter_source_identifier(self, queryset, info):
        if self.source_identifier is None:
            return queryset

        try:
            categories = models.StructureCategory.objects.filter(identifier=self.source_identifier)
        except models.StructureCategory.DoesNotExist:
            return queryset.none()

        return queryset.filter(source__in=categories)

    def filter_target_identifier(self, queryset, info):
        if self.target_identifier is None:
            return queryset

        try:
            categories = models.StructureCategory.objects.filter(identifier=self.target_identifier)
        except models.StructureCategory.DoesNotExist:
            return queryset.none()

        return queryset.filter(target__in=categories)


@strawberry_django.filter(models.ScatterPlot)
class ScatterPlotFilter(IDFilterMixin, SearchFilterMixin):
    id: auto
    graph: strawberry.ID | None

    def filter_graph(self, queryset, info):
        if self.graph is None:
            return queryset
        return queryset.filter(query__graph_id=self.graph)


@strawberry_django.filter(models.NodeQuery)
class NodeQueryFilter(IDFilterMixin, SearchFilterMixin):
    id: auto


@strawberry.input(description="Filter for entities in the graph")
class EntityFilter:
    ids: list[strawberry.ID] | None = strawberry.field(default=None, description="Filter by list of entity IDs")
    external_ids: list[strawberry.ID] | None = strawberry.field(default=None, description="Filter by list of entity IDs")
    search: str | None = strawberry.field(default=None, description="Search entities by text")
    tags: list[str] | None = strawberry.field(default=None, description="Filter by list of categorie tags")
    graph: strawberry.ID | None = strawberry.field(default=None, description="Filter by graph ID")
    categories: list[strawberry.ID] | None = strawberry.field(default=None, description="Filter by list of entity categories")
    created_before: datetime.datetime | None = strawberry.field(default=None, description="Filter by creation date before this date")
    created_after: datetime.datetime | None = strawberry.field(default=None, description="Filter by creation date after this date")
    active: bool | None = strawberry.field(default=None, description="Filter by active status")


@strawberry.input(description="Filter for entities in the graph")
class ReagentFilter:
    ids: list[strawberry.ID] | None = strawberry.field(default=None, description="Filter by list of entity IDs")
    external_ids: list[strawberry.ID] | None = strawberry.field(default=None, description="Filter by list of entity IDs")
    search: str | None = strawberry.field(default=None, description="Search entities by text")
    tags: list[str] | None = strawberry.field(default=None, description="Filter by list of categorie tags")
    graph: strawberry.ID | None = strawberry.field(default=None, description="Filter by graph ID")
    categories: list[strawberry.ID] | None = strawberry.field(default=None, description="Filter by list of entity categories")
    created_before: datetime.datetime | None = strawberry.field(default=None, description="Filter by creation date before this date")
    created_after: datetime.datetime | None = strawberry.field(default=None, description="Filter by creation date after this date")
    active: bool | None = strawberry.field(default=None, description="Filter by active status")


@strawberry.input
class PropertyMatch:
    key: str = strawberry.field(description="The property matching")
    operator: enums.WhereOperator = strawberry.field(description="The operator to use")
    value: scalars.Any = strawberry.field(description="THe value to filter agains")


@strawberry.input
class PropertyOrder:
    key: str = strawberry.field(description="THe property")
    direction: enums.OrderDirection = strawberry.field(description="The order direction")


@strawberry.input(description="Filter for entities in the graph")
class CategoryNodesFilter:
    ids: list[strawberry.ID] | None = strawberry.field(default=None, description="Filter by list of entity IDs")
    search: str | None = strawberry.field(default=None, description="Search entities by text")
    property_matches: list[PropertyMatch] | None = strawberry.field(default=None, description="Property matches that should or should not hold true")


@strawberry.input(description="Filter for entities in the graph")
class CategoryNodesOrder:
    property_order: list[PropertyOrder] | None = strawberry.field(default=None, description="Property matches that should or should not hold true")


@strawberry.input(description="Filter for entity relations in the graph")
class EntityRelationFilter:
    graph: strawberry.ID | None = strawberry.field(default=None, description="Filter by graph ID")
    kind: strawberry.ID | None = strawberry.field(default=None, description="Filter by relation kind")
    ids: list[strawberry.ID] | None = strawberry.field(default=None, description="Filter by list of relation IDs")
    linked_expression: strawberry.ID | None = strawberry.field(default=None, description="Filter by linked expression ID")
    search: str | None = strawberry.field(default=None, description="Search relations by text")
    with_self: bool | None = strawberry.field(default=None, description="Include self-relations")
    left_id: strawberry.ID | None = strawberry.field(default=None, description="Filter by left entity ID")
    right_id: strawberry.ID | None = strawberry.field(default=None, description="Filter by right entity ID")


@strawberry_django.filter(models.GraphSequence)
class GraphSequenceFilter(IDFilterMixin, SearchFilterMixin):
    id: auto


@strawberry_django.filter(models.Model)
class ModelFilter(IDFilterMixin):
    id: auto
    search: str | None

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(name__contains=self.search)


@strawberry.input(description="Filter for entity relations in the graph")
class NodeFilter:
    graph: strawberry.ID | None = strawberry.field(default=None, description="Filter by graph ID")
    kind: strawberry.ID | None = strawberry.field(default=None, description="Filter by relation kind")
    ids: list[strawberry.ID] | None = strawberry.field(default=None, description="Filter by list of relation IDs")
    linked_expression: strawberry.ID | None = strawberry.field(default=None, description="Filter by linked expression ID")
    search: str | None = strawberry.field(default=None, description="Search relations by text")
    property_matches: list[PropertyMatch] | None = strawberry.field(default=None, description="Property matches that should or should not hold true")


@strawberry.input(description="Filter for entity relations in the graph")
class EdgeFilter:
    graph: strawberry.ID | None = strawberry.field(default=None, description="Filter by graph ID")
    kind: strawberry.ID | None = strawberry.field(default=None, description="Filter by relation kind")
    ids: list[strawberry.ID] | None = strawberry.field(default=None, description="Filter by list of relation IDs")
    search: str | None = strawberry.field(default=None, description="Search relations by text")
    with_self: bool | None = strawberry.field(default=None, description="Include self-relations")
    left_id: strawberry.ID | None = strawberry.field(default=None, description="Filter by left entity ID")
    right_id: strawberry.ID | None = strawberry.field(default=None, description="Filter by right entity ID")


@strawberry.input(description="Filter for entity relations in the graph")
class StructureFilter(NodeFilter):
    kind: strawberry.ID | None = strawberry.field(default=None, description="Filter by relation kind")


@strawberry.input(description="Filter for entity relations in the graph")
class MetricFilter(NodeFilter):
    kind: strawberry.ID | None = strawberry.field(default=None, description="Filter by relation kind")


@strawberry.input(description="Filter for entity relations in the graph")
class NodeEventFilter(NodeFilter):
    kind: strawberry.ID | None = strawberry.field(default=None, description="Filter by relation kind")


@strawberry.input(description="Filter for entity relations in the graph")
class ProtocolEventFilter(NodeFilter):
    kind: strawberry.ID | None = strawberry.field(default=None, description="Filter by relation kind")


@strawberry.input(description="Filter for entity relations in the graph")
class EditEventFilter(NodeFilter):
    kind: strawberry.ID | None = strawberry.field(default=None, description="Filter by relation kind")


@strawberry.input(description="Filter for entity relations in the graph")
class NaturalEventFilter(NodeFilter):
    kind: strawberry.ID | None = strawberry.field(default=None, description="Filter by relation kind")


@strawberry.input(description="Filter for entity relations in the graph")
class ParticipantFilter(EdgeFilter):
    kind: strawberry.ID | None = strawberry.field(default=None, description="Filter by relation kind")


@strawberry.input(description="Filter for entity relations in the graph")
class RelationFilter(EdgeFilter):
    kind: strawberry.ID | None = strawberry.field(default=None, description="Filter by relation kind")


@strawberry.input(description="Filter for entity relations in the graph")
class StructureRelationFilter(EdgeFilter):
    kind: strawberry.ID | None = strawberry.field(default=None, description="Filter by relation kind")


@strawberry.input(description="Filter for entity relations in the graph")
class MeasurementFilter(EdgeFilter):
    kind: strawberry.ID | None = strawberry.field(default=None, description="Filter by relation kind")
