"""The GraphQL face of pairs query runs and trained models: types, filters and orders.

Every type is fenced to the request's organization, the way the todo types are:
strawberry-django applies `get_queryset` to root lists, nested lists and pk lookups.
"""

from datetime import datetime
from typing import List, Optional, cast

import kante
import strawberry
import strawberry_django
from django.db.models import Q, QuerySet
from strawberry import auto
from strawberry.scalars import JSON

from arkitekt_datalayer.types import BigFileStore

from api.context import get_active_organization
from api.inputs import DescriptorConstraintInput
from datasets import models


def _fenced(path: str):
    """Scope a type's rows to the active organization, reached through ``path``."""

    def decorate(cls):
        def get_queryset(cls_, queryset, info, **kwargs):
            return queryset.filter(**{path: get_active_organization(info)})

        cls.get_queryset = classmethod(get_queryset)
        return cls

    return decorate


@kante.filter_type(models.PairsQueryRun)
class PairsQueryRunFilter:
    id: auto

    @kante.filter_field(description="Filter by list of IDs")
    def ids(self, value: list[strawberry.ID], prefix: str) -> Q:
        return Q(**{f"{prefix}id__in": value})

    @kante.filter_field(description="The runs of one pairs query")
    def query(self, value: strawberry.ID, prefix: str) -> Q:
        return Q(**{f"{prefix}query_id": value})

    @kante.filter_field(description="The runs against one graph (view)")
    def graph(self, value: strawberry.ID, prefix: str) -> Q:
        return Q(**{f"{prefix}graph_id": value})

    @kante.filter_field(description="Runs the server made for a model registered against a query (true), or ones somebody ran (false)")
    def auto(self, value: bool, prefix: str) -> Q:
        return Q(**{f"{prefix}auto": value})

    @kante.filter_field(description="Search the name and description")
    def search(self, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}name__icontains": value}) | Q(**{f"{prefix}description__icontains": value})

    @kante.filter_field(
        description=(
            "Filter to the runs satisfying every one of these descriptor constraints: the `requires` of a port, handed on unchanged, so a picker offers what the port accepts "
            "(e.g. `@kraph/source_identifier` EQUALS `@mikro/arraylens`). Answered in SQL from the descriptors stored on every run. A key a run does not declare is refused rather than ignored"
        )
    )
    def requires(self, info: kante.Info, queryset: QuerySet, value: list[DescriptorConstraintInput], prefix: str) -> tuple[QuerySet, Q]:
        from kraph_server.service import service

        return queryset, service.requires(models.PairsQueryRun, value, prefix)


@strawberry_django.order_type(models.PairsQueryRun)
class PairsQueryRunOrder:
    name: auto
    created_at: auto
    as_of_seq: auto


@kante.filter_type(models.PairsQueryRunEntry)
class PairsQueryRunEntryFilter:
    id: auto

    @kante.filter_field(description="Filter by list of IDs")
    def ids(self, value: list[strawberry.ID], prefix: str) -> Q:
        return Q(**{f"{prefix}id__in": value})


@strawberry_django.order_type(models.PairsQueryRunEntry)
class PairsQueryRunEntryOrder:
    position: auto


@_fenced("run__organization")
@kante.django_type(models.PairsQueryRunEntry, filters=PairsQueryRunEntryFilter, pagination=True, ordering=PairsQueryRunEntryOrder, description="One pair a run answered: a source datum and a target datum")
class PairsQueryRunEntry:
    id: strawberry.ID = strawberry_django.field(description="Database ID of the entry")
    position: int = strawberry_django.field(description="Its place in the run, 0 first")
    source_identifier: str = strawberry_django.field(description="The source datum's structure identifier, e.g. @mikro/arraylens (@kraph/entity for a drawn instance)")
    source_object: strawberry.ID = strawberry_django.field(description="The source datum's id within its structure")
    target_identifier: str = strawberry_django.field(description="The target datum's structure identifier")
    target_object: strawberry.ID = strawberry_django.field(description="The target datum's id within its structure")
    run: "PairsQueryRun" = strawberry_django.field(description="The run it belongs to")


@_fenced("organization")
@kante.django_type(models.PairsQueryRun, filters=PairsQueryRunFilter, pagination=True, ordering=PairsQueryRunOrder, description="A pairs query's answer, stored with where the drawing stood: the exact pairs a model learned from")
class PairsQueryRun:
    id: strawberry.ID = strawberry_django.field(description="Database ID of the run")
    name: str = strawberry_django.field(description="What the run is called")
    description: Optional[str] = strawberry_django.field(description="What the run is for")
    auto: bool = strawberry_django.field(description="Run by the server for a model registered against the query")
    as_of_seq: int = strawberry_django.field(description="Where the drawing stood: everything the log committed at or below it was drawn")
    plan: JSON = strawberry_django.field(description="The query's plan as it was run")
    schema_hash: Optional[str] = strawberry_django.field(description="The view's schema hash when it was run")
    n_pairs: int = strawberry_django.field(description="How many pairs it holds")
    source_identifier: Optional[str] = strawberry_django.field(description="The structure identifier every source shares; null when they differ")
    target_identifier: Optional[str] = strawberry_django.field(description="The structure identifier every target shares; null when they differ")
    created_at: datetime = strawberry_django.field(description="When the run was made")
    entries: List[PairsQueryRunEntry] = strawberry_django.field(description="The pairs, in the run's order")

    @strawberry_django.field(only=["query_id"], description="The id of the pairs query that was run")
    def query_id(self) -> strawberry.ID:
        return strawberry.ID(str(cast(models.PairsQueryRun, self).query_id))

    @strawberry_django.field(only=["graph_id"], description="The id of the graph (view) the run read")
    def graph_id(self) -> strawberry.ID:
        return strawberry.ID(str(cast(models.PairsQueryRun, self).graph_id))

    @strawberry_django.field(only=["stored_descriptors"], description="What the run says about itself, for a port's `requires`: its view and query, size, position, and the identifiers every pair shares (null when mixed)")
    def descriptors(self) -> JSON:
        return cast(models.PairsQueryRun, self).stored_descriptors or {}


@kante.filter_type(models.TrainedModel)
class ModelFilter:
    id: auto

    @kante.filter_field(description="Filter by list of IDs")
    def ids(self, value: list[strawberry.ID], prefix: str) -> Q:
        return Q(**{f"{prefix}id__in": value})

    @kante.filter_field(description="The models of one framework, e.g. 'care'")
    def framework(self, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}framework": value})

    @kante.filter_field(description="The models trained on one run")
    def trained_on(self, value: strawberry.ID, prefix: str) -> Q:
        return Q(**{f"{prefix}trained_on_id": value})

    @kante.filter_field(description="Search the name and description")
    def search(self, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}name__icontains": value}) | Q(**{f"{prefix}description__icontains": value})

    @kante.filter_field(
        description=(
            "Filter to the models satisfying every one of these descriptor constraints: the `requires` of a port, handed on unchanged (e.g. `@kraph/framework` EQUALS `care`). Answered in SQL from the descriptors stored on every model. A key a model does not declare is refused rather than ignored"
        )
    )
    def requires(self, info: kante.Info, queryset: QuerySet, value: list[DescriptorConstraintInput], prefix: str) -> tuple[QuerySet, Q]:
        from kraph_server.service import service

        return queryset, service.requires(models.TrainedModel, value, prefix)


@strawberry_django.order_type(models.TrainedModel)
class ModelOrder:
    name: auto
    created_at: auto


@_fenced("organization")
@kante.django_type(models.TrainedModel, name="Model", filters=ModelFilter, pagination=True, ordering=ModelOrder, description="A trained model: its weights, and the pairs query run it learned from")
class Model:
    id: strawberry.ID = strawberry_django.field(description="Database ID of the model")
    name: str = strawberry_django.field(description="What the model is called")
    description: Optional[str] = strawberry_django.field(description="What the model does")
    framework: str = strawberry_django.field(description="What the weights are for, e.g. 'care' or 'cellpose'")
    trained_on: Optional[PairsQueryRun] = strawberry_django.field(description="The pairs query run it was trained on; null for weights from elsewhere")
    store: BigFileStore = strawberry_django.field(description="The big file holding the weights")
    parameters: Optional[JSON] = strawberry_django.field(description="How it was trained, as the trainer reported it")
    created_at: datetime = strawberry_django.field(description="When the model was registered")

    @strawberry_django.field(only=["stored_descriptors"], description="What the model says about itself, for a port's `requires`: its framework and what it was trained on (run, query, position, and the identifiers its pairs share; null where none)")
    def descriptors(self) -> JSON:
        return cast(models.TrainedModel, self).stored_descriptors or {}
