"""mikro's change feed of metrics, as kraph reads it: entries to apply, and a feed to serve.

`entry`/`withdrawal` build what a page of ``@mikro/metric`` hands kraph (mikro renders the
body; ``arkitekt_service.feed`` carries it). `apply` runs a page the way the hook agent does --
inside one transaction, the draw after the commit -- without the HTTP in between.
`serve` stands mikro's side up in this process: entries in the feed tables, bodies rendered from
:data:`BODIES`, served at ``/_feed`` by :mod:`tests.support.feed_urls`.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from arkitekt_service.feed.api import Change, record_changes
from arkitekt_service.feed.reader import RemoteEntry
from authentikate.models import Organization
from django.db import transaction

from evidence import ingest
from graph_engine.controller import GraphController
from graph_engine.projection.context import current_or_default

#: What the in-process stand-in for mikro renders for each object it serves.
BODIES: dict[str, dict[str, Any]] = {}

ISSUER = "https://lok.example/o"


def body(identifier: str, object: str, key: str, *, magnitude: float | None = None, unit: str | None = None, code: str | None = None, user: str | None = "mikro-user-1", app: str | None = "ais_suite", task: str | None = None, supersedes: uuid.UUID | None = None) -> dict[str, Any]:
    """A metric as mikro renders it into its feed."""
    return {
        "target": {"identifier": identifier, "object": object, "uuid": str(uuid.uuid4())},
        "key": key,
        "magnitude": magnitude,
        "unit": unit,
        "code": code,
        "producer": {"app": app, "version": "0.4.1", "client": "ais-client", "user": user, "issuer": ISSUER if user else None},
        "task": {"task_id": task, "root_task_id": task} if task else None,
        "supersedes": None if supersedes is None else str(supersedes),
        "created_at": datetime.datetime(2026, 10, 19, 9, 12, 3, tzinfo=datetime.UTC).isoformat(),
    }


_next_id = iter(range(1, 10**9))


def entry(xid: int, metric_body: dict[str, Any] | None, *, uid: uuid.UUID | None = None, organization: str = "evidence-org") -> RemoteEntry:
    """A CREATED entry of mikro's transaction ``xid``; a None body is a metric deleted before it was read."""
    return RemoteEntry(xid=xid, id=next(_next_id), kind="CREATED", object=str(next(_next_id)), uuid=uid or uuid.uuid4(), organization=organization, body=metric_body)


def withdrawal(xid: int, uid: uuid.UUID, *, organization: str = "evidence-org") -> RemoteEntry:
    """A DELETED entry: mikro withdrawing the metric ``uid``."""
    return RemoteEntry(xid=xid, id=next(_next_id), kind="DELETED", object="0", uuid=uid, organization=organization, body=None)


def apply(organization: Organization, entries: list[RemoteEntry]) -> ingest.Recorded:
    """Apply one page as the hook agent does: in one transaction, drawn after its commit."""
    controller = GraphController(projector=current_or_default())
    with transaction.atomic():
        return controller.ingest_metric_page(organization, entries)


def serve(organization: str, bodies: list[dict[str, Any]]) -> list[uuid.UUID]:
    """Record CREATED entries in this process's feed, as mikro would, and the bodies it will render."""
    uids = [uuid.uuid4() for _ in bodies]
    with transaction.atomic():
        objects = [str(1000 + len(BODIES) + i) for i in range(len(bodies))]
        record_changes([Change(ingest.FEED, "CREATED", obj, organization, uuid=uid) for obj, uid in zip(objects, uids, strict=True)])
    BODIES.update(zip(objects, bodies, strict=True))
    return uids
