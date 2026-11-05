"""Todo lists are product state: they persist, they move, and they never reach the log (C7).

A list is handed to someone, its items carry the objects to work on, and each
object is ticked on its own. Every assertion re-reads the rows: a resolver that
answers without saving must not pass.
"""

import kante
import pytest
from asgiref.sync import sync_to_async
from authentikate.models import Organization, User
from kante.context import HttpContext

from evidence import models as evidence_models
from tests.support import reads, writes
from projects import models as project_models
from todos import models as todo_models

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

IMAGES = [{"identifier": "@mikro/image", "object": str(n)} for n in (1, 2, 3)]


async def _run(schema: kante.Schema, context: HttpContext, document: str, **variables) -> dict:
    result = await schema.execute(document, variable_values=variables, context_value=context)
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data is not None
    return result.data


async def _list(schema: kante.Schema, context: HttpContext, assignee: str | None = "tiago") -> str:
    project = await _run(schema, context, writes.CREATE_PROJECT, input={"name": "Annotation round"})
    created = await _run(schema, context, writes.CREATE_TODO_LIST, input={"project": project["createProject"]["id"], "name": "Tiago's images", "assignee": assignee})
    return created["createTodoList"]["id"]


async def _item(schema: kante.Schema, context: HttpContext, todo_list: str, title: str = "Annotate", **extra) -> dict:
    created = await _run(schema, context, writes.CREATE_TODO_ITEM, input={"list": todo_list, "title": title, **extra})
    return created["createTodoItem"]


async def test_an_item_carries_its_objects_and_writes_no_evidence(api_schema, api_context) -> None:
    """Objects are plain (identifier, object) pairs: no Structure is minted, no Assertion recorded.

    Counted across every organization (`all_objects`) on purpose: the claim is that the log
    does not move at all, whichever tenant it would have been written under.
    """
    assertions = await evidence_models.Assertion.all_objects.acount()
    structures = await evidence_models.Structure.all_objects.acount()

    item = await _item(api_schema, api_context, await _list(api_schema, api_context), structures=IMAGES)

    assert [(s["identifier"], s["object"], s["done"]) for s in item["structures"]] == [("@mikro/image", o, False) for o in ("1", "2", "3")]
    assert await todo_models.TodoItemStructure.objects.filter(item_id=item["id"]).acount() == 3
    assert await evidence_models.Assertion.all_objects.acount() == assertions
    assert await evidence_models.Structure.all_objects.acount() == structures


async def test_attaching_an_object_twice_keeps_one(api_schema, api_context) -> None:
    item = await _item(api_schema, api_context, await _list(api_schema, api_context), structures=IMAGES[:1])

    data = await _run(api_schema, api_context, writes.ATTACH_TO_TODO_ITEM, input={"item": item["id"], "structures": IMAGES[:2]})

    assert [s["object"] for s in data["attachToTodoItem"]["structures"]] == ["1", "2"]


async def test_moving_an_item_renumbers_its_new_column(api_schema, api_context) -> None:
    todo_list = await _list(api_schema, api_context)
    a = await _item(api_schema, api_context, todo_list, "a")
    await _item(api_schema, api_context, todo_list, "b")
    c = await _item(api_schema, api_context, todo_list, "c")

    await _run(api_schema, api_context, writes.MOVE_TODO_ITEM, input={"id": a["id"], "status": "DOING", "index": 0})
    await _run(api_schema, api_context, writes.MOVE_TODO_ITEM, input={"id": c["id"], "status": "TODO", "index": 0})

    rows = [row async for row in todo_models.TodoItem.objects.filter(list_id=todo_list).order_by("status", "position").values_list("title", "status", "position")]
    assert rows == [("a", "DOING", 0), ("c", "TODO", 0), ("b", "TODO", 1)]


async def test_ticking_the_last_object_finishes_the_item_and_reopening_one_takes_it_back(api_schema, api_context) -> None:
    item = await _item(api_schema, api_context, await _list(api_schema, api_context), structures=IMAGES[:2])
    first, second = (s["id"] for s in item["structures"])

    ticked = await _run(api_schema, api_context, writes.SET_TODO_STRUCTURE_DONE, input={"id": first, "done": True})
    assert ticked["setTodoStructureDone"]["status"] == "TODO"
    assert ticked["setTodoStructureDone"]["structures"][0]["doneBy"] == "1"

    await _run(api_schema, api_context, writes.SET_TODO_STRUCTURE_DONE, input={"id": second, "done": True})
    assert (await todo_models.TodoItem.objects.aget(pk=item["id"])).status == "DONE"

    await _run(api_schema, api_context, writes.SET_TODO_STRUCTURE_DONE, input={"id": first, "done": False})
    reopened = await todo_models.TodoItem.objects.aget(pk=item["id"])
    assert reopened.status == "DOING"
    assert (await todo_models.TodoItemStructure.objects.aget(pk=first)).done_by is None


async def test_starting_an_object_moves_its_to_do_item_to_doing_and_finishing_keeps_who_started(api_schema, api_context) -> None:
    item = await _item(api_schema, api_context, await _list(api_schema, api_context), structures=IMAGES[:2])
    first, _ = (s["id"] for s in item["structures"])

    started = (await _run(api_schema, api_context, writes.SET_TODO_STRUCTURE_STATUS, input={"id": first, "status": "DOING"}))["setTodoStructureStatus"]
    assert started["status"] == "DOING"
    assert (started["structures"][0]["status"], started["structures"][0]["done"], started["structures"][0]["startedBy"]) == ("DOING", False, "1")

    finished = (await _run(api_schema, api_context, writes.SET_TODO_STRUCTURE_STATUS, input={"id": first, "status": "DONE"}))["setTodoStructureStatus"]
    assert finished["status"] == "DOING"
    assert finished["structures"][0] == {"id": first, "status": "DONE", "done": True, "doneBy": "1", "startedBy": "1"}

    reset = (await _run(api_schema, api_context, writes.SET_TODO_STRUCTURE_DONE, input={"id": first, "done": False}))["setTodoStructureDone"]
    row = await todo_models.TodoItemStructure.objects.aget(pk=first)
    assert (row.status, row.done, row.started_by, row.done_by) == ("TODO", False, None, None)
    assert reset["status"] == "DOING"


async def test_mine_is_the_item_s_assignee_else_its_list_s(api_schema, api_context) -> None:
    """The static token's sub is "1": items for "1" directly, or on a list for "1" with no assignee of their own."""
    for_me = await _list(api_schema, api_context, assignee="1")
    for_someone = await _list(api_schema, api_context, assignee="tiago")
    await _item(api_schema, api_context, for_me, "inherits me")
    await _item(api_schema, api_context, for_me, "handed on", assignee="tiago")
    await _item(api_schema, api_context, for_someone, "handed to me", assignee="1")
    await _item(api_schema, api_context, for_someone, "not mine")

    data = await _run(api_schema, api_context, reads.TODO_ITEMS, filters={"mine": True})

    assert sorted(item["title"] for item in data["todoItems"]) == ["handed to me", "inherits me"]
    assert {item["effectiveAssignee"] for item in data["todoItems"]} == {"1"}


async def test_items_are_found_by_the_object_they_carry(api_schema, api_context) -> None:
    """Once each, however many other objects the item carries: the filter joins its objects once."""
    todo_list = await _list(api_schema, api_context)
    await _item(api_schema, api_context, todo_list, "with image 2", structures=IMAGES)
    await _item(api_schema, api_context, todo_list, "without")

    data = await _run(api_schema, api_context, reads.TODO_ITEMS, filters={"identifier": "@mikro/image", "object": "2"})

    assert [item["title"] for item in data["todoItems"]] == ["with image 2"]


async def test_another_tenant_s_todos_are_neither_listed_nor_movable(api_schema, api_context, other_organization: Organization) -> None:
    @sync_to_async
    def foreign_item() -> todo_models.TodoItem:
        user, _ = User.objects.get_or_create(username="foreign", sub="foreign-sub")
        project = project_models.Project.objects.create(organization=other_organization, name="Theirs", creator=user)
        todo_list = todo_models.TodoList.objects.create(project=project, name="Theirs", creator=user, assignee="1")
        return todo_models.TodoItem.objects.create(list=todo_list, title="Theirs", creator=user)

    item = await foreign_item()

    listed = await _run(api_schema, api_context, reads.TODO_ITEMS, filters={"mine": True})
    assert listed["todoItems"] == []
    assert (await _run(api_schema, api_context, reads.PROJECTS))["projects"] == []

    moved = await api_schema.execute(writes.MOVE_TODO_ITEM, variable_values={"input": {"id": str(item.pk), "status": "DONE", "index": 0}}, context_value=api_context)
    assert moved.errors
    assert (await todo_models.TodoItem.objects.aget(pk=item.pk)).status == "TODO"


async def test_the_board_reads_what_its_pages_ask_for(api_schema, api_context) -> None:
    """The reads the app's pages make, nested as they are there: a list with its progress and cards, a project's lists, an item's place."""
    todo_list = await _list(api_schema, api_context)
    item = await _item(api_schema, api_context, todo_list, "Annotate", structures=IMAGES[:1])
    await _item(api_schema, api_context, todo_list, "Review")
    await _run(api_schema, api_context, writes.SET_TODO_STRUCTURE_DONE, input={"id": item["structures"][0]["id"], "done": True})

    board = (await _run(api_schema, api_context, reads.TODO_LIST_BOARD, id=todo_list))["todoList"]
    assert board["progress"] == {"done": 1, "total": 2}
    assert [(card["title"], card["status"], card["effectiveAssignee"]) for card in board["items"]] == [("Annotate", "DONE", "tiago"), ("Review", "TODO", "tiago")]

    project = (await _run(api_schema, api_context, reads.PROJECT_TODO_LISTS, id=board["project"]["id"]))["project"]
    assert [(entry["id"], entry["progress"]["done"]) for entry in project["todoLists"]] == [(todo_list, 1)]

    read = (await _run(api_schema, api_context, reads.TODO_ITEM_WITH_LIST, id=item["id"]))["todoItem"]
    assert read["list"]["project"]["name"] == "Annotation round"
    assert read["effectiveAssignee"] == "tiago"
