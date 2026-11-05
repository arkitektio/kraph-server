"""Todo lists, live: `todoChanged` yields each change to the caller's organization's lists as it commits.

The room is `todos.channel.room(organization)` on both sides. The item is re-fetched
under the organization's fence rather than trusted from the message, so a message
for another tenant's room could never hand out another tenant's row.
"""

from typing import AsyncGenerator, Optional

import kante
import strawberry
from asgiref.sync import sync_to_async
from authentikate.strawberry.directives import AuthSubscribeExtension
from kante.types import Info

from api import context
from todos import channel
from todos import models as todo_models
from todos import types as todo_types


@sync_to_async
def _fetch(organization, item_id: str) -> Optional[todo_models.TodoItem]:
    return (
        todo_models.TodoItem.objects.filter(pk=item_id, list__project__organization=organization)
        .select_related("list", "list__project")
        .first()
    )


@sync_to_async
def _list_is_ours(organization, list_id: str) -> bool:
    return todo_models.TodoList.objects.filter(pk=list_id, project__organization=organization).exists()


@kante.type(description="Todo lists, as they change")
class TodoSubscription:
    @kante.subscription(
        extensions=[AuthSubscribeExtension(scopes=["kraph_read"])],
        description="Each change to the organization's todo lists and items as its transaction commits; `list` or `item` narrow it to one board or one card",
    )
    async def todo_changed(
        self, info: Info, list: Optional[strawberry.ID] = None, item: Optional[strawberry.ID] = None
    ) -> AsyncGenerator[todo_types.TodoChange, None]:
        organization = context.get_active_organization(info)
        await sync_to_async(context.assert_can_access_organization)(info, organization)
        async for message in channel.todo_channel.listen(info, [channel.room(organization)]):
            if list is not None and message.list != str(list):
                continue
            if item is not None and message.item != str(item):
                continue
            kind = todo_types.TodoChangeKind(message.kind)
            row = None
            if message.item is not None and kind == todo_types.TodoChangeKind.CHANGED:
                row = await _fetch(organization, message.item)
                if row is None:
                    continue  # not this organization's (or gone already): the message is not trusted
            elif not await _list_is_ours(organization, message.list) and kind == todo_types.TodoChangeKind.CHANGED:
                continue
            yield todo_types.TodoChange(kind=kind, list_id=strawberry.ID(message.list), item_id=None if message.item is None else strawberry.ID(message.item), item=row)  # type: ignore[arg-type]
