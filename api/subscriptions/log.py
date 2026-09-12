"""The log, live (RFC 0020).

One subscription: `assertionRecorded`, which yields each `Assertion` of the
caller's organization as its transaction commits. The room is
`evidence.channel.room(organization)` on both sides — here and in
`evidence.channel.announce` — so the name has one definition; and the row is
re-fetched under the organization's scope rather than trusted from the message,
so the room name is not the only tenant fence.

The message carries an id and a seq; the row is what the client gets, with the
same six claim lists `assertion(id:)` answers. A consumer that wants never to
miss an act pairs this with `changes(afterSeq:)`: the subscription says "now",
the feed says "everything since".
"""

from typing import AsyncGenerator

from asgiref.sync import sync_to_async
import kante
from kante.types import Info

from api import context, types
from evidence import models as evidence_models
from evidence import channel
from evidence.channel import assertion_channel


@kante.type(description="The log, as it is written")
class Subscription:
    """Root subscription type. Websocket transport only — see `kante.channel`."""

    @kante.subscription(description="Each act of claiming in the caller's organization, as its transaction commits. Never an act that rolled back, never another tenant's")
    async def assertion_recorded(self, info: Info) -> AsyncGenerator[types.Assertion, None]:
        organization = context.get_active_organization(info)
        # The membership check is an ORM query; the resolver is async.
        await sync_to_async(context.assert_can_access_organization)(info, organization)
        async for message in assertion_channel.listen(info, [channel.room(organization)]):
            row = await evidence_models.Assertion.objects.for_organization(organization).filter(id=message.id).afirst()
            if row is None:
                # Announced for this room but not in this organization's log — the
                # message is not trusted for tenancy, the row is.
                continue
            yield row  # type: ignore[misc]
