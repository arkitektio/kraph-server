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
    ids: list[strawberry.ID] | None

    def filter_ids(self, queryset, info):
        if self.ids is None:
            return queryset
        return queryset.filter(id__in=self.ids)


@strawberry.input
class SearchFilterMixin:
    search: str | None

    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(name__contains=self.search)



@strawberry.django.filter(models.Reagent)
class ReagentFilter:
    ids: list[strawberry.ID] | None
    search: str | None


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


@strawberry.django.filter(models.ZarrStore)
class ZarrStoreFilter:
    shape: Optional[FilterLookup[int]]



  

@strawberry_django.filter(models.LinkedExpression)
class LinkedExpressionFilter:
    graph: strawberry.ID | None 
    search: str | None 
    pinned: bool | None 
    kind: enums.ExpressionKind | None
    ids: list[strawberry.ID] | None


    def filter_ids(self, queryset, info):
        if self.ids is None:
            return queryset
        return queryset.filter(id__in=self.ids)


    def filter_graph(self, queryset, info):
        if self.graph is None:
            return queryset
        return queryset.filter(graph_id=self.graph)
    
    def filter_search(self, queryset, info):
        if self.search is None:
            return queryset
        return queryset.filter(expression__label__contains=self.search)
    
    def filter_kind(self, queryset, info):
        if self.kind is None:
            return queryset
        return queryset.filter(expression__kind=self.kind)
    
    def filter_pinned(self, queryset, info):
        if self.pinned is None:
            return queryset
        if self.pinned and info.context.request.user:
            try:
                return queryset.filter(pinned_by=info.context.request.user)
            except:
                raise ValueError("User not authenticated")
        return queryset


@strawberry.django.filter(models.Graph)
class GraphFilter(IDFilterMixin, SearchFilterMixin):
    id: auto


@strawberry.input 
class EntityFilter:
    graph: strawberry.ID | None = None
    kind: strawberry.ID | None = None
    ids: list[strawberry.ID] | None = None
    linked_expression: strawberry.ID | None = None
    search: str | None = None

@strawberry.input 
class EntityRelationFilter:
    graph: strawberry.ID | None = None
    kind: strawberry.ID | None = None
    ids: list[strawberry.ID] | None = None
    linked_expression: strawberry.ID | None = None
    search: str | None = None
    with_self: bool | None = None
    left_id: strawberry.ID | None = None
    right_id: strawberry.ID | None = None

@strawberry.django.filter(models.Ontology)
class OntologyFilter(IDFilterMixin, SearchFilterMixin):
    id: auto

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



@strawberry.django.filter(models.ReagentMapping)
class ReagentMappingFilter(IDFilterMixin, SearchFilterMixin):
    id: auto
    protocol: strawberry.ID | None = None

    def filter_protocol(self, queryset, info):
        if self.protocol is None:
            return queryset
        return queryset.filter(protocol_id=self.protocol)