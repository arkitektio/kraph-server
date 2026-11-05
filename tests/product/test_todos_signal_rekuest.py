"""Todo changes reach the hub's rekuest as signals, for triggers to act on.

`@kraph/todoitem` (the card: its column, how many objects are done) and
`@kraph/todoitemstructure` (one object: To do / Doing / Done). The signals go to a real HTTP
server on a local port standing in for rekuest's intake, signed with kraph's instance key.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import kante
import pytest
from arkitekt_service import trust
from asgiref.sync import sync_to_async
from authentikate.models import Organization, User
from joserfc.jwk import OKPKey
from kante.context import HttpContext

from projects import models as project_models
from tests.support import writes
from todos import models as todo_models

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

KRAPH_KEY = OKPKey.generate_key("Ed25519")
REKUEST_KEY = OKPKey.generate_key("Ed25519")
INSTANCE = {
    "PRIVATE_KEY": KRAPH_KEY.as_pem(private=True).decode(),
    "TRUST_JWKS": {"keys": [{**trust.public_jwk(KRAPH_KEY), "service": "kraph"}, {**trust.public_jwk(REKUEST_KEY), "service": "rekuest"}]},
}
IMAGES = [{"identifier": "@mikro/arraydataset", "object": str(n)} for n in (1, 2, 3)]


class _Intake:
    """A local HTTP server recording every POST, as rekuest's signal intake would receive it."""

    def __init__(self) -> None:
        self.received: list[dict] = []
        intake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers["Content-Length"]))
                intake.received.append({"path": self.path, "headers": dict(self.headers), "body": json.loads(body), "raw": body})
                self.send_response(202)
                self.end_headers()

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def bodies(self, identifier: str, kind: str | None = None) -> list[dict]:
        return [r["body"] for r in self.received if r["body"]["identifier"] == identifier and (kind is None or r["body"]["kind"] == kind)]

    def until(self, predicate, timeout: float = 10) -> None:
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert predicate(), f"not received; got {[(r['body']['kind'], r['body']['identifier'], r['body'].get('descriptors')) for r in self.received]}"


@pytest.fixture
def intake(settings):
    server = _Intake()
    settings.REKUEST_SERVICE = {"REKUEST_URL": server.url, "SERVICE": "kraph"}
    settings.INSTANCE = INSTANCE
    yield server
    server.server.shutdown()
    server.server.server_close()


async def _run(schema: kante.Schema, context: HttpContext, document: str, **variables) -> dict:
    result = await schema.execute(document, variable_values=variables, context_value=context)
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    return result.data


async def _item(schema, context, **extra) -> dict:
    project = await _run(schema, context, writes.CREATE_PROJECT, input={"name": "Round"})
    todo_list = await _run(schema, context, writes.CREATE_TODO_LIST, input={"project": project["createProject"]["id"], "name": "Images", "assignee": "tiago"})
    created = await _run(schema, context, writes.CREATE_TODO_ITEM, input={"list": todo_list["createTodoList"]["id"], "title": "Annotate", **extra})
    return created["createTodoItem"]


async def test_putting_objects_on_an_item_signals_each_as_created(api_schema, api_context, intake) -> None:
    item = await _item(api_schema, api_context, structures=IMAGES)

    intake.until(lambda: len(intake.bodies("@kraph/todoitemstructure", "CREATED")) == 3 and intake.bodies("@kraph/todoitem", "CREATED"))
    (card,) = intake.bodies("@kraph/todoitem", "CREATED")
    assert card["object"] == item["id"]
    assert (card["descriptors"]["@kraph/total"], card["descriptors"]["@kraph/assignee"]) == (3, "tiago")
    assert sorted(b["descriptors"]["@kraph/object"] for b in intake.bodies("@kraph/todoitemstructure", "CREATED")) == ["1", "2", "3"]
    # Signed the way rekuest checks it: kraph's instance key, for rekuest, for this path and body.
    first = intake.received[0]
    assert first["path"] == "/agi/signal/kraph"
    assert trust.verify("POST", first["path"], first["raw"], first["headers"]["Authorization"], audience="rekuest").issuer == "kraph"


async def test_ticking_the_last_object_signals_the_object_and_the_finished_item(api_schema, api_context, intake) -> None:
    item = await _item(api_schema, api_context, structures=IMAGES[:2])
    for structure in item["structures"]:
        await _run(api_schema, api_context, writes.SET_TODO_STRUCTURE_STATUS, input={"id": structure["id"], "status": "DONE"})

    def finished() -> bool:
        return any(b["descriptors"]["@kraph/status"] == "DONE" for b in intake.bodies("@kraph/todoitem", "UPDATED"))

    intake.until(finished)
    objects = [b for b in intake.bodies("@kraph/todoitemstructure", "UPDATED") if b["descriptors"]["@kraph/status"] == "DONE"]
    assert sorted(b["object"] for b in objects) == sorted(s["id"] for s in item["structures"])
    assert all(b["descriptors"]["@kraph/done_by"] for b in objects)
    done = [b for b in intake.bodies("@kraph/todoitem", "UPDATED") if b["descriptors"]["@kraph/status"] == "DONE"]
    assert (done[-1]["descriptors"]["@kraph/done"], done[-1]["descriptors"]["@kraph/total"]) == (2, 2)


async def test_a_bulk_tick_signals_every_object(api_schema, api_context, intake) -> None:
    item = await _item(api_schema, api_context, structures=IMAGES)
    await _run(api_schema, api_context, writes.SET_TODO_STRUCTURES_STATUS, input={"ids": [s["id"] for s in item["structures"]], "status": "DONE"})

    intake.until(lambda: len([b for b in intake.bodies("@kraph/todoitemstructure", "UPDATED") if b["descriptors"]["@kraph/status"] == "DONE"]) == 3)
    intake.until(lambda: any(b["descriptors"]["@kraph/status"] == "DONE" for b in intake.bodies("@kraph/todoitem", "UPDATED")))


async def test_a_refused_write_signals_nothing(api_schema, api_context, intake, other_organization: Organization) -> None:
    item = await _item(api_schema, api_context, structures=IMAGES[:1])
    intake.until(lambda: intake.bodies("@kraph/todoitem", "CREATED"))
    time.sleep(0.3)
    before = len(intake.received)

    @sync_to_async
    def foreign_row() -> int:
        user, _ = User.objects.get_or_create(username="foreign", sub="foreign-sub")
        project = project_models.Project.objects.create(organization=other_organization, name="Theirs", creator=user)
        theirs = todo_models.TodoList.objects.create(project=project, name="Theirs", creator=user)
        foreign = todo_models.TodoItem.objects.create(list=theirs, title="Theirs", creator=user)
        return todo_models.TodoItemStructure.objects.create(item=foreign, identifier="@mikro/arraydataset", object="9").pk

    foreign = await foreign_row()
    time.sleep(0.5)
    before = len(intake.received)  # the foreign setup's own signals are not what this is about
    result = await api_schema.execute(
        writes.SET_TODO_STRUCTURES_STATUS,
        variable_values={"input": {"ids": [item["structures"][0]["id"], str(foreign)], "status": "DONE"}},
        context_value=api_context,
    )
    assert result.errors
    time.sleep(1)
    assert len(intake.received) == before


async def test_touching_a_finished_item_does_not_tell_its_triggers_again(api_schema, api_context, intake) -> None:
    """Renamed, rescheduled or dragged within Done: nothing a trigger tests changed, so nothing is sent."""
    item = await _item(api_schema, api_context, structures=IMAGES[:1])
    await _run(api_schema, api_context, writes.SET_TODO_STRUCTURE_STATUS, input={"id": item["structures"][0]["id"], "status": "DONE"})
    intake.until(lambda: any(b["descriptors"]["@kraph/status"] == "DONE" for b in intake.bodies("@kraph/todoitem", "UPDATED")))
    time.sleep(0.5)
    finished = len(intake.bodies("@kraph/todoitem", "UPDATED"))

    await _run(api_schema, api_context, writes.MOVE_TODO_ITEM, input={"id": item["id"], "status": "DONE", "index": 0})
    await _run(api_schema, api_context, writes.SCHEDULE_TODO_ITEM, input={"id": item["id"], "dueAt": "2030-01-01T00:00:00+00:00"})
    time.sleep(1)
    assert len(intake.bodies("@kraph/todoitem", "UPDATED")) == finished

    # Reopened: that is news.
    await _run(api_schema, api_context, writes.SET_TODO_STRUCTURE_STATUS, input={"id": item["structures"][0]["id"], "status": "TODO"})
    intake.until(lambda: len(intake.bodies("@kraph/todoitem", "UPDATED")) > finished)
