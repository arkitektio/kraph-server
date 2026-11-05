"""Subscriptions in tests: open one in its own task and read what it yields.

The same harness as `tests/log/test_an_act_is_one_transaction.py`, with the document,
its variables and the room to wait for as arguments.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any, AsyncIterator

from asgiref.sync import sync_to_async
from authentikate.models import Client
from channels.layers import get_channel_layer
from kante.testing import build_ws_context

from tests.support.identity import static_identity


class StubConsumer:
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


async def subscribe(api_schema, document: str, room: str, variables: dict | None = None) -> tuple[asyncio.Task, asyncio.Queue]:
    """Start the subscription; return once its room is registered on the layer, so a write made right after is heard."""
    user, org, membership = await sync_to_async(static_identity)()
    client, _ = await Client.objects.aget_or_create(client_id="oinsoins")
    consumer = StubConsumer()
    await consumer.open()
    ctx = build_ws_context(consumer=consumer, user=user, organization=org, client=client, membership=membership, token="test", connection_params={"token": "test"})
    received: asyncio.Queue[Any] = asyncio.Queue()

    async def run() -> None:
        stream = await api_schema.subscribe(document, variable_values=variables or {}, context_value=ctx)
        if not hasattr(stream, "__anext__"):
            await received.put(stream)
            return
        async for result in stream:
            await received.put(result)

    task = asyncio.create_task(run())
    for _ in range(200):
        await asyncio.sleep(0.01)
        if task.done() or room in getattr(consumer.channel_layer, "groups", {}):
            break
    if task.done():
        raise AssertionError(f"subscription did not start: {task.exception() or received.get_nowait()}")
    return task, received


async def close(task: asyncio.Task) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
