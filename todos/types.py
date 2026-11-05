"""The GraphQL face of todo lists: types, filters and orders.

Every type is fenced to the request's organization through its project, the way
`api.types.org_scoped` fences graphs — strawberry-django applies `get_queryset`
to root lists, nested prefetches and pk lookups alike.
"""

from datetime import datetime
from typing import List, Optional, cast

import kante
import strawberry
import strawberry_django
from django.db.models import Q
from strawberry import auto

from api.context import get_active_organization
from projects.types import Project
from todos import models
from todos.inputs import TodoStatus


def _sub(info: kante.Info) -> str:
    return str(info.context.request.user.sub)


def _fenced(path: str):
    """Scope a type's rows to the active organization, reached through ``path``."""

    def decorate(cls):
        def get_queryset(cls_, queryset, info, **kwargs):
            return queryset.filter(**{path: get_active_organization(info)})

        cls.get_queryset = classmethod(get_queryset)
        return cls

    return decorate


# ---------------------------------------------------------------- filters


@kante.filter_type(models.TodoList)
class TodoListFilter:
    id: auto

    @kante.filter_field(description="Filter by list of IDs")
    def ids(self, value: list[strawberry.ID], prefix: str) -> Q:
        return Q(**{f"{prefix}id__in": value})

    @kante.filter_field(description="The lists of one project")
    def project(self, value: strawberry.ID, prefix: str) -> Q:
        return Q(**{f"{prefix}project_id": value})

    @kante.filter_field(description="Lists assigned to this user (a sub), or holding an item assigned to them")
    def assignee(self, value: strawberry.ID, prefix: str) -> Q:
        return Q(**{f"{prefix}assignee": value}) | Q(**{f"{prefix}id__in": models.TodoItem.objects.filter(assignee=value).values("list_id")})

    @kante.filter_field(description="Lists assigned to the caller, or holding an item assigned to them")
    def mine(self, info: kante.Info, value: bool, prefix: str) -> Q:
        if not value:
            return Q()
        sub = _sub(info)
        return Q(**{f"{prefix}assignee": sub}) | Q(**{f"{prefix}id__in": models.TodoItem.objects.filter(assignee=sub).values("list_id")})

    @kante.filter_field(description="Search the name and description")
    def search(self, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}name__icontains": value}) | Q(**{f"{prefix}description__icontains": value})


def _assigned_to(sub: str, prefix: str) -> Q:
    """An item's own assignee, else its list's: the item's effective assignee is ``sub``."""
    return Q(**{f"{prefix}assignee": sub}) | (Q(**{f"{prefix}assignee__isnull": True}) & Q(**{f"{prefix}list__assignee": sub}))


@kante.filter_type(models.TodoItem)
class TodoItemFilter:
    id: auto

    @kante.filter_field(description="Filter by list of IDs")
    def ids(self, value: list[strawberry.ID], prefix: str) -> Q:
        return Q(**{f"{prefix}id__in": value})

    @kante.filter_field(description="The items of one list")
    def list(self, value: strawberry.ID, prefix: str) -> Q:
        return Q(**{f"{prefix}list_id": value})

    @kante.filter_field(description="The items of one project")
    def project(self, value: strawberry.ID, prefix: str) -> Q:
        return Q(**{f"{prefix}list__project_id": value})

    @kante.filter_field(description="Items in any of these columns")
    def status(self, value: List[TodoStatus], prefix: str) -> Q:
        return Q(**{f"{prefix}status__in": [TodoStatus(status).value for status in value]})

    @kante.filter_field(description="Items whose effective assignee (their own, else their list's) is this user (a sub)")
    def assignee(self, value: strawberry.ID, prefix: str) -> Q:
        return _assigned_to(str(value), prefix)

    @kante.filter_field(description="Items whose effective assignee is the caller")
    def mine(self, info: kante.Info, value: bool, prefix: str) -> Q:
        return _assigned_to(_sub(info), prefix) if value else Q()

    @kante.filter_field(description="Items that carry this object; pair with `object`")
    def identifier(self, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}structures__identifier": value})

    @kante.filter_field(description="Items that carry this object; pair with `identifier`")
    def object(self, value: strawberry.ID, prefix: str) -> Q:
        return Q(**{f"{prefix}structures__object": value})

    @kante.filter_field(description="Search the title and description")
    def search(self, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}title__icontains": value}) | Q(**{f"{prefix}description__icontains": value})


# ---------------------------------------------------------------- orders


@strawberry_django.order_type(models.TodoList)
class TodoListOrder:
    name: auto
    created_at: auto


@strawberry_django.order_type(models.TodoItem)
class TodoItemOrder:
    position: auto
    created_at: auto
    updated_at: auto


# ---------------------------------------------------------------- types


@strawberry.type(description="How far along something is: done out of total")
class TodoProgress:
    done: int
    total: int


@_fenced("project__organization")
@kante.django_type(models.TodoList, filters=TodoListFilter, pagination=True, ordering=TodoListOrder, description="A list of things to do, usually handed to one person")
class TodoList:
    id: strawberry.ID = strawberry_django.field(description="Database ID of the list")
    name: str = strawberry_django.field(description="The name of the list")
    description: Optional[str] = strawberry_django.field(description="What the list is for")
    assignee: Optional[strawberry.ID] = strawberry_django.field(description="The sub of the user the list is assigned to")
    created_at: datetime = strawberry_django.field(description="When the list was made")
    project: Project = strawberry_django.field(description="The project the list belongs to")
    items: List["TodoItem"] = strawberry_django.field(description="The list's items")

    @strawberry_django.field(description="Items done, out of all items on the list")
    def progress(self) -> TodoProgress:
        items = cast(models.TodoList, self).items
        return TodoProgress(done=items.filter(status=models.TodoStatus.DONE).count(), total=items.count())


@_fenced("item__list__project__organization")
@kante.django_type(models.TodoItemStructure, description="An object a todo item is about, with its own To do / Doing / Done")
class TodoItemStructure:
    id: strawberry.ID = strawberry_django.field(description="Database ID of this object on the item")
    identifier: str = strawberry_django.field(description="The object's structure identifier, e.g. @mikro/image")
    object: strawberry.ID = strawberry_django.field(description="The object's id within its structure")
    started_at: Optional[datetime] = strawberry_django.field(description="When somebody started on it")
    started_by: Optional[strawberry.ID] = strawberry_django.field(description="The sub of who started on it")
    done: bool = strawberry_django.field(description="Whether this object has been dealt with")
    done_at: Optional[datetime] = strawberry_django.field(description="When it was ticked")
    done_by: Optional[strawberry.ID] = strawberry_django.field(description="The sub of who ticked it")
    position: int = strawberry_django.field(description="Its place on the item")
    item: "TodoItem" = strawberry_django.field(description="The item it is on")

    @strawberry_django.field(only=["status"], description="How far along this object is: To do, Doing or Done")
    def status(self) -> TodoStatus:
        return TodoStatus(cast(models.TodoItemStructure, self).status)


@_fenced("list__project__organization")
@kante.django_type(models.TodoItem, filters=TodoItemFilter, pagination=True, ordering=TodoItemOrder, description="One card on a todo board")
class TodoItem:
    id: strawberry.ID = strawberry_django.field(description="Database ID of the item")
    title: str = strawberry_django.field(description="What is to be done")
    description: Optional[str] = strawberry_django.field(description="More about what is to be done")
    position: int = strawberry_django.field(description="Its place within its column, 0 first")
    assignee: Optional[strawberry.ID] = strawberry_django.field(description="The item's own assignee (a sub); see `effectiveAssignee`")
    created_at: datetime = strawberry_django.field(description="When the item was made")
    updated_at: datetime = strawberry_django.field(description="When the item last changed")
    list: TodoList = strawberry_django.field(description="The list the item is on")
    structures: List[TodoItemStructure] = strawberry_django.field(description="The objects the item is about")

    @strawberry_django.field(only=["status"], description="The board column the item is in")
    def status(self) -> TodoStatus:
        return TodoStatus(cast(models.TodoItem, self).status)

    @strawberry_django.field(only=["assignee", "list__assignee"], select_related=["list"], description="Who the item is for: its own assignee, else its list's (a sub)")
    def effective_assignee(self) -> Optional[strawberry.ID]:
        item = cast(models.TodoItem, self)
        return item.assignee or item.list.assignee
