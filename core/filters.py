import strawberry
from core import models, enums
from koherent.strawberry.filters import ProvenanceFilter
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


@strawberry.django.filter(models.Reagent)
class ReagentFilter:
    ids: list[strawberry.ID] | None = strawberry.field(
        default=None, description="Filter by list of reagent IDs"
    )
    search: str | None = strawberry.field(
        default=None, description="Search reagents by text"
    )

    def filter_ids(self, queryset, info):
        if self.ids is None:
            return queryset
        return queryset.filter(id__in=self.ids)

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(expression__label__contains=self.search)

    def filter_kind(self, queryset, info):
        if self.kind is None:
            return queryset
        return queryset.filter(kind=self.kind)


@strawberry.django.filter(models.Expression)
class ExpressionFilter:
    ids: list[strawberry.ID] | None
    id: auto
    search: str | None
    kind: enums.ExpressionKind | None

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


@strawberry.django.filter(models.Graph)
class GraphFilter(IDFilterMixin, SearchFilterMixin):
    id: auto

@strawberry.django.filter(models.GraphView)
class GraphViewFilter(IDFilterMixin, SearchFilterMixin):
    id: auto


@strawberry.django.filter(models.GraphView)
class GraphQueryFilter(IDFilterMixin, SearchFilterMixin):
    id: auto

@strawberry.django.filter(models.ScatterPlot)
class ScatterPlotFilter(IDFilterMixin, SearchFilterMixin):
    id: auto


@strawberry.django.filter(models.NodeView)
class NodeViewFilter(IDFilterMixin, SearchFilterMixin):
    id: auto


@strawberry.django.filter(models.NodeQuery)
class NodeQueryFilter(IDFilterMixin, SearchFilterMixin):
    id: auto



@strawberry.input(description="Filter for entities in the graph")
class EntityFilter:
    graph: strawberry.ID | None = strawberry.field(
        default=None, description="Filter by graph ID"
    )
    kind: strawberry.ID | None = strawberry.field(
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


@strawberry.django.filter(models.Ontology, description="Filter for ontologies")
class OntologyFilter(IDFilterMixin, SearchFilterMixin):
    id: auto = strawberry.field(description="Filter by ontology ID")


@strawberry.django.filter(models.Protocol)
class ProtocolFilter(IDFilterMixin, SearchFilterMixin):
    id: auto


@strawberry.django.filter(models.Experiment)
class ExperimentFilter(IDFilterMixin, SearchFilterMixin):
    id: auto


@strawberry.django.filter(models.ProtocolStep)
class ProtocolStepFilter(IDFilterMixin, SearchFilterMixin):
    id: auto
    protocol: strawberry.ID | None = None

    def filter_protocol(self, queryset, info):
        if self.protocol is None:
            return queryset
        return queryset.filter(protocol_id=self.protocol)


@strawberry.django.filter(models.ProtocolStepTemplate)
class ProtocolStepTemplateFilter(IDFilterMixin):
    id: auto
    search: str | None

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(name__contains=self.search)


@strawberry.django.filter(models.Model)
class ModelFilter(IDFilterMixin):
    id: auto
    search: str | None

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(name__contains=self.search)


@strawberry.django.filter(models.ReagentMapping)
class ReagentMappingFilter(IDFilterMixin, SearchFilterMixin):
    id: auto
    protocol: strawberry.ID | None = None

    def filter_protocol(self, queryset, info):
        if self.protocol is None:
            return queryset
        return queryset.filter(protocol_id=self.protocol)
