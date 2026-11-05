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
from django.db import transaction
from django.db.models import Max, Model
from django.utils import timezone
from kante.types import Info

from api.context import get_active_organization
from projects.resolvers import fetch_project
from todos import inputs, models, types

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


def _list(info: Info, pk: int) -> models.TodoList:
    return _fetch(info, models.TodoList, pk, "project__organization", "todo list")


def _item(info: Info, pk: int, *, lock: bool = False) -> models.TodoItem:
    return _fetch(info, models.TodoItem, pk, "list__project__organization", "todo item", lock=lock)


def _end_of_column(todo_list: models.TodoList, status: str) -> int:
    last = models.TodoItem.objects.filter(list=todo_list, status=status).aggregate(last=Max("position"))["last"]
    return 0 if last is None else last + 1


def _attach(item: models.TodoItem, structures: Iterable[inputs.TodoStructureInputModel]) -> None:
    last = item.structures.aggregate(last=Max("position"))["last"]
    position = 0 if last is None else last + 1
    for structure in structures:
        _, created = models.TodoItemStructure.objects.get_or_create(
            item=item,
            identifier=structure.identifier,
            object=str(structure.object),
            defaults={"position": position},
        )
        if created:
            position += 1


def _settle(item: models.TodoItem) -> None:
    """Move an item to the column its objects say: all ticked → Done, one open on a Done item → Doing,
    one started on a To do item → Doing."""
    total = item.structures.count()
    if total == 0:
        return
    done = item.structures.filter(done=True).count()
    if done == total and item.status != models.TodoStatus.DONE:
        target = models.TodoStatus.DONE
    elif done < total and item.status == models.TodoStatus.DONE:
        target = models.TodoStatus.DOING
    elif item.status == models.TodoStatus.TODO and item.structures.filter(status=models.TodoStatus.DOING).exists():
        target = models.TodoStatus.DOING
    else:
        return
    item.status = target
    item.position = _end_of_column(item.list, target)
    item.save(update_fields=["status", "position", "updated_at"])


# ---------------------------------------------------------------- lists


def create_todo_list(info: Info, input: inputs.CreateTodoListInput) -> types.TodoList:
    model = input.to_pydantic()
    return models.TodoList.objects.create(
        project=fetch_project(info, model.project),
        name=model.name,
        description=model.description,
        assignee=_named(model.assignee),
        creator=info.context.request.user,
    )


def update_todo_list(info: Info, input: inputs.UpdateTodoListInput) -> types.TodoList:
    model = input.to_pydantic()
    todo_list = _list(info, model.id)
    todo_list.name = model.name
    todo_list.description = model.description
    todo_list.assignee = _named(model.assignee)
    todo_list.save()
    return todo_list


def delete_todo_list(info: Info, input: inputs.TodoIdInput) -> strawberry.ID:
    model = input.to_pydantic()
    _list(info, model.id).delete()
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
            position=_end_of_column(todo_list, status),
            creator=info.context.request.user,
        )
        _attach(item, model.structures or [])
    return item


def update_todo_item(info: Info, input: inputs.UpdateTodoItemInput) -> types.TodoItem:
    model = input.to_pydantic()
    item = _item(info, model.id)
    item.title = model.title
    item.description = model.description
    item.assignee = _named(model.assignee)
    item.save()
    return item


def delete_todo_item(info: Info, input: inputs.TodoIdInput) -> strawberry.ID:
    model = input.to_pydantic()
    _item(info, model.id).delete()
    return strawberry.ID(str(model.id))


def move_todo_item(info: Info, input: inputs.MoveTodoItemInput) -> types.TodoItem:
    """Put an item at ``index`` of a column, renumbering that column from 0."""
    model = input.to_pydantic()
    with transaction.atomic():
        item = _item(info, model.id, lock=True)
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
        item.save(update_fields=["status", "position", "updated_at"])
    return item


def attach_to_todo_item(info: Info, input: inputs.AttachToTodoItemInput) -> types.TodoItem:
    model = input.to_pydantic()
    with transaction.atomic():
        item = _item(info, model.item, lock=True)
        _attach(item, model.structures)
        _settle(item)
    return item


def detach_from_todo_item(info: Info, input: inputs.TodoIdInput) -> types.TodoItem:
    """Take one object off its item. Returns the item."""
    model = input.to_pydantic()
    with transaction.atomic():
        structure = _fetch(info, models.TodoItemStructure, model.id, "item__list__project__organization", "object on a todo item")
        item = _item(info, structure.item_id, lock=True)
        structure.delete()
        _settle(item)
    return item


def _set_structure_status(info: Info, id: int, status: models.TodoStatus) -> types.TodoItem:
    """Move one object to a status, keeping `done` and who/when in step. Returns its item, settled."""
    with transaction.atomic():
        structure = _fetch(info, models.TodoItemStructure, id, "item__list__project__organization", "object on a todo item", lock=True)
        item = _item(info, structure.item_id, lock=True)
        if structure.status != status:
            now, sub = timezone.now(), _sub(info)
            if status == models.TodoStatus.TODO:
                structure.started_at = structure.started_by = None
            elif status == models.TodoStatus.DOING or structure.started_by is None:
                # Started now; going straight to Done counts as started by whoever finished it.
                structure.started_at, structure.started_by = now, sub
            structure.status = status
            structure.done = status == models.TodoStatus.DONE
            structure.done_at = now if structure.done else None
            structure.done_by = sub if structure.done else None
            structure.save(update_fields=["status", "started_at", "started_by", "done", "done_at", "done_by"])
        _settle(item)
    return item


def set_todo_structure_status(info: Info, input: inputs.SetTodoStructureStatusInput) -> types.TodoItem:
    """Move one object on an item to To do, Doing or Done. Returns the item, whose column may have moved."""
    model = input.to_pydantic()
    return _set_structure_status(info, model.id, models.TodoStatus(model.status.value))


def set_todo_structure_done(info: Info, input: inputs.SetTodoStructureDoneInput) -> types.TodoItem:
    """Tick (Done) or untick (To do) one object on an item. Returns the item, whose column may have moved."""
    model = input.to_pydantic()
    return _set_structure_status(info, model.id, models.TodoStatus.DONE if model.done else models.TodoStatus.TODO)
