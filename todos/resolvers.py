"""Writes to todo lists.

Every write fetches its row through the request's organization first — the
client names a primary key and never a tenant, so the row is what authorizes
(`api/mutations/_scoped.py` has the long version). Any member of the
organization may change any list: a todo list is shared work, not somebody's
private plot.

Ticking keeps the board honest: the last open object ticked moves its item to
Done, an object started (Doing) on a To do item moves it to Doing, and an object
reopened (or a new one put) on a Done item moves it back to Doing. Moving a card
by hand never ticks or unticks anything.
"""

from typing import Iterable, Optional, TypeVar

import strawberry
import strawberry_django.filters
from django.db import transaction
from django.db.models import Count, Max, Model, Q
from django.utils import timezone
from kante.types import Info

from api.context import get_active_organization
from projects.resolvers import fetch_project
from todos import inputs, models, types
from todos.channel import announce

# Saves describe a row for the hub (`kraph_server.service`); what a save does not see is restored.
# Every `update_fields` save names `stored_descriptors`, or the description computed on save is dropped.
DESCRIBED = "stored_descriptors"


def _service():
    from kraph_server.service import service

    return service


def _object_signal():
    from kraph_server.service import object_signal

    return object_signal

M = TypeVar("M", bound=Model)


def _sub(info: Info) -> str:
    return str(info.context.request.user.sub)


def _named(sub: Optional[str]) -> Optional[str]:
    """An assignee as stored: an empty string is nobody."""
    return sub or None


def _fetch(info: Info, model: type[M], pk: int, path: str, what: str, *, lock: bool = False) -> M:
    queryset = model.objects.select_for_update() if lock else model.objects.all()
    item = queryset.filter(pk=pk, **{path: get_active_organization(info)}).first()
    if item is None:
        raise ValueError(f"No {what} with id {pk} in this organization")
    return item


def _announce(info: Info, item: models.TodoItem, *, deleted: bool = False) -> None:
    """An item changed (or left): its list's board, the object chips and the dashboards follow."""
    announce(get_active_organization(info), item.list_id, item.pk, deleted=deleted)


def _list(info: Info, pk: int) -> models.TodoList:
    return _fetch(info, models.TodoList, pk, "project__organization", "todo list")


def _item(info: Info, pk: int, *, lock: bool = False) -> models.TodoItem:
    return _fetch(info, models.TodoItem, pk, "list__project__organization", "todo item", lock=lock)


def _end_of_column(todo_list: models.TodoList, status: str) -> int:
    last = models.TodoItem.objects.filter(list=todo_list, status=status).aggregate(last=Max("position"))["last"]
    return 0 if last is None else last + 1


def _attach(item: models.TodoItem, structures: Iterable[inputs.TodoStructureInputModel]) -> None:
    """Put objects on an item, after the ones it has, in two queries however many there are. One
    already on it is left as it is (and keeps its place)."""
    last = item.structures.aggregate(last=Max("position"))["last"]
    start = 0 if last is None else last + 1
    present = set(item.structures.values_list("identifier", "object"))
    fresh: list[models.TodoItemStructure] = []
    for structure in structures:
        key = (structure.identifier, str(structure.object))
        if key in present:
            continue
        present.add(key)
        fresh.append(models.TodoItemStructure(item=item, identifier=key[0], object=key[1], position=start + len(fresh)))
    # A concurrent attach of the same object loses to the unique constraint, quietly.
    models.TodoItemStructure.objects.bulk_create(fresh, ignore_conflicts=True)
    if fresh:
        # A bulk write sends no save signals: describe the new rows and announce each as CREATED.
        created = models.TodoItemStructure.objects.filter(item=item, position__gte=start).select_related("item__list__project__organization")
        service = _service()
        service.restore(created, emit=False)
        for row in created:
            _object_signal().emit(row.pk, organization=row.item.list.project.organization.identifier, descriptors=row.stored_descriptors, kind="CREATED")
        # The item's counts moved.
        service.restore(item)


def _settle(item: models.TodoItem) -> None:
    """Move an item to the column its objects say: all ticked → Done, one open on a Done item → Doing,
    one started on a To do item → Doing."""
    counts = item.structures.aggregate(
        total=Count("id"),
        done=Count("id", filter=Q(done=True)),
        doing=Count("id", filter=Q(status=models.TodoStatus.DOING)),
    )
    total, done = counts["total"], counts["done"]
    if total == 0:
        return
    if done == total and item.status != models.TodoStatus.DONE:
        target = models.TodoStatus.DONE
    elif done < total and item.status == models.TodoStatus.DONE:
        target = models.TodoStatus.DOING
    elif item.status == models.TodoStatus.TODO and counts["doing"]:
        target = models.TodoStatus.DOING
    else:
        return
    item.status = target
    item.position = _end_of_column(item.list, target)
    item.save(update_fields=["status", "position", "updated_at", DESCRIBED])


# ---------------------------------------------------------------- lists


def create_todo_list(info: Info, input: inputs.CreateTodoListInput) -> types.TodoList:
    model = input.to_pydantic()
    todo_list = models.TodoList.objects.create(
        project=fetch_project(info, model.project),
        name=model.name,
        description=model.description,
        assignee=_named(model.assignee),
        due_at=model.due_at,
        creator=info.context.request.user,
    )
    announce(get_active_organization(info), todo_list.pk)
    return todo_list


def update_todo_list(info: Info, input: inputs.UpdateTodoListInput) -> types.TodoList:
    model = input.to_pydantic()
    todo_list = _list(info, model.id)
    todo_list.name = model.name
    todo_list.description = model.description
    todo_list.assignee = _named(model.assignee)
    todo_list.save()
    # Items without an assignee of their own follow the list.
    _service().restore(models.TodoItem.objects.filter(list=todo_list, assignee__isnull=True))
    announce(get_active_organization(info), todo_list.pk)
    return todo_list


def assign_todo_list(info: Info, input: inputs.AssignTodoInput) -> types.TodoList:
    """Change only who a list is for; its items without an assignee of their own follow."""
    model = input.to_pydantic()
    todo_list = _list(info, model.id)
    todo_list.assignee = _named(model.assignee)
    todo_list.save(update_fields=["assignee"])
    _service().restore(models.TodoItem.objects.filter(list=todo_list, assignee__isnull=True))
    announce(get_active_organization(info), todo_list.pk)
    return todo_list


def schedule_todo_list(info: Info, input: inputs.ScheduleTodoInput) -> types.TodoList:
    """Change only when a list is due; its items without a date of their own follow."""
    model = input.to_pydantic()
    todo_list = _list(info, model.id)
    todo_list.due_at = model.due_at
    todo_list.save(update_fields=["due_at"])
    announce(get_active_organization(info), todo_list.pk)
    return todo_list


def delete_todo_list(info: Info, input: inputs.TodoIdInput) -> strawberry.ID:
    model = input.to_pydantic()
    _list(info, model.id).delete()
    announce(get_active_organization(info), model.id, deleted=True)
    return strawberry.ID(str(model.id))


# ---------------------------------------------------------------- items


def create_todo_item(info: Info, input: inputs.CreateTodoItemInput) -> types.TodoItem:
    model = input.to_pydantic()
    todo_list = _list(info, model.list)
    status = (model.status or inputs.TodoStatus.TODO).value
    with transaction.atomic():
        item = models.TodoItem.objects.create(
            list=todo_list,
            title=model.title,
            description=model.description,
            assignee=_named(model.assignee),
            status=status,
            due_at=model.due_at,
            position=_end_of_column(todo_list, status),
            creator=info.context.request.user,
        )
        _attach(item, model.structures or [])
        _announce(info, item)
    return item


def update_todo_item(info: Info, input: inputs.UpdateTodoItemInput) -> types.TodoItem:
    model = input.to_pydantic()
    item = _item(info, model.id)
    item.title = model.title
    item.description = model.description
    item.assignee = _named(model.assignee)
    item.save()
    _announce(info, item)
    return item


def assign_todo_item(info: Info, input: inputs.AssignTodoInput) -> types.TodoItem:
    """Change only who an item is for; nobody means its list's assignee again."""
    model = input.to_pydantic()
    item = _item(info, model.id)
    item.assignee = _named(model.assignee)
    item.save(update_fields=["assignee", "updated_at", DESCRIBED])
    _announce(info, item)
    return item


def schedule_todo_item(info: Info, input: inputs.ScheduleTodoInput) -> types.TodoItem:
    """Change only when an item is due; no date means its list's again."""
    model = input.to_pydantic()
    item = _item(info, model.id)
    item.due_at = model.due_at
    item.save(update_fields=["due_at", "updated_at", DESCRIBED])
    _announce(info, item)
    return item


def delete_todo_item(info: Info, input: inputs.TodoIdInput) -> strawberry.ID:
    model = input.to_pydantic()
    item = _item(info, model.id)
    item.delete()
    announce(get_active_organization(info), item.list_id, model.id, deleted=True)
    return strawberry.ID(str(model.id))


def move_todo_item(info: Info, input: inputs.MoveTodoItemInput) -> types.TodoItem:
    """Put an item at ``index`` of a column (of another list, when ``list`` names one), renumbering
    that column from 0."""
    model = input.to_pydantic()
    with transaction.atomic():
        item = _item(info, model.id, lock=True)
        if model.list is not None and model.list != item.list_id:
            # The old board loses the card.
            announce(get_active_organization(info), item.list_id, item.pk, deleted=True)
            item.list = _list(info, model.list)
            moved_lists = True
        else:
            moved_lists = False
        column = list(
            models.TodoItem.objects.select_for_update()
            .filter(list_id=item.list_id, status=model.status.value)
            .exclude(pk=item.pk)
            .order_by("position", "created_at")
        )
        column.insert(min(model.index, len(column)), item)
        item.status = model.status.value
        for position, card in enumerate(column):
            card.position = position
        models.TodoItem.objects.bulk_update([card for card in column if card.pk != item.pk], ["position"])
        item.save(update_fields=["list", "status", "position", "updated_at", DESCRIBED])
        if moved_lists:
            # Its objects now name another list and project; not news to announce per object.
            _service().restore(item.structures.all(), emit=False)
        _announce(info, item)
    return item


def attach_to_todo_item(info: Info, input: inputs.AttachToTodoItemInput) -> types.TodoItem:
    model = input.to_pydantic()
    with transaction.atomic():
        item = _item(info, model.item, lock=True)
        _attach(item, model.structures)
        _settle(item)
        _announce(info, item)
    return item


def detach_from_todo_item(info: Info, input: inputs.TodoIdInput) -> types.TodoItem:
    """Take one object off its item. Returns the item."""
    model = input.to_pydantic()
    with transaction.atomic():
        structure = _fetch(info, models.TodoItemStructure, model.id, "item__list__project__organization", "object on a todo item")
        item = _item(info, structure.item_id, lock=True)
        structure.delete()
        _settle(item)
        _service().restore(item)
        _announce(info, item)
    return item


_MOVED_FIELDS = ["status", "started_at", "started_by", "done", "done_at", "done_by", DESCRIBED]


def _move(structure: models.TodoItemStructure, status: models.TodoStatus, now, sub: str) -> None:
    """Move one object to ``status`` in memory, keeping `done` and who/when in step (saved by the caller)."""
    if status == models.TodoStatus.TODO:
        structure.started_at = structure.started_by = None
    elif status == models.TodoStatus.DOING or structure.started_by is None:
        # Started now; going straight to Done counts as started by whoever finished it.
        structure.started_at, structure.started_by = now, sub
    structure.status = status
    structure.done = status == models.TodoStatus.DONE
    structure.done_at = now if structure.done else None
    structure.done_by = sub if structure.done else None


def _set_structure_status(info: Info, id: int, status: models.TodoStatus) -> types.TodoItem:
    """Move one object to a status, keeping `done` and who/when in step. Returns its item, settled."""
    with transaction.atomic():
        structure = _fetch(info, models.TodoItemStructure, id, "item__list__project__organization", "object on a todo item", lock=True)
        item = _item(info, structure.item_id, lock=True)
        if structure.status != status:
            _move(structure, status, timezone.now(), _sub(info))
            structure.save(update_fields=_MOVED_FIELDS)
        _settle(item)
        # Its counts moved even when its column did not.
        _service().restore(item)
        _announce(info, item)
    return item


def set_todo_structure_status(info: Info, input: inputs.SetTodoStructureStatusInput) -> types.TodoItem:
    """Move one object on an item to To do, Doing or Done. Returns the item, whose column may have moved."""
    model = input.to_pydantic()
    return _set_structure_status(info, model.id, models.TodoStatus(model.status.value))


def set_todo_structure_done(info: Info, input: inputs.SetTodoStructureDoneInput) -> types.TodoItem:
    """Tick (Done) or untick (To do) one object on an item. Returns the item, whose column may have moved."""
    model = input.to_pydantic()
    return _set_structure_status(info, model.id, models.TodoStatus.DONE if model.done else models.TodoStatus.TODO)


def set_todo_structures_status(info: Info, input: inputs.SetTodoStructuresStatusInput) -> list[types.TodoItem]:
    """Move several objects to one status at once ("mark all done"). Every id must be of this
    organization, or nothing changes. Each touched item settles once. Returns the touched items."""
    model = input.to_pydantic()
    status = models.TodoStatus(model.status.value)
    wanted = set(model.ids)
    with transaction.atomic():
        rows = list(
            models.TodoItemStructure.objects.select_for_update()
            .filter(pk__in=wanted, item__list__project__organization=get_active_organization(info))
            .order_by("pk")
        )
        missing = wanted - {row.pk for row in rows}
        if missing:
            raise ValueError(f"No object on a todo item with id {min(missing)} in this organization")
        items = {
            item.pk: item
            for item in models.TodoItem.objects.select_for_update()
            .filter(pk__in={row.item_id for row in rows})
            .select_related("list")
            .order_by("pk")
        }
        now, sub = timezone.now(), _sub(info)
        changed = [row for row in rows if row.status != status]
        for row in changed:
            _move(row, status, now, sub)
        models.TodoItemStructure.objects.bulk_update(changed, _MOVED_FIELDS)
        service = _service()
        # A bulk write sends no save signals: each changed object is described and announced here.
        service.restore(models.TodoItemStructure.objects.filter(pk__in=[row.pk for row in changed]).select_related("item__list"))
        for item in items.values():
            _settle(item)
            service.restore(item)
            _announce(info, item)
    return list(items.values())


# ---------------------------------------------------------------- reads


def todo_summary(info: Info, filters: Optional[types.TodoItemFilter] = None) -> types.TodoSummary:
    """The items ``filters`` selects (the same filter as `todoItems`), counted by column, and their
    objects by whether they are done: two aggregates, whatever the number of items."""
    queryset = strawberry_django.filters.apply(
        filters,
        models.TodoItem.objects.filter(list__project__organization=get_active_organization(info)),
        info=info,
    )
    counts = queryset.aggregate(
        overdue=Count("id", filter=types.overdue_q(timezone.now())),
        total=Count("id"),
        todo=Count("id", filter=Q(status=models.TodoStatus.TODO)),
        doing=Count("id", filter=Q(status=models.TodoStatus.DOING)),
        done=Count("id", filter=Q(status=models.TodoStatus.DONE)),
    )
    objects = models.TodoItemStructure.objects.filter(item__in=queryset.values("pk")).aggregate(
        total=Count("id"),
        done=Count("id", filter=Q(done=True)),
    )
    return types.TodoSummary(
        todo=counts["todo"],
        doing=counts["doing"],
        done=counts["done"],
        total=counts["total"],
        overdue=counts["overdue"],
        objects=types.TodoProgress(done=objects["done"], total=objects["total"]),
    )
