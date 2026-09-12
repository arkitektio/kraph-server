"""The one lock the projection takes: per organization, while a bulk redraw runs.

Two bulk paths redraw an organization's views — `projector.rebuild` (drop and
replay one graph, refolding organization-grain caches on the way) and
`projector.replay` (apply the outbox to every consistent graph). Each is many
autocommit statements by design: one long writing transaction would stall the
`changes()` horizon for everyone (`evidence/log.py`). So the lock is a Postgres
**session** advisory lock, not a transaction one — an `_xact_` lock in
autocommit releases the moment its statement ends — released in `finally`, and
by the server if the session dies.

Per organization, not per graph: the outbox is organization grain, `replay`
walks every graph, and `rebuild` refolds `State`, `CurrentStanding` and the
identity cache organization-wide. Two of these interleaving on one organization
is what the lock prevents; the in-request draw of an ordinary write is *not*
under it — that path converges on its own and the runner retries anything it
loses to a race.

Session locks are reentrant on one connection, so a `rebuild` reached from a
locked caller does not deadlock on itself.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator

from authentikate.models import Organization
from django.db import connection

#: The int4 namespace every kraph advisory lock is keyed under, so a lock this
#: service takes can never collide with one another service takes on the same
#: database. ASCII "kra".
LOCK_NAMESPACE = 0x6B7261


def _key(organization: Organization | int) -> int:
    return int(getattr(organization, "id", organization))


@contextlib.contextmanager
def organization_projection_lock(organization: Organization, *, wait: bool) -> Iterator[bool]:
    """Hold the organization's projection lock for the block.

    `wait=True` blocks until it is free and always yields True. `wait=False`
    tries once and yields whether it got it — the runner's choice, so a pass
    that meets a running rebuild skips the organization and says so instead of
    queueing behind it.
    """
    key = _key(organization)
    with connection.cursor() as cursor:
        if wait:
            cursor.execute("SELECT pg_advisory_lock(%s, %s)", [LOCK_NAMESPACE, key])
            held = True
        else:
            cursor.execute("SELECT pg_try_advisory_lock(%s, %s)", [LOCK_NAMESPACE, key])
            held = bool(cursor.fetchone()[0])
    try:
        yield held
    finally:
        if held:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s, %s)", [LOCK_NAMESPACE, key])


def is_locked(organization: Organization) -> bool:
    """Whether any session holds the organization's projection lock right now."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND classid = %s AND objid = %s AND objsubid = 2 AND granted",
            [LOCK_NAMESPACE, _key(organization)],
        )
        return cursor.fetchone() is not None
