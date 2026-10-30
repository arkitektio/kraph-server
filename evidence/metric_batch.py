"""Many metrics, about many structures, as one act: the write `assertMetricValues` and mikro's feed share.

**Set-based.** Kinds, structures and metrics are written per batch, and `State` is folded once
per (entity, kind, key) touched, not once per metric (`state.merge_many`), so thousands of
metrics about new objects are a handful of statements.

**Once, for a producer that asks.** Every metric carries a uuid in `Metric.source_uuid` (unique):
its producer's, or a fresh one the caller minted for it. :func:`outstanding` drops what is already
recorded, so a batch retried under the same uuids records nothing twice and mints no assertion,
and the unique index settles two copies racing past that check: the loser's rows are skipped, not
folded. A batch that names no uuids is one transaction, so a failure recorded nothing and a rerun
is safe unless it had in fact committed, when the rerun is a second measurement.

Nothing here draws: the draw follows the commit, as for every write.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from authentikate.models import Organization

from evidence import claims as claims_module
from evidence import models as evidence_models
from evidence import state as state_module
from evidence import writer
from evidence.values import JSONValue


@dataclass(frozen=True)
class StatedMetric:
    """One value somebody states about one external datum."""

    source_uuid: uuid.UUID
    identifier: str
    object: str
    key: str
    value: JSONValue
    value_kind: str
    unit: str | None = None
    confidence: float | None = None
    confidence_type: str | None = None
    observed_at: datetime.datetime | None = None
    supersedes: uuid.UUID | None = None
    derived_from: tuple[str, ...] = ()


@dataclass
class Recorded:
    """What one act wrote: the structures whose evidence moved, for the draw that follows."""

    metrics: int = 0
    retracted: int = 0
    structure_ids: set[uuid.UUID] = field(default_factory=set)


def outstanding(organization: Organization, metrics: Sequence[StatedMetric]) -> list[StatedMetric]:
    """The metrics not recorded yet.

    A retry names the same datum, key and kind, and is dropped; its value is not compared, so a
    tool that computes something else the second time keeps the first answer. Anything else
    holding the uuid is a collision, not a retry: refused, because skipping it would lose the
    value while telling the caller it went through. That covers another organization's metric.
    """
    wanted = {m.source_uuid: m for m in metrics}
    held = list(evidence_models.Metric.all_objects.filter(source_uuid__in=list(wanted)).select_related("structure"))
    collisions = [
        str(row.source_uuid)
        for row in held
        if row.organization_id != organization.pk or (row.structure.identifier, row.structure.object, row.key, row.value_kind) != _identity(wanted[row.source_uuid])
    ]
    if collisions:
        raise ValueError(f"These metric uuids already name a different metric: {sorted(collisions)}. A uuid names one metric, so choose another.")
    recorded = {row.source_uuid for row in held}
    return [m for m in metrics if m.source_uuid not in recorded]


def _identity(metric: StatedMetric) -> tuple[str, str, str, str | None]:
    """What a retry has to agree on with the metric it repeats: the datum, the key and the kind."""
    return (metric.identifier, metric.object, metric.key, writer.canonical_value_kind(metric.value_kind))


def assert_corrections_known(organization: Organization, metrics: Sequence[StatedMetric]) -> None:
    """Refuse a correction of a metric this organization does not hold: it would record the new value and retract nothing."""
    named = {m.supersedes for m in metrics if m.supersedes is not None}
    if not named:
        return
    known = set(evidence_models.Metric.all_objects.filter(organization=organization, source_uuid__in=named).values_list("source_uuid", flat=True))
    unknown = named - known
    if unknown:
        raise ValueError(f"`supersedes` names metrics that are not on the record: {sorted(str(source) for source in unknown)}")


def _structures(organization: Organization, metrics: Sequence[StatedMetric], assertion: evidence_models.Assertion) -> dict[tuple[str, str], evidence_models.Structure]:
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


def _citations(organization: Organization, cited: Sequence[tuple[str, str]], assertion: evidence_models.Assertion) -> None:
    """``(claim, source)`` pairs as `DERIVED_FROM` links, in one insert: one table cited by every metric of a batch is the ordinary case."""
    # `bulk_create` skips `save`, so the link's own default for `observed_at` is stated here.
    evidence_models.Link.all_objects.bulk_create(
        [
            evidence_models.Link(organization=organization, kind=evidence_models.Link.Kind.DERIVED_FROM, source_ref=claim, target_ref=source, assertion=assertion, observed_at=assertion.asserted_at)
            for claim, source in cited
        ]
    )


def record_into(organization: Organization, fresh: Sequence[StatedMetric], assertion: evidence_models.Assertion, recorded: Recorded) -> None:
    """Record metrics not recorded before (:func:`outstanding`) under ``assertion``. Inside the caller's transaction; draws nothing."""
    structures = _structures(organization, fresh, assertion)
    kinds: dict[tuple[uuid.UUID, str, str], evidence_models.MetricKind] = {}
    rows: list[evidence_models.Metric] = []
    for metric in fresh:
        structure = structures[(metric.identifier, metric.object)]
        declared = writer.canonical_value_kind(metric.value_kind) or metric.value_kind
        kind_key = (structure.kind_id, metric.key, declared)
        if kind_key not in kinds:
            kinds[kind_key] = writer.ensure_metric_kind(organization, structure.kind, metric.key, declared)
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
                confidence=metric.confidence,
                confidence_type=metric.confidence_type,
                # Set here, as `record_metric` would: a bulk insert runs no `save`.
                observed_at=writer.as_datetime(metric.observed_at, assertion.asserted_at),
                asserted_at=assertion.asserted_at,
                source_uuid=metric.source_uuid,
                **writer.value_columns(metric.value, declared, metric.key),
            )
        )
    # A copy of this batch that raced past `outstanding` holds some of these uuids. Its rows are
    # the record and these are not: only what landed is folded, counted and cited.
    evidence_models.Metric.all_objects.bulk_create(rows, ignore_conflicts=True)
    landed = set(evidence_models.Metric.all_objects.filter(assertion=assertion, source_uuid__in=[row.source_uuid for row in rows]).values_list("pk", flat=True))
    created = [row for row in rows if row.pk in landed]
    recorded.metrics += len(created)
    recorded.structure_ids.update(row.structure_id for row in created)
    state_module.merge_many(created, informed_by(organization, {row.structure_id for row in created}))

    by_source = {row.source_uuid: row for row in created}
    stated_for = [(by_source[m.source_uuid], m) for m in fresh if m.source_uuid in by_source]
    corrected = {m.supersedes: row for row, m in stated_for if m.supersedes is not None}
    old = list(evidence_models.Metric.all_objects.filter(organization=organization, source_uuid__in=list(corrected)).select_related("structure")) if corrected else []
    _citations(
        organization,
        [(str(row.pk), source) for row, m in stated_for for source in m.derived_from] + [(str(corrected[previous.source_uuid].pk), str(previous.pk)) for previous in old],
        assertion,
    )
    retract(organization, old, assertion, recorded)


def retract(organization: Organization, metrics: Sequence[evidence_models.Metric], assertion: evidence_models.Assertion, recorded: Recorded) -> None:
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
