"""`Subscription.assertionRecorded` — the log announces each act as it commits (RFC 0020).

A subscriber gets the `Assertion` row after its transaction commits and never
for one that rolled back: the broadcast is `transaction.on_commit`, so a write that
fails after recording its assertion announces nothing. The room is the
organization's — `evidence.channel.room` on both sides — so a tenant hears
its own log and nobody else's.

The listener here is a stub consumer over the in-memory channel layer
(`settings_test.CHANNEL_LAYERS`): `Channel.listen` needs only `channel_layer`,
`channel_name` and `listen_to_channel`, which is what a strawberry
`ChannelsConsumer` provides and what this reproduces without a websocket.
"""

import asyncio
import contextlib
from typing import Any, AsyncIterator

import pytest
from asgiref.sync import sync_to_async
from authentikate.models import Client
from channels.layers import get_channel_layer
from django.db import transaction
from kante.testing import build_ws_context

from evidence import channel, models as evidence_models, writer
from graph_engine.controller import GraphController
from graph_engine.input_models import ProvenanceContext
from tests.api.test_reads_are_tenant_scoped import other_organization  # noqa: F401  (fixture)
from tests.conftest import _static_identity

SUBSCRIPTION = """
    subscription AssertionRecorded {
        assertionRecorded { id seq subject instances { id } }
    }
"""

ASSERT_ENTITY = """
    mutation AssertEntityExists($input: AssertEntityExistsInput!) {
        assertEntityExists(input: $input) { assertion { id seq } instance { id } }
    }
"""


class _StubConsumer:
    """The three things `Channel.listen` reads off a consumer."""

    def __init__(self) -> None:
        self.channel_layer = get_channel_layer()
        self.channel_name = ""

    async def open(self) -> None:
        self.channel_name = await self.channel_layer.new_channel()

    @contextlib.asynccontextmanager
    async def listen_to_channel(self, type: str, *, timeout: float | None = None, groups: Any = ()) -> AsyncIterator[Any]:
        for group in groups:
            await self.channel_layer.group_add(group, self.channel_name)

        async def messages() -> Any:
            while True:
                message = await self.channel_layer.receive(self.channel_name)
                if message.get("type") == type:
                    yield message

        try:
            yield messages()
        finally:
            for group in groups:
                await self.channel_layer.group_discard(group, self.channel_name)


async def _subscribe(api_schema, organization=None):
    """Open the subscription in its own task and hand back what it receives.

    One task drives the generator from start to close: strawberry's extensions
    set contextvars on entry and reset them on exit, and a token reset from a
    different task than the one that set it is an error. Returns once the room
    is registered on the layer, so a write made right after is heard.
    """
    user, org, membership = await sync_to_async(_static_identity)()
    client, _ = await Client.objects.aget_or_create(client_id="oinsoins")
    consumer = _StubConsumer()
    await consumer.open()
    ctx = build_ws_context(consumer=consumer, user=user, organization=organization or org, client=client, membership=membership, token="test", connection_params={"token": "test"})
    received: asyncio.Queue[Any] = asyncio.Queue()

    async def run() -> None:
        stream = await api_schema.subscribe(SUBSCRIPTION, context_value=ctx)
        if not hasattr(stream, "__anext__"):
            await received.put(stream)
            return
        async for result in stream:
            await received.put(result)

    task = asyncio.create_task(run())
    room = channel.room(organization or org)
    for _ in range(200):
        await asyncio.sleep(0.01)
        if task.done() or room in getattr(consumer.channel_layer, "groups", {}):
            break
    if task.done():
        raise AssertionError(f"subscription did not start: {task.exception() or received.get_nowait()}")
    return task, received


async def _close(task: asyncio.Task) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_committed_write_is_announced(api_schema, simple_api_context, test_graph) -> None:
    task, received = await _subscribe(api_schema)
    try:
        result = await api_schema.execute(ASSERT_ENTITY, variable_values={"input": {"term": "AIS", "supportingEvidence": []}}, context_value=simple_api_context)
        assert result.errors is None, f"GraphQL errors: {result.errors}"
        written = result.data["assertEntityExists"]

        announced = await asyncio.wait_for(received.get(), timeout=5)
        assert announced.errors is None, f"GraphQL errors: {announced.errors}"
        act = announced.data["assertionRecorded"]
        assert act["id"] == written["assertion"]["id"]
        assert act["seq"] == written["assertion"]["seq"]
        assert [row["id"] for row in act["instances"]] == [written["instance"]["id"]], "the announced row is the full act, claims and all"
    finally:
        await _close(task)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_rolled_back_write_is_not_announced(api_schema, simple_api_context, test_graph) -> None:
    """The broadcast is on commit. An assertion recorded inside a transaction that
    then fails was never part of the log, and nobody hears about it."""
    organization = simple_api_context.request._organization
    before = await evidence_models.Assertion.all_objects.acount()
    task, received = await _subscribe(api_schema)
    try:

        def write_then_fail() -> None:
            controller = GraphController()
            with pytest.raises(RuntimeError):
                with transaction.atomic():
                    controller._create_assertion(organization, ProvenanceContext(subject="1", app_id="test"))
                    raise RuntimeError("something after the assertion failed")

        await sync_to_async(write_then_fail)()
        assert await evidence_models.Assertion.all_objects.acount() == before

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(received.get(), timeout=1)
    finally:
        await _close(task)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_act_whose_claims_fail_is_not_recorded(api_schema, simple_api_context, test_graph, monkeypatch) -> None:
    """The act is one transaction. A failure while writing the claims takes the
    assertion and its outbox row with it: the log never held an act that said
    nothing, and nobody hears about it."""
    from graph_engine import models as projection_models

    before = await evidence_models.Assertion.all_objects.acount()
    pending_before = await projection_models.PendingProjection.objects.acount()

    def refuse(*args, **kwargs):
        raise RuntimeError("the claim could not be written")

    monkeypatch.setattr(writer, "create_instance", refuse)
    task, received = await _subscribe(api_schema)
    try:
        result = await api_schema.execute(ASSERT_ENTITY, variable_values={"input": {"term": "AIS"}}, context_value=simple_api_context)
        assert result.errors, "the write fails"

        assert await evidence_models.Assertion.all_objects.acount() == before, "no act was recorded"
        assert await projection_models.PendingProjection.objects.acount() == pending_before, "and nothing is owed to the projection"

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(received.get(), timeout=1)
    finally:
        await _close(task)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_another_tenants_write_is_not_heard(api_schema, simple_api_context, test_graph, other_organization) -> None:  # noqa: F811
    task, received = await _subscribe(api_schema)
    try:

        def foreign_write() -> None:
            with transaction.atomic():
                assertion = writer.create_assertion(other_organization, subject="stranger", app_id="test")
                channel.announce(assertion)

        await sync_to_async(foreign_write)()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(received.get(), timeout=1)
    finally:
        await _close(task)
