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
statements.

A DELETED entry is mikro withdrawing the metric: a `Standing(stands=False)` here, never a delete
(the log is append-only). A correction (``supersedes``) retracts what it corrects and cites it
(`DERIVED_FROM`, RFC 0017), as `supersedeMetricValue` does.

Nothing here draws: the draw follows the page's commit (`GraphController.ingest_metric_page`).
"""

from __future__ import annotations

import datetime
import re
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from arkitekt_service.feed.consumer import Poison
from arkitekt_service.feed.reader import RemoteEntry
from authentikate.models import Client, Organization, User
from django.db import IntegrityError, transaction

from core.enums import ValueKind
from evidence import claims as claims_module
from evidence import models as evidence_models
from evidence import state as state_module
from evidence import writer

#: The feed metrics are read from, as the structure mikro hosts them under.
FEED = "@mikro/metric"
#: The service the feed is read from: the subject of an act no user of its is named in.
PRODUCER = "live.arkitekt.mikro"


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


@dataclass
class Recorded:
    """What one act wrote: the structures whose evidence moved, for the draw that follows."""

    metrics: int = 0
    retracted: int = 0
    structure_ids: set[uuid.UUID] = field(default_factory=set)


def _structures(organization: Organization, metrics: Sequence[FedMetric], assertion: evidence_models.Assertion) -> dict[tuple[str, str], evidence_models.Structure]:
    """The individual each metric is about: one query per identifier, one insert for the new ones."""
    kinds = {identifier: writer.ensure_structure_kind(organization, identifier) for identifier in {m.identifier for m in metrics}}
    wanted = {(m.identifier, m.object) for m in metrics}

    def existing() -> dict[tuple[str, str], evidence_models.Structure]:
        found: dict[tuple[str, str], evidence_models.Structure] = {}
        for identifier in kinds:
            objects = [obj for ident, obj in wanted if ident == identifier]
            for structure in evidence_models.Structure.all_objects.filter(organization=organization, identifier=identifier, object__in=objects):
                found[(structure.identifier, structure.object)] = structure
        return found

    found = existing()
    missing = wanted - set(found)
    if missing:
        # `bulk_create` skips `save`, so `observed_at` is set here: the datum was observed to
        # exist when it was first referenced.
        evidence_models.Structure.all_objects.bulk_create(
            [
                evidence_models.Structure(organization=organization, kind=kinds[identifier], identifier=identifier, object=obj, assertion=assertion, observed_at=assertion.asserted_at)
                for identifier, obj in missing
            ],
            ignore_conflicts=True,
        )
        found = existing()
    return found


def informed_by(organization: Organization, structure_ids: Iterable[uuid.UUID]) -> dict[str, list[str]]:
    """What each structure is standing evidence for (its INFORMS links that stand), by structure."""
    informed: dict[str, list[str]] = {}
    links = claims_module.standing(
        evidence_models.Link.objects.for_organization(organization).filter(kind=evidence_models.Link.Kind.INFORMS, source_ref__in=[str(s) for s in structure_ids]),
        "link",
    )
    for source_ref, target_ref in links.values_list("source_ref", "target_ref").distinct():
        informed.setdefault(str(source_ref), []).append(str(target_ref))
    return informed


def record(organization: Organization, act: Act, assertion: evidence_models.Assertion) -> Recorded:
    """Write one act's outstanding claims (:func:`outstanding`) under ``assertion``. Inside the page's transaction; draws nothing."""
    recorded = Recorded()
    if act.created:
        _record_created(organization, act.created, assertion, recorded)
    if act.deleted:
        withdrawn = list(evidence_models.Metric.all_objects.filter(organization=organization, source_uuid__in=act.deleted).select_related("structure"))
        _retract(organization, withdrawn, assertion, recorded)
    return recorded


def _record_created(organization: Organization, fresh: Sequence[FedMetric], assertion: evidence_models.Assertion, recorded: Recorded) -> None:
    """Record metrics not ingested before (:func:`outstanding`); the unique ``source_uuid`` is the backstop."""
    structures = _structures(organization, fresh, assertion)
    kinds: dict[tuple[uuid.UUID, str, str], evidence_models.MetricKind] = {}
    rows: list[evidence_models.Metric] = []
    for metric in fresh:
        structure = structures[(metric.identifier, metric.object)]
        kind_key = (structure.kind_id, metric.key, metric.value_kind)
        if kind_key not in kinds:
            kinds[kind_key] = writer.ensure_metric_kind(organization, structure.kind, metric.key, metric.value_kind)
        rows.append(
            evidence_models.Metric(
                organization=organization,
                structure=structure,
                kind=kinds[kind_key],
                key=metric.key,
                # The term's, as `writer.record_metric` has it: the kind is part of the term's identity.
                value_kind=kinds[kind_key].value_kind,
                assertion=assertion,
                unit=metric.unit,
                # Set here, as `record_metric` would: a bulk insert runs no `save`.
                observed_at=metric.created_at,
                asserted_at=assertion.asserted_at,
                source_uuid=metric.source_uuid,
                **writer.value_columns(metric.code if metric.code is not None else metric.magnitude, metric.value_kind, metric.key),
            )
        )
    created = evidence_models.Metric.all_objects.bulk_create(rows)
    recorded.metrics += len(created)
    recorded.structure_ids.update(row.structure_id for row in created)
    state_module.merge_many(created, informed_by(organization, {row.structure_id for row in created}))

    corrected = {m.supersedes: m for m in fresh if m.supersedes is not None}
    if corrected:
        by_source = {row.source_uuid: row for row in created}
        old = list(evidence_models.Metric.all_objects.filter(organization=organization, source_uuid__in=list(corrected)).select_related("structure"))
        for previous in old:
            writer.create_link(
                organization,
                kind=evidence_models.Link.Kind.DERIVED_FROM,
                source_ref=str(by_source[corrected[previous.source_uuid].source_uuid].pk),
                target_ref=str(previous.pk),
                assertion=assertion,
            )
        _retract(organization, old, assertion, recorded)


def _retract(organization: Organization, metrics: Sequence[evidence_models.Metric], assertion: evidence_models.Assertion, recorded: Recorded) -> None:
    """Withdraw each metric that still stands, and take it out of the statistics once."""
    if not metrics:
        return
    informed = informed_by(organization, {m.structure_id for m in metrics})
    for metric in metrics:
        result = writer.retract(organization, metric, assertion)
        if result.moved:
            state_module.retract(metric, informed.get(str(metric.structure_id), []))
            recorded.retracted += 1
            recorded.structure_ids.add(metric.structure_id)
