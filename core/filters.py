import datetime
import strawberry
from core import models, enums
from strawberry import auto
from typing import Optional
from strawberry_django.filters import FilterLookup
import strawberry_django

print("Test")


@strawberry.input
class IDFilterMixin:
    ids: list[strawberry.ID] | None = strawberry.field(
        default=None, description="Filter by list of IDs"
    )

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
        return queryset.filter(label__contains=self.search)

    def filter_kind(self, queryset, info):
        if self.kind is None:
            return queryset
        return queryset.filter(kind=self.kind)

    def filter_graph(self, queryset, info):
        if self.graph is None:
            return queryset
        return queryset.filter(
            ontology=models.Graph.objects.get(id=self.graph).ontology
        )

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
    
    def filter_name(self, queryset, info):
        if self.name is None:
            return queryset
        return queryset.filter(name__contains=self.name)
    
    def filter_values(self, queryset, info):
        if self.values is None:
            return queryset
        return queryset.filter(value__in=self.values)


@strawberry_django.filter(models.GraphQuery)
class GraphQueryFilter(IDFilterMixin, SearchFilterMixin):
    id: auto


@strawberry_django.filter(models.ScatterPlot)
class ScatterPlotFilter(IDFilterMixin, SearchFilterMixin):
    id: auto


@strawberry_django.filter(models.NodeQuery)
class NodeQueryFilter(IDFilterMixin, SearchFilterMixin):
    id: auto


@strawberry.input(description="Filter for entities in the graph")
class EntityFilter:
    ids: list[strawberry.ID] | None = strawberry.field(
        default=None, description="Filter by list of entity IDs"
    )
    external_ids: list[strawberry.ID] | None = strawberry.field(
        default=None, description="Filter by list of entity IDs"
    )
    search: str | None = strawberry.field(
        default=None, description="Search entities by text"
    )
    tags: list[str] | None = strawberry.field(
        default=None, description="Filter by list of categorie tags"
    )
    graph: strawberry.ID | None = strawberry.field(
        default=None, description="Filter by graph ID"
    )
    categories: list[strawberry.ID] | None = strawberry.field(
        default=None, description="Filter by list of entity categories"
    )
    created_before: datetime.datetime | None = strawberry.field(
        default=None, description="Filter by creation date before this date"
    )
    created_after: datetime.datetime | None = strawberry.field(
        default=None, description="Filter by creation date after this date"
    )
    active: bool | None = strawberry.field(
        default=None, description="Filter by active status"
    )
    
    
@strawberry.input(description="Filter for entities in the graph")
class ReagentFilter:
    ids: list[strawberry.ID] | None = strawberry.field(
        default=None, description="Filter by list of entity IDs"
    )
    external_ids: list[strawberry.ID] | None = strawberry.field(
        default=None, description="Filter by list of entity IDs"
    )
    search: str | None = strawberry.field(
        default=None, description="Search entities by text"
    )
    tags: list[str] | None = strawberry.field(
        default=None, description="Filter by list of categorie tags"
    )
    graph: strawberry.ID | None = strawberry.field(
        default=None, description="Filter by graph ID"
    )
    categories: list[strawberry.ID] | None = strawberry.field(
        default=None, description="Filter by list of entity categories"
    )
    created_before: datetime.datetime | None = strawberry.field(
        default=None, description="Filter by creation date before this date"
    )
    created_after: datetime.datetime | None = strawberry.field(
        default=None, description="Filter by creation date after this date"
    )
    active: bool | None = strawberry.field(
        default=None, description="Filter by active status"
    )
    
    
    
@strawberry.input(description="Filter for entities in the graph")
class NodeFilter:
    graph: strawberry.ID | None = strawberry.field(
        default=None, description="Filter by graph ID"
    )
    category: strawberry.ID | None = strawberry.field(
        default=None, description="Filter by entity kind"
    )
    ids: list[strawberry.ID] | None = strawberry.field(
        default=None, description="Filter by list of entity IDs"
    )
    linked_expression: strawberry.ID | None = strawberry.field(
        default=None, description="Filter by linked expression ID"
    )
    identifier: str | None = strawberry.field(
        default=None, description="Filter by structure identifier"
    )
    object: strawberry.ID | None = strawberry.field(
        default=None, description="Filter by associated object ID"
    )
    search: str | None = strawberry.field(
        default=None, description="Search entities by text"
    )


@strawberry.input(description="Filter for entity relations in the graph")
class EntityRelationFilter:
    graph: strawberry.ID | None = strawberry.field(
        default=None, description="Filter by graph ID"
    )
    kind: strawberry.ID | None = strawberry.field(
        default=None, description="Filter by relation kind"
    )
    ids: list[strawberry.ID] | None = strawberry.field(
        default=None, description="Filter by list of relation IDs"
    )
    linked_expression: strawberry.ID | None = strawberry.field(
        default=None, description="Filter by linked expression ID"
    )
    search: str | None = strawberry.field(
        default=None, description="Search relations by text"
    )
    with_self: bool | None = strawberry.field(
        default=None, description="Include self-relations"
    )
    left_id: strawberry.ID | None = strawberry.field(
        default=None, description="Filter by left entity ID"
    )
    right_id: strawberry.ID | None = strawberry.field(
        default=None, description="Filter by right entity ID"
    )


@strawberry_django.filter(models.Experiment)
class ExperimentFilter(IDFilterMixin, SearchFilterMixin):
    id: auto



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
    graph: strawberry.ID | None = strawberry.field(
        default=None, description="Filter by graph ID"
    )
    kind: strawberry.ID | None = strawberry.field(
        default=None, description="Filter by relation kind"
    )
    ids: list[strawberry.ID] | None = strawberry.field(
        default=None, description="Filter by list of relation IDs"
    )
    linked_expression: strawberry.ID | None = strawberry.field(
        default=None, description="Filter by linked expression ID"
    )
    search: str | None = strawberry.field(
        default=None, description="Search relations by text"
    )


@strawberry.input(description="Filter for entity relations in the graph")
class EdgeFilter:
    graph: strawberry.ID | None = strawberry.field(
        default=None, description="Filter by graph ID"
    )
    kind: strawberry.ID | None = strawberry.field(
        default=None, description="Filter by relation kind"
    )
    ids: list[strawberry.ID] | None = strawberry.field(
        default=None, description="Filter by list of relation IDs"
    )
    search: str | None = strawberry.field(
        default=None, description="Search relations by text"
    )
    with_self: bool | None = strawberry.field(
        default=None, description="Include self-relations"
    )
    left_id: strawberry.ID | None = strawberry.field(
        default=None, description="Filter by left entity ID"
    )
    right_id: strawberry.ID | None = strawberry.field(
        default=None, description="Filter by right entity ID"
    )




@strawberry.input(description="Filter for entity relations in the graph")
class StructureFilter(NodeFilter):
    kind: strawberry.ID | None = strawberry.field(
        default=None, description="Filter by relation kind"
    )


@strawberry.input(description="Filter for entity relations in the graph")
class MetricFilter(NodeFilter):
    kind: strawberry.ID | None = strawberry.field(
        default=None, description="Filter by relation kind"
    )


@strawberry.input(description="Filter for entity relations in the graph")
class NodeEventFilter(NodeFilter):
    kind: strawberry.ID | None = strawberry.field(
        default=None, description="Filter by relation kind"
    )


@strawberry.input(description="Filter for entity relations in the graph")
class ProtocolEventFilter(NodeFilter):
    kind: strawberry.ID | None = strawberry.field(
        default=None, description="Filter by relation kind"
    )


@strawberry.input(description="Filter for entity relations in the graph")
class NaturalEventFilter(NodeFilter):
    kind: strawberry.ID | None = strawberry.field(
        default=None, description="Filter by relation kind"
    )




@strawberry.input(description="Filter for entity relations in the graph")
class ParticipantFilter(EdgeFilter):
    kind: strawberry.ID | None = strawberry.field(
        default=None, description="Filter by relation kind"
    )


@strawberry.input(description="Filter for entity relations in the graph")
class RelationFilter(EdgeFilter):
    kind: strawberry.ID | None = strawberry.field(
        default=None, description="Filter by relation kind"
    )


@strawberry.input(description="Filter for entity relations in the graph")
class MeasurementFilter(EdgeFilter):
    kind: strawberry.ID | None = strawberry.field(
        default=None, description="Filter by relation kind"
    )
