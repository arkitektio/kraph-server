"""Metrics recorded in another service, read from its change feed and recorded here as claims.

mikro records metrics -- observations about its annotations and datasets -- and keeps every
change in a feed (``@mikro/metric``, ``arkitekt_service.feed``). kraph reads that feed one
organization at a time (``kraph_server/hook_agent.py``) and records each metric as a `Metric`
claim about the `Structure` mikro's object is, so the folds, the rules and the views treat it
like any other measurement. One transaction of mikro's is one act here: its entries share an
`Assertion` (:meth:`GraphController.ingest_metric_page`), whose `subject`, `app_id` and
`action_id` are the producer mikro recorded -- its user, its app and the rekuest task it ran in.

**Exactly once.** A page is applied in one transaction with the reader's cursor, and every
ingested metric carries its mikro uuid in `Metric.source_uuid` (unique): a page read twice
records nothing the second time. **Set-based.** Kinds, structures and metrics are written per
page, and `State` is folded once per (entity, kind, key) touched, not once per metric
(`state.merge_many`) -- a batch of thousands of metrics about new objects is a handful of
statements. That write is :mod:`evidence.metric_batch`, shared with `assertMetricValues`; this module
is the feed's reading of an entry.

A DELETED entry is mikro withdrawing the metric: a `Standing(stands=False)` here, never a delete
(the log is append-only). A correction (``supersedes``) retracts what it corrects and cites it
(`DERIVED_FROM`, RFC 0017), as `supersedeMetricValue` does.

Nothing here draws: the draw follows the page's commit (`GraphController.ingest_metric_page`).
"""

from __future__ import annotations

import datetime
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from arkitekt_service.feed.consumer import Poison
from arkitekt_service.feed.reader import RemoteEntry
from authentikate.models import Client, Organization, User
from django.db import IntegrityError, transaction

from core.enums import ValueKind
from evidence import metric_batch
from evidence import models as evidence_models
from evidence.metric_batch import Recorded, StatedMetric

#: The feed metrics are read from, as the structure mikro hosts them under.
FEED = "@mikro/metric"
#: The service the feed is read from: the subject of an act no user of its is named in.
PRODUCER = "mikro"


@dataclass(frozen=True)
class Producer:
    """Who recorded a metric in mikro: as mikro verified them, never re-verified here."""

    user: str | None
    issuer: str | None
    app: str | None
    version: str | None
    client: str | None
    task: str | None


@dataclass(frozen=True)
class FedMetric:
    """A metric as mikro's feed renders it."""

    source_uuid: uuid.UUID
    identifier: str
    object: str
    key: str
    magnitude: float | None
    unit: str | None
    code: str | None
    supersedes: uuid.UUID | None
    producer: Producer
    created_at: datetime.datetime

    @property
    def value_kind(self) -> str:
        return ValueKind.CATEGORY.value if self.code is not None else ValueKind.FLOAT.value

    def stated(self) -> StatedMetric:
        """This metric as the write takes it: observed when mikro recorded it."""
        return StatedMetric(
            source_uuid=self.source_uuid,
            identifier=self.identifier,
            object=self.object,
            key=self.key,
            value=self.code if self.code is not None else self.magnitude,
            value_kind=self.value_kind,
            unit=self.unit,
            observed_at=self.created_at,
            supersedes=self.supersedes,
        )


@dataclass
class Act:
    """The entries of one transaction of mikro's: one act here."""

    xid: int
    created: list[FedMetric] = field(default_factory=list)
    deleted: list[uuid.UUID] = field(default_factory=list)

    @property
    def producer(self) -> Producer | None:
        return self.created[0].producer if self.created else None


def _str(value: object, what: str) -> str:
    if not isinstance(value, str) or not value:
        raise Poison(f"{what} is {value!r}, not a string")
    return value


def _optional_str(value: object, what: str) -> str | None:
    return None if value is None else _str(value, what)


def parse(entry: RemoteEntry) -> FedMetric | None:
    """What a CREATED entry says, or None when the metric is gone (its DELETED follows). Poison if malformed."""
    body = entry.body
    if body is None:
        return None
    if not isinstance(body, dict) or entry.uuid is None:
        raise Poison(f"entry {entry.xid}:{entry.id} has no metric body or no uuid")
    target, producer, task = body.get("target"), body.get("producer") or {}, body.get("task")
    if not isinstance(target, dict) or not isinstance(producer, dict):
        raise Poison(f"entry {entry.xid}:{entry.id} has no target or producer")
    magnitude, code = body.get("magnitude"), body.get("code")
    if (magnitude is None) == (code is None):
        raise Poison(f"metric {entry.uuid} is neither a quantity nor a code")
    if magnitude is not None and not isinstance(magnitude, (int, float)):
        raise Poison(f"metric {entry.uuid} has a magnitude of {magnitude!r}")
    try:
        created_at = datetime.datetime.fromisoformat(_str(body.get("created_at"), "created_at"))
        supersedes = None if body.get("supersedes") is None else uuid.UUID(_str(body.get("supersedes"), "supersedes"))
    except ValueError as error:
        raise Poison(f"metric {entry.uuid}: {error}") from error
    return FedMetric(
        source_uuid=entry.uuid,
        identifier=_str(target.get("identifier"), "target.identifier"),
        object=_str(target.get("object"), "target.object"),
        key=_str(body.get("key"), "key"),
        magnitude=None if magnitude is None else float(magnitude),
        unit=_optional_str(body.get("unit"), "unit"),
        code=_optional_str(code, "code"),
        supersedes=supersedes,
        producer=Producer(
            user=_optional_str(producer.get("user"), "producer.user"),
            issuer=_optional_str(producer.get("issuer"), "producer.issuer"),
            app=_optional_str(producer.get("app"), "producer.app"),
            version=_optional_str(producer.get("version"), "producer.version"),
            client=_optional_str(producer.get("client"), "producer.client"),
            task=_optional_str(task.get("task_id"), "task.task_id") if isinstance(task, dict) else None,
        ),
        created_at=created_at,
    )


def acts(entries: Sequence[RemoteEntry]) -> list[Act]:
    """The page's entries grouped by the transaction of mikro's that wrote them, in feed order."""
    grouped: dict[int, Act] = {}
    for entry in entries:
        act = grouped.setdefault(entry.xid, Act(entry.xid))
        if entry.kind == "CREATED":
            metric = parse(entry)
            if metric is not None:
                act.created.append(metric)
        elif entry.kind == "DELETED":
            if entry.uuid is None:
                raise Poison(f"DELETED entry {entry.xid}:{entry.id} names no metric uuid")
            act.deleted.append(entry.uuid)
        else:
            raise Poison(f"entry {entry.xid}:{entry.id} is {entry.kind!r}: a metric is created or deleted, never updated")
    return list(grouped.values())


def outstanding(organization: Organization, act: Act) -> Act:
    """The part of ``act`` not recorded yet: metrics not ingested before, withdrawals of ones that were."""
    already = set(evidence_models.Metric.all_objects.filter(source_uuid__in=[m.source_uuid for m in act.created]).values_list("source_uuid", flat=True))
    known = set(evidence_models.Metric.all_objects.filter(organization=organization, source_uuid__in=act.deleted).values_list("source_uuid", flat=True)) if act.deleted else set()
    return Act(act.xid, [m for m in act.created if m.source_uuid not in already], [d for d in act.deleted if d in known])


def local_user_id(producer: Producer) -> str | None:
    """This service's id of the user mikro recorded (``(sub, iss)``), made as authenticating them would make it.

    An assertion's subject is the local user's id everywhere else, so a rule naming a SUBJECT
    reads a fed metric like any other. Without an issuer the user cannot be told apart: None.
    """
    if producer.user is None or producer.issuer is None:
        return None
    user = User.objects.filter(sub=producer.user, iss=producer.issuer).first()
    if user is None:
        user = User(sub=producer.user, iss=producer.issuer, username=re.sub(r"[^\w.@+-]", "_", f"{producer.issuer}_{producer.user}")[:150])
        user.set_unusable_password()
        try:
            with transaction.atomic():
                user.save()
        except IntegrityError:  # made meanwhile by a request authenticating them
            user = User.objects.get(sub=producer.user, iss=producer.issuer)
    return str(user.id)


def local_client_id(producer: Producer) -> str | None:
    """This service's id of the OAuth client mikro recorded the metric through: what every assertion's ``app_id`` is."""
    if producer.client is None:
        return None
    client, _ = Client.objects.get_or_create(client_id=producer.client)
    return str(client.id)


def record(organization: Organization, act: Act, assertion: evidence_models.Assertion) -> Recorded:
    """Write one act's outstanding claims (:func:`outstanding`) under ``assertion``. Inside the page's transaction; draws nothing."""
    recorded = Recorded()
    if act.created:
        metric_batch.record_into(organization, [metric.stated() for metric in act.created], assertion, recorded)
    if act.deleted:
        withdrawn = list(evidence_models.Metric.all_objects.filter(organization=organization, source_uuid__in=act.deleted).select_related("structure"))
        metric_batch.retract(organization, withdrawn, assertion, recorded)
    return recorded
