"""Todo lists are product state: they persist, they move, and they never reach the log (C7).

A list is handed to someone, its items carry the objects to work on, and each
object is ticked on its own. Every assertion re-reads the rows: a resolver that
answers without saving must not pass.
"""

import asyncio

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


# ---------------------------------------------------------------- reads that scale


@pytest.fixture
def query_counter(monkeypatch):
    """Counts SQL statements on every thread (the schema's resolvers run on sync_to_async's)."""
    from django.db.backends import utils

    count = {"n": 0}
    original = utils.CursorWrapper._execute

    def counted(self, *args, **kwargs):
        count["n"] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(utils.CursorWrapper, "_execute", counted)
    return count


async def test_list_progress_is_counted_in_the_list_query_not_per_list(api_schema, api_context, query_counter) -> None:
    """`progress` is an annotation: reading it over five lists costs what it costs over one."""
    first = await _list(api_schema, api_context)
    await _item(api_schema, api_context, first, structures=IMAGES[:1])

    query_counter["n"] = 0
    one = await _run(api_schema, api_context, reads.TODO_LISTS_PROGRESS)
    with_one = query_counter["n"]
    assert with_one > 0, "the counter saw no statements: it is not measuring anything"

    for _ in range(4):
        await _item(api_schema, api_context, await _list(api_schema, api_context))
    query_counter["n"] = 0
    five = await _run(api_schema, api_context, reads.TODO_LISTS_PROGRESS)

    assert len(one["todoLists"]) == 1 and len(five["todoLists"]) == 5
    assert query_counter["n"] == with_one
    assert {entry["id"]: entry["progress"] for entry in five["todoLists"]}[first] == {"done": 0, "total": 1}


async def test_an_item_is_found_once_by_an_identifier_it_carries_many_times(api_schema, api_context) -> None:
    todo_list = await _list(api_schema, api_context)
    await _item(api_schema, api_context, todo_list, "three images", structures=IMAGES)

    data = await _run(api_schema, api_context, reads.TODO_ITEMS, filters={"identifier": "@mikro/image"})

    assert [item["title"] for item in data["todoItems"]] == ["three images"]


async def test_identifier_and_object_name_one_object(api_schema, api_context) -> None:
    """An item with image 1 and table 2 does not carry "image 2"."""
    todo_list = await _list(api_schema, api_context)
    await _item(api_schema, api_context, todo_list, "mixed", structures=[IMAGES[0], {"identifier": "@mikro/table", "object": "2"}])

    split = await _run(api_schema, api_context, reads.TODO_ITEMS, filters={"identifier": "@mikro/image", "object": "2"})
    paired = await _run(api_schema, api_context, reads.TODO_ITEMS, filters={"structure": {"identifier": "@mikro/table", "object": "2"}})

    assert split["todoItems"] == []
    assert [item["title"] for item in paired["todoItems"]] == ["mixed"]


async def test_an_object_s_track_is_its_own_rows_only(api_schema, api_context, other_organization: Organization) -> None:
    """One row per item the object is on, with the item's progress instead of its other objects; another tenant's row is not among them."""
    todo_list = await _list(api_schema, api_context)
    first = await _item(api_schema, api_context, todo_list, "Annotate", structures=IMAGES)
    await _item(api_schema, api_context, todo_list, "Review", structures=IMAGES[1:2])
    await _item(api_schema, api_context, todo_list, "Other", structures=IMAGES[2:])
    await _run(api_schema, api_context, writes.SET_TODO_STRUCTURE_STATUS, input={"id": first["structures"][0]["id"], "status": "DONE"})

    @sync_to_async
    def foreign_row() -> None:
        user, _ = User.objects.get_or_create(username="foreign", sub="foreign-sub")
        project = project_models.Project.objects.create(organization=other_organization, name="Theirs", creator=user)
        theirs = todo_models.TodoList.objects.create(project=project, name="Theirs", creator=user)
        item = todo_models.TodoItem.objects.create(list=theirs, title="Theirs", creator=user)
        todo_models.TodoItemStructure.objects.create(item=item, identifier="@mikro/image", object="2")

    await foreign_row()

    rows = (await _run(api_schema, api_context, reads.TODO_TRACK, identifier="@mikro/image", object="2"))["todoItemStructures"]

    assert sorted(row["item"]["title"] for row in rows) == ["Annotate", "Review"]
    assert {row["object"] for row in rows} == {"2"}
    assert {row["item"]["title"]: row["item"]["progress"] for row in rows} == {"Annotate": {"done": 1, "total": 3}, "Review": {"done": 0, "total": 1}}


async def test_the_summary_counts_the_items_the_filter_selects(api_schema, api_context) -> None:
    mine = await _list(api_schema, api_context, assignee="1")
    others = await _list(api_schema, api_context, assignee="someone-else")
    done = await _item(api_schema, api_context, mine, "finished", structures=IMAGES[:1])
    await _item(api_schema, api_context, mine, "started", status="DOING", structures=IMAGES[1:])
    await _item(api_schema, api_context, mine, "waiting")
    await _item(api_schema, api_context, others, "not mine", structures=IMAGES)
    await _run(api_schema, api_context, writes.SET_TODO_STRUCTURE_STATUS, input={"id": done["structures"][0]["id"], "status": "DONE"})

    summary = (await _run(api_schema, api_context, reads.TODO_SUMMARY, filters={"mine": True}))["todoSummary"]

    assert summary == {"todo": 1, "doing": 1, "done": 1, "total": 3, "objects": {"done": 1, "total": 3}}


# ---------------------------------------------------------------- writes that make sense


async def test_marking_all_of_an_item_s_objects_done_at_once_finishes_it(api_schema, api_context) -> None:
    item = await _item(api_schema, api_context, await _list(api_schema, api_context), structures=IMAGES)

    data = await _run(api_schema, api_context, writes.SET_TODO_STRUCTURES_STATUS, input={"ids": [s["id"] for s in item["structures"]], "status": "DONE"})

    (moved,) = data["setTodoStructuresStatus"]
    assert moved["status"] == "DONE"
    assert moved["progress"] == {"done": 3, "total": 3}
    assert await todo_models.TodoItemStructure.objects.filter(item_id=item["id"], done=True, done_by__isnull=False).acount() == 3


async def test_a_bulk_status_change_with_a_foreign_object_changes_nothing(api_schema, api_context, other_organization: Organization) -> None:
    item = await _item(api_schema, api_context, await _list(api_schema, api_context), structures=IMAGES[:1])

    @sync_to_async
    def foreign_row() -> int:
        user, _ = User.objects.get_or_create(username="foreign", sub="foreign-sub")
        project = project_models.Project.objects.create(organization=other_organization, name="Theirs", creator=user)
        theirs = todo_models.TodoList.objects.create(project=project, name="Theirs", creator=user)
        foreign = todo_models.TodoItem.objects.create(list=theirs, title="Theirs", creator=user)
        return todo_models.TodoItemStructure.objects.create(item=foreign, identifier="@mikro/image", object="9").pk

    foreign = await foreign_row()
    result = await api_schema.execute(
        writes.SET_TODO_STRUCTURES_STATUS,
        variable_values={"input": {"ids": [item["structures"][0]["id"], str(foreign)], "status": "DONE"}},
        context_value=api_context,
    )

    assert result.errors
    assert await todo_models.TodoItemStructure.objects.filter(done=True).acount() == 0


async def test_assigning_an_item_changes_only_who_it_is_for(api_schema, api_context) -> None:
    todo_list = await _list(api_schema, api_context, assignee="tiago")
    created = await _run(api_schema, api_context, writes.CREATE_TODO_ITEM, input={"list": todo_list, "title": "Annotate", "description": "carefully"})
    item_id = created["createTodoItem"]["id"]

    assigned = (await _run(api_schema, api_context, writes.ASSIGN_TODO_ITEM, input={"id": item_id, "assignee": "maria"}))["assignTodoItem"]
    assert (assigned["title"], assigned["assignee"], assigned["effectiveAssignee"]) == ("Annotate", "maria", "maria")
    assert (await todo_models.TodoItem.objects.aget(pk=item_id)).description == "carefully"

    unassigned = (await _run(api_schema, api_context, writes.ASSIGN_TODO_ITEM, input={"id": item_id}))["assignTodoItem"]
    assert (unassigned["assignee"], unassigned["effectiveAssignee"]) == (None, "tiago")

    relisted = (await _run(api_schema, api_context, writes.ASSIGN_TODO_LIST, input={"id": todo_list, "assignee": "maria"}))["assignTodoList"]
    assert relisted["assignee"] == "maria"


async def test_an_item_moves_onto_another_list(api_schema, api_context) -> None:
    source, target = await _list(api_schema, api_context), await _list(api_schema, api_context)
    item = await _item(api_schema, api_context, source, structures=IMAGES[:1])

    await _run(api_schema, api_context, writes.MOVE_TODO_ITEM, input={"id": item["id"], "status": "DOING", "index": 0, "list": target})

    moved = await todo_models.TodoItem.objects.aget(pk=item["id"])
    assert (str(moved.list_id), moved.status, moved.position) == (target, "DOING", 0)


# ---------------------------------------------------------------- live


TODO_CHANGED = """
    subscription TodoChanged($list: ID) {
        todoChanged(list: $list) { kind listId itemId item { id title status progress { done total } } }
    }
"""


async def _next(received, timeout: float = 5) -> dict:
    result = await asyncio.wait_for(received.get(), timeout=timeout)
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    return result.data["todoChanged"]


async def test_a_board_hears_its_items_change_as_they_commit(api_schema, api_context) -> None:
    from tests.support import live
    from todos import channel as todo_channel
    from tests.support.identity import static_identity

    _, org, _ = await sync_to_async(static_identity)()
    todo_list = await _list(api_schema, api_context)
    task, received = await live.subscribe(api_schema, TODO_CHANGED, todo_channel.room(org), {"list": todo_list})
    try:
        item = await _item(api_schema, api_context, todo_list, "Annotate", structures=IMAGES[:1])
        created = await _next(received)
        assert (created["kind"], created["itemId"], created["item"]["title"]) == ("CHANGED", item["id"], "Annotate")

        await _run(api_schema, api_context, writes.SET_TODO_STRUCTURE_STATUS, input={"id": item["structures"][0]["id"], "status": "DONE"})
        ticked = await _next(received)
        assert (ticked["item"]["status"], ticked["item"]["progress"]) == ("DONE", {"done": 1, "total": 1})

        await _run(api_schema, api_context, writes.DELETE_TODO_ITEM, id=item["id"])
        gone = await _next(received)
        assert (gone["kind"], gone["itemId"], gone["item"]) == ("DELETED", item["id"], None)
    finally:
        await live.close(task)


async def test_a_board_does_not_hear_another_list(api_schema, api_context) -> None:
    from tests.support import live
    from todos import channel as todo_channel
    from tests.support.identity import static_identity

    _, org, _ = await sync_to_async(static_identity)()
    watched, other = await _list(api_schema, api_context), await _list(api_schema, api_context)
    task, received = await live.subscribe(api_schema, TODO_CHANGED, todo_channel.room(org), {"list": watched})
    try:
        await _item(api_schema, api_context, other, "Elsewhere")
        await _item(api_schema, api_context, watched, "Here")
        heard = await _next(received)
        assert heard["item"]["title"] == "Here"
        assert received.empty()
    finally:
        await live.close(task)


# ---------------------------------------------------------------- due dates


TODO_ITEMS_DUE = """
    query TodoItems($filters: TodoItemFilter) {
        todoItems(filters: $filters, ordering: [{position: ASC}]) { id title dueAt effectiveDueAt }
    }
"""


async def test_an_item_without_a_date_is_due_when_its_list_is(api_schema, api_context) -> None:
    todo_list = await _list(api_schema, api_context)
    await _run(api_schema, api_context, writes.SCHEDULE_TODO_LIST, input={"id": todo_list, "dueAt": "2026-01-10T12:00:00+00:00"})
    created = await _run(api_schema, api_context, writes.CREATE_TODO_ITEM, input={"list": todo_list, "title": "Annotate", "description": "carefully"})
    item_id = created["createTodoItem"]["id"]

    (item,) = (await _run(api_schema, api_context, TODO_ITEMS_DUE, filters={"ids": [item_id]}))["todoItems"]
    assert item["dueAt"] is None
    assert item["effectiveDueAt"].startswith("2026-01-10")

    scheduled = (await _run(api_schema, api_context, writes.SCHEDULE_TODO_ITEM, input={"id": item_id, "dueAt": "2026-02-01T09:00:00+00:00"}))["scheduleTodoItem"]
    assert scheduled["title"] == "Annotate" and scheduled["effectiveDueAt"].startswith("2026-02-01")
    assert (await todo_models.TodoItem.objects.aget(pk=item_id)).description == "carefully"


async def test_overdue_is_past_due_and_not_done(api_schema, api_context) -> None:
    todo_list = await _list(api_schema, api_context, assignee="1")
    late = await _item(api_schema, api_context, todo_list, "late", dueAt="2020-01-01T00:00:00+00:00")
    finished = await _item(api_schema, api_context, todo_list, "late but done", dueAt="2020-01-01T00:00:00+00:00", structures=IMAGES[:1])
    await _item(api_schema, api_context, todo_list, "in time", dueAt="2999-01-01T00:00:00+00:00")
    await _item(api_schema, api_context, todo_list, "no date")
    await _run(api_schema, api_context, writes.SET_TODO_STRUCTURE_STATUS, input={"id": finished["structures"][0]["id"], "status": "DONE"})

    overdue = (await _run(api_schema, api_context, TODO_ITEMS_DUE, filters={"overdue": True}))["todoItems"]
    dated = (await _run(api_schema, api_context, TODO_ITEMS_DUE, filters={"hasDue": True}))["todoItems"]
    summary = (await _run(api_schema, api_context, reads.TODO_SUMMARY_OVERDUE, filters={"mine": True}))["todoSummary"]

    assert [item["id"] for item in overdue] == [late["id"]]
    assert len(dated) == 3
    assert summary["overdue"] == 1
