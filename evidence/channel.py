"""The log announces each act as it commits (RFC 0020).

One kante channel, one message shape: the id and seq of an `Assertion`, in the
organization's room. The subscriber (`api/subscriptions/log.py`) re-fetches the row
under its own organization scope, so the room name is not the only thing keeping
one tenant's log out of another's stream.

The broadcast is `transaction.on_commit`. `GraphController._create_assertion`
calls :func:`announce` as the first statement of a write's transaction, and the
message goes out only once that transaction commits — a write that fails after
recording its assertion was never part of the log and announces nothing.
"""

from __future__ import annotations

from typing import Any

from kante.channel import build_channel
from pydantic import BaseModel


class AssertionRecorded(BaseModel):
    """What the room hears: enough to re-fetch the act, nothing to trust as-is."""

    id: str
    seq: int
    organization: int


assertion_channel = build_channel(AssertionRecorded, name="assertion")


def room(organization: Any) -> str:
    """The organization's room for this channel — the one definition, used by both sides.

    Not `assertion_channel.org_group`: kante spells that ``assertion:org:<id>``,
    and the channel layer refuses a group name containing a colon (only ASCII
    alphanumerics, hyphens, underscores and periods are allowed), so every
    broadcast through it raises inside the commit hook.
    """
    organization_id = getattr(organization, "id", organization)
    return f"assertion.org.{int(organization_id)}"


def announce(assertion: Any) -> None:
    """Broadcast ``assertion`` to its organization's room once its transaction commits."""
    message = AssertionRecorded(id=str(assertion.id), seq=int(assertion.seq), organization=int(assertion.organization_id))
    assertion_channel.broadcast_on_commit(message, groups=[room(assertion.organization_id)])
