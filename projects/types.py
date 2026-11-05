"""The GraphQL face of projects.

A project is fenced to the request's organization, like every todo type. What
hangs off a project is declared by its own app and reached lazily, so this app
imports none of them.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Annotated, List, Optional

import kante
import strawberry
import strawberry_django
from django.db.models import Q
from strawberry import auto

from api.context import get_active_organization
from projects import models

if TYPE_CHECKING:
    from todos.types import TodoList


def _fenced(cls):
    """Scope the type's rows to the active organization (root lists, nested prefetches and pk lookups)."""

    def get_queryset(cls_, queryset, info, **kwargs):
        return queryset.filter(organization=get_active_organization(info))

    cls.get_queryset = classmethod(get_queryset)
    return cls


@kante.filter_type(models.Project)
class ProjectFilter:
    id: auto

    @kante.filter_field(description="Filter by list of IDs")
    def ids(self, value: list[strawberry.ID], prefix: str) -> Q:
        return Q(**{f"{prefix}id__in": value})

    @kante.filter_field(description="Search the name and description")
    def search(self, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}name__icontains": value}) | Q(**{f"{prefix}description__icontains": value})


@strawberry_django.order_type(models.Project)
class ProjectOrder:
    name: auto
    created_at: auto


@_fenced
@kante.django_type(models.Project, filters=ProjectFilter, pagination=True, ordering=ProjectOrder, description="One piece of work in an organization: the anchor its todo lists hang off")
class Project:
    id: strawberry.ID = strawberry_django.field(description="Database ID of the project")
    name: str = strawberry_django.field(description="The name of the project")
    description: Optional[str] = strawberry_django.field(description="What the project is about")
    created_at: datetime = strawberry_django.field(description="When the project was made")
    todo_lists: List[Annotated["TodoList", strawberry.lazy("todos.types")]] = strawberry_django.field(description="The project's todo lists")
