"""Todo lists announce each change as it commits, so open boards and chips follow live.

One kante channel, one small message: which list (and item) changed, and how. The
subscriber (`api/subscriptions/todos.py`) re-fetches the item under its own
organization fence, so the room name is never the only thing keeping one tenant's
todos out of another's stream (the rule `evidence/channel.py` follows for the log).

The broadcast is `transaction.on_commit`: a write that rolls back announces nothing.
"""

from __future__ import annotations

from typing import Literal, Optional

from authentikate.models import Organization
from kante.channel import build_channel
from pydantic import BaseModel


class TodoChanged(BaseModel):
    """What the room hears: enough to re-fetch, nothing to trust as-is."""

    kind: Literal["CHANGED", "DELETED"]
    list: str
    item: Optional[str] = None
    organization: int


todo_channel = build_channel(TodoChanged, name="todo")


def room(organization: Organization | int) -> str:
    """The organization's todo room. Dots, not colons: the channel layer refuses a colon in a group name."""
    organization_id = getattr(organization, "id", organization)
    return f"todo.org.{int(organization_id)}"


def announce(organization: Organization | int, todo_list: int | str, item: int | str | None = None, *, deleted: bool = False) -> None:
    """Tell the organization's room that a list (or one of its items) changed, once the transaction commits."""
    organization_id = int(getattr(organization, "id", organization))
    message = TodoChanged(
        kind="DELETED" if deleted else "CHANGED",
        list=str(todo_list),
        item=None if item is None else str(item),
        organization=organization_id,
    )
    todo_channel.broadcast_on_commit(message, groups=[room(organization_id)])
