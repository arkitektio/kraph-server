"""The GraphQL face of todo lists: types, filters and orders.

Every type is fenced to the request's organization through its project, the way
`api.types.org_scoped` fences graphs — strawberry-django applies `get_queryset`
to root lists, nested prefetches and pk lookups alike.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional, cast

import kante
import strawberry
import strawberry_django
from django.db.models import Count, Q
from django.utils import timezone
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


@strawberry.input(description="One object, named the way a comment names one")
class TodoObjectFilter:
    identifier: str = strawberry.field(description="The object's structure identifier, e.g. @mikro/image")
    object: strawberry.ID = strawberry.field(description="The object's id within its structure")


def _carrying(prefix: str, **lookup: object) -> Q:
    """Items with at least one object matching ``lookup``. A subquery, not a join, so an item is
    never returned once per matching object."""
    return Q(**{f"{prefix}id__in": models.TodoItemStructure.objects.filter(**lookup).values("item_id")})



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

    @kante.filter_field(description="Lists that still hold an item not Done (true), or none (false)")
    def open(self, value: bool, prefix: str) -> Q:
        q = Q(**{f"{prefix}id__in": models.TodoItem.objects.exclude(status=models.TodoStatus.DONE).values("list_id")})
        return q if value else ~q

    @kante.filter_field(description="Search the name and description")
    def search(self, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}name__icontains": value}) | Q(**{f"{prefix}description__icontains": value})


def _due_before(moment: datetime, prefix: str = "") -> Q:
    """An item's own due date, else its list's, is before ``moment``."""
    return Q(**{f"{prefix}due_at__lt": moment}) | (Q(**{f"{prefix}due_at__isnull": True}) & Q(**{f"{prefix}list__due_at__lt": moment}))


def overdue_q(now: datetime, prefix: str = "") -> Q:
    """Past its (effective) due date and not Done."""
    return _due_before(now, prefix) & ~Q(**{f"{prefix}status": models.TodoStatus.DONE})


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

    # Given together, `identifier` and `object` name ONE object: both go into the same subquery
    # (two would match an item with an image 4 and a table 4). The filter instance is `self`.

    @kante.filter_field(description="Items that carry this object; pair with `object` (or use `structure`)")
    def identifier(self, value: str, prefix: str) -> Q:
        paired = getattr(self, "object", None)
        if paired not in (None, strawberry.UNSET):
            return _carrying(prefix, identifier=value, object=str(paired))
        return _carrying(prefix, identifier=value)

    @kante.filter_field(description="Items that carry this object; pair with `identifier` (or use `structure`)")
    def object(self, value: strawberry.ID, prefix: str) -> Q:
        if getattr(self, "identifier", None) not in (None, strawberry.UNSET):
            return Q()  # `identifier` matched the pair
        return _carrying(prefix, object=str(value))

    @kante.filter_field(description="Items that carry this object (identifier and object together)")
    def structure(self, value: TodoObjectFilter, prefix: str) -> Q:
        return _carrying(prefix, identifier=value.identifier, object=str(value.object))

    @kante.filter_field(description="Items not Done yet (true), or only Done ones (false)")
    def open(self, value: bool, prefix: str) -> Q:
        q = ~Q(**{f"{prefix}status": models.TodoStatus.DONE})
        return q if value else ~q

    @kante.filter_field(description="Items that are for somebody, their own assignee or their list's (true), or for nobody (false)")
    def assigned(self, value: bool, prefix: str) -> Q:
        nobody = Q(**{f"{prefix}assignee__isnull": True}) & Q(**{f"{prefix}list__assignee__isnull": True})
        return ~nobody if value else nobody

    @kante.filter_field(description="Items changed at or after this time")
    def updated_since(self, value: datetime, prefix: str) -> Q:
        return Q(**{f"{prefix}updated_at__gte": value})

    @kante.filter_field(description="Items due (their own date, else their list's) before this time")
    def due_before(self, value: datetime, prefix: str) -> Q:
        return _due_before(value, prefix)

    @kante.filter_field(description="Items past their due date and not Done (true), or not overdue (false)")
    def overdue(self, value: bool, prefix: str) -> Q:
        q = overdue_q(timezone.now(), prefix)
        return q if value else ~q

    @kante.filter_field(description="Items with a due date, their own or their list's (true), or none (false)")
    def has_due(self, value: bool, prefix: str) -> Q:
        none = Q(**{f"{prefix}due_at__isnull": True}) & Q(**{f"{prefix}list__due_at__isnull": True})
        return ~none if value else none

    @kante.filter_field(description="Search the title and description")
    def search(self, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}title__icontains": value}) | Q(**{f"{prefix}description__icontains": value})


@kante.filter_type(models.TodoItemStructure)
class TodoItemStructureFilter:
    id: auto

    @kante.filter_field(description="Filter by list of IDs")
    def ids(self, value: list[strawberry.ID], prefix: str) -> Q:
        return Q(**{f"{prefix}id__in": value})

    @kante.filter_field(description="This object's rows, one per item it is on; pair with `object`")
    def identifier(self, value: str, prefix: str) -> Q:
        return Q(**{f"{prefix}identifier": value})

    @kante.filter_field(description="This object's rows, one per item it is on; pair with `identifier`")
    def object(self, value: strawberry.ID, prefix: str) -> Q:
        return Q(**{f"{prefix}object": str(value)})

    @kante.filter_field(description="Objects in any of these states")
    def status(self, value: List[TodoStatus], prefix: str) -> Q:
        return Q(**{f"{prefix}status__in": [TodoStatus(status).value for status in value]})

    @kante.filter_field(description="The objects of one item")
    def item(self, value: strawberry.ID, prefix: str) -> Q:
        return Q(**{f"{prefix}item_id": value})

    @kante.filter_field(description="The objects on one list's items")
    def list(self, value: strawberry.ID, prefix: str) -> Q:
        return Q(**{f"{prefix}item__list_id": value})

    @kante.filter_field(description="The objects on one project's items")
    def project(self, value: strawberry.ID, prefix: str) -> Q:
        return Q(**{f"{prefix}item__list__project_id": value})

    @kante.filter_field(description="Objects on items whose effective assignee is this user (a sub)")
    def assignee(self, value: strawberry.ID, prefix: str) -> Q:
        return _assigned_to(str(value), f"{prefix}item__")

    @kante.filter_field(description="Objects on items whose effective assignee is the caller")
    def mine(self, info: kante.Info, value: bool, prefix: str) -> Q:
        return _assigned_to(_sub(info), f"{prefix}item__") if value else Q()


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
    due_at: auto


@strawberry_django.order_type(models.TodoItemStructure)
class TodoItemStructureOrder:
    position: auto
    created_at: auto
    done_at: auto


# ---------------------------------------------------------------- types


@strawberry.type(description="How far along something is: done out of total")
class TodoProgress:
    done: int
    total: int


@strawberry.type(description="Todo items counted by column, and their objects by whether they are done")
class TodoSummary:
    todo: int = strawberry.field(description="Items in To do")
    doing: int = strawberry.field(description="Items in Doing")
    done: int = strawberry.field(description="Items in Done")
    total: int = strawberry.field(description="All items")
    overdue: int = strawberry.field(description="Items past their due date (their own, else their list's) and not Done")
    objects: TodoProgress = strawberry.field(description="The objects on those items: done out of total")


def _progress(row: object, done: str, total: str, related) -> TodoProgress:
    """Read the counts the optimizer annotated; a row that did not come through it (a mutation's
    answer) counts them itself."""
    if hasattr(row, done) and hasattr(row, total):
        return TodoProgress(done=getattr(row, done), total=getattr(row, total))
    rows = related(row)
    return TodoProgress(done=rows.filter(status=models.TodoStatus.DONE).count(), total=rows.count())


@_fenced("project__organization")
@kante.django_type(models.TodoList, filters=TodoListFilter, pagination=True, ordering=TodoListOrder, description="A list of things to do, usually handed to one person")
class TodoList:
    id: strawberry.ID = strawberry_django.field(description="Database ID of the list")
    name: str = strawberry_django.field(description="The name of the list")
    description: Optional[str] = strawberry_django.field(description="What the list is for")
    assignee: Optional[strawberry.ID] = strawberry_django.field(description="The sub of the user the list is assigned to")
    due_at: Optional[datetime] = strawberry_django.field(description="When the list is due; its items without a date of their own follow it")
    created_at: datetime = strawberry_django.field(description="When the list was made")
    project: Project = strawberry_django.field(description="The project the list belongs to")
    items: List["TodoItem"] = strawberry_django.field(description="The list's items")

    @strawberry_django.field(
        annotate={
            "_items_done": Count("items", filter=Q(items__status=models.TodoStatus.DONE), distinct=True),
            "_items_total": Count("items", distinct=True),
        },
        description="Items done, out of all items on the list",
    )
    def progress(self) -> TodoProgress:
        return _progress(self, "_items_done", "_items_total", lambda row: row.items)


@_fenced("item__list__project__organization")
@kante.django_type(
    models.TodoItemStructure,
    filters=TodoItemStructureFilter,
    pagination=True,
    ordering=TodoItemStructureOrder,
    description="An object a todo item is about, with its own To do / Doing / Done",
)
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
    due_at: Optional[datetime] = strawberry_django.field(description="The item's own due date; see `effectiveDueAt`")
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

    @strawberry_django.field(only=["due_at", "list__due_at"], select_related=["list"], description="When the item is due: its own date, else its list's")
    def effective_due_at(self) -> Optional[datetime]:
        item = cast(models.TodoItem, self)
        return item.due_at or item.list.due_at

    @strawberry_django.field(
        annotate={
            "_structures_done": Count("structures", filter=Q(structures__status=models.TodoStatus.DONE), distinct=True),
            "_structures_total": Count("structures", distinct=True),
        },
        description="The item's objects done, out of all of them; read it instead of counting `structures`",
    )
    def progress(self) -> TodoProgress:
        return _progress(self, "_structures_done", "_structures_total", lambda row: row.structures)


# ---------------------------------------------------------------- live


@strawberry.enum(description="What happened to a todo list or item")
class TodoChangeKind(str, Enum):
    CHANGED = "CHANGED"
    DELETED = "DELETED"


@strawberry.type(description="A todo list or item changed: re-read it, or drop it when it was deleted")
class TodoChange:
    kind: TodoChangeKind = strawberry.field(description="Changed (created, edited, moved, ticked) or deleted")
    list_id: strawberry.ID = strawberry.field(description="The list it is on (or the list itself)")
    item_id: Optional[strawberry.ID] = strawberry.field(description="The item, when the change was to one")
    item: Optional[TodoItem] = strawberry.field(description="The item as it is now; null for a list-only change or a deleted item")
