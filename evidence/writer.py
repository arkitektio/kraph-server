"""The write path for the relational evidence base.

Deliberately knows nothing about Apache AGE, Cypher, or graphs. Evidence is the
base relation; projections are built from it, never the other way round, so a
dependency in this direction would put the source of truth downstream of its own
cache.

Every function here is append-only. There is no update and no delete: correcting
a claim means writing a new assertion, and retracting one means writing a
:class:`~evidence.models.LifecycleEvent`. That is what keeps a derived value
explainable after the evidence behind it stops counting.
"""

from __future__ import annotations

import datetime
from typing import Any, Iterable

from authentikate.models import Organization
from django.db import transaction
from django.utils import timezone

from core.enums import ValueKind
from evidence import models as evidence_models

# Which typed column each ValueKind writes into. The inverse of
# `Metric.VALUE_COLUMN_FOR_KIND`, kept here because writing is where coercion
# has to happen.
_COLUMN_FOR_KIND: dict[str, str] = evidence_models.Metric.VALUE_COLUMN_FOR_KIND

_VECTOR_KINDS = frozenset(
    {
        ValueKind.ONE_D_VECTOR.value,
        ValueKind.TWO_D_VECTOR.value,
        ValueKind.THREE_D_VECTOR.value,
        ValueKind.FOUR_D_VECTOR.value,
        ValueKind.N_VECTOR.value,
    }
)


#: The one remaining conversion table, and it is an *input adapter* rather than a
#: parallel vocabulary: `PropertyType` is still what the GraphQL inputs accept,
#: while everything below the API speaks `ValueKind`.
_PROPERTY_TYPE_TO_VALUE_KIND: dict[str, str] = {
    "float": ValueKind.FLOAT.value,
    "integer": ValueKind.INT.value,
    "string": ValueKind.STRING.value,
    "boolean": ValueKind.BOOLEAN.value,
    "datetime": ValueKind.DATETIME.value,
    "point_3d": ValueKind.THREE_D_VECTOR.value,
}


def infer_value_kind(value: Any) -> ValueKind:
    """Guess a value's kind when the schema does not declare one.

    Only a fallback. The kind's declared ``value_kind`` wins whenever it
    exists, because inference cannot distinguish a CATEGORY from a STRING, and
    guessing wrong puts the value in a column the aggregation layer will not
    look in.
    """
    if isinstance(value, bool):
        return ValueKind.BOOLEAN
    if isinstance(value, int):
        return ValueKind.INT
    if isinstance(value, float):
        return ValueKind.FLOAT
    if isinstance(value, datetime.datetime):
        return ValueKind.DATETIME
    if isinstance(value, (list, tuple)):
        return {1: ValueKind.ONE_D_VECTOR, 2: ValueKind.TWO_D_VECTOR, 3: ValueKind.THREE_D_VECTOR, 4: ValueKind.FOUR_D_VECTOR}.get(len(value), ValueKind.N_VECTOR)
    return ValueKind.STRING


def value_columns(value: Any, value_kind: str) -> dict[str, Any]:
    """Map a value onto the single typed column its kind designates.

    Raises rather than silently dropping the value, because a metric that
    round-trips as ``None`` is indistinguishable from one that was never
    recorded — and the aggregation layer would treat it as absent evidence.
    """
    column = _COLUMN_FOR_KIND.get(value_kind)
    if column is None:
        raise ValueError(f"Unknown value_kind {value_kind!r}; expected one of {sorted(_COLUMN_FOR_KIND)}")

    if value_kind in _VECTOR_KINDS:
        return {column: list(value)}
    if column == "value_num":
        return {column: float(value)}
    if column == "value_bool":
        return {column: bool(value)}
    if column == "value_txt":
        return {column: str(value)}
    return {column: value}


def _as_datetime(value: Any, default: datetime.datetime) -> datetime.datetime:
    """Accept the ms-epoch ints the GraphQL surface still speaks."""
    if value is None:
        return default
    if isinstance(value, datetime.datetime):
        return value if timezone.is_aware(value) else timezone.make_aware(value, datetime.timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.datetime.fromtimestamp(value / 1000, tz=datetime.timezone.utc)
    raise TypeError(f"Cannot interpret {value!r} as a timestamp")


def ensure_structure_kind(organization: Organization, identifier: str) -> evidence_models.StructureKind:
    """Get or create the organization's term for a kind of external datum.

    Always allowed. Refusing to record a measurement because no graph had
    declared `@mikro/roi` would be refusing a fact about the world on a
    bookkeeping technicality — and the identifier is owned by the service that
    produced the datum anyway, so there is nothing here for us to approve.
    """
    kind, _ = evidence_models.StructureKind.all_objects.get_or_create(
        organization=organization,
        identifier=identifier,
    )
    return kind


def ensure_metric_kind(
    organization: Organization,
    structure_kind: evidence_models.StructureKind,
    key: str,
    value_kind: Any,
) -> evidence_models.MetricKind:
    """Get or create the organization's term for a kind of measurement.

    Raises when an existing term is redeclared with a different ``value_kind``.
    That is a real disagreement about what is being measured — one caller saying
    a length is a number and another saying it is a string — and resolving it
    silently would put the same measurement in different columns depending on who
    wrote it. Naming both kinds in the error is what makes it fixable.
    """
    declared = getattr(value_kind, "value", value_kind)
    declared = _PROPERTY_TYPE_TO_VALUE_KIND.get(declared, declared)
    if declared is None:
        raise ValueError(f"Cannot record '{structure_kind.identifier}'.{key} without a value kind: a term whose type is unknown cannot say which column its values belong in.")

    existing = evidence_models.MetricKind.all_objects.filter(organization=organization, structure_kind=structure_kind, key=key).first()

    if existing is None:
        return evidence_models.MetricKind.all_objects.create(
            organization=organization,
            structure_kind=structure_kind,
            key=key,
            value_kind=declared,
        )

    if existing.value_kind != declared:
        raise ValueError(f"'{structure_kind.identifier}'.{key} is declared {existing.value_kind}; cannot redeclare it as {declared}. Change the schema, or record this under a different key.")

    return existing


def create_assertion(
    organization: Organization,
    *,
    subject: str,
    app_id: str,
    action_id: str | None = None,
    action_name: str | None = None,
    action_args: dict[str, Any] | None = None,
    asserted_at: datetime.datetime | None = None,
) -> evidence_models.Assertion:
    """Record who is claiming something, and when they claim it."""
    return evidence_models.Assertion.objects.create_for_organization(
        organization=organization,
        subject=subject,
        app_id=app_id,
        action_id=action_id,
        action_name=action_name,
        action_args=action_args or {},
        asserted_at=asserted_at or timezone.now(),
    )


def ensure_structure(
    organization: Organization,
    kind: evidence_models.StructureKind,
    object: str,
    assertion: evidence_models.Assertion,
) -> evidence_models.Structure:
    """Get or create the structure for an external datum.

    Idempotent by identity rather than by kind: two projections resolving the
    same ``(identifier, object)`` converge on one row, which is the whole point of
    scoping evidence to the organization. The first assertion to introduce the
    structure is the one recorded — later references are not re-attributions.
    """
    structure, _ = evidence_models.Structure.objects.for_organization(organization).get_or_create(
        organization=organization,
        identifier=kind.identifier,
        object=object,
        defaults={"kind": kind, "assertion": assertion},
    )
    return structure


def record_metric(
    organization: Organization,
    structure: evidence_models.Structure,
    kind: evidence_models.MetricKind,
    *,
    key: str,
    value: Any,
    assertion: evidence_models.Assertion,
    unit: str | None = None,
    confidence: float | None = None,
    confidence_type: str | None = None,
    measured_at: Any = None,
    value_kind: str | None = None,
) -> evidence_models.Metric:
    """Append a measurement.

    ``measured_at`` defaults to the assertion time when the caller does not know
    when the observation happened, which is honest about the two axes being
    equal in that case rather than leaving the column null and unqueryable.
    """
    resolved = value_kind or kind.value_kind or infer_value_kind(value)
    resolved = getattr(resolved, "value", resolved)
    # The GraphQL surface still speaks `PropertyType` ("float", "integer",
    # "point_3d"); storage speaks `ValueKind`. Normalise at the boundary rather
    # than letting a lowercase spelling reach a column mapping that will not
    # recognise it.
    resolved = _PROPERTY_TYPE_TO_VALUE_KIND.get(resolved, resolved)

    return evidence_models.Metric.objects.create_for_organization(
        organization=organization,
        structure=structure,
        kind=kind,
        key=key,
        value_kind=resolved,
        assertion=assertion,
        unit=unit,
        confidence=confidence,
        confidence_type=confidence_type,
        measured_at=_as_datetime(measured_at, assertion.asserted_at),
        asserted_at=assertion.asserted_at,
        **value_columns(value, resolved),
    )


def create_link(
    organization: Organization,
    *,
    kind: str,
    source_ref: str,
    target_ref: str,
    assertion: evidence_models.Assertion,
    category: core_models.Category | None = None,
) -> evidence_models.Link:
    """Attach evidence to something. Refs stay opaque — see `Link`."""
    return evidence_models.Link.objects.create_for_organization(
        organization=organization,
        kind=kind,
        source_ref=source_ref,
        target_ref=target_ref,
        assertion=assertion,
        category=category,
    )


_TARGET_TYPES: dict[type, str] = {
    evidence_models.Structure: "structure",
    evidence_models.Metric: "metric",
    evidence_models.Link: "link",
}


def archive_ref(
    organization: Organization,
    *,
    target_type: str,
    target_id: str,
    assertion: evidence_models.Assertion,
    at: datetime.datetime | None = None,
) -> evidence_models.LifecycleEvent:
    """Retract something that is not an evidence row — currently only entities.

    Entities are still projected into AGE, so there is no row to flip a cached
    status on. The lifecycle log is still the authority; the projection picks the
    state up from here.
    """
    return evidence_models.LifecycleEvent.objects.create_for_organization(
        organization=organization,
        target_type=target_type,
        target_id=target_id,
        status=evidence_models.LifecycleStatus.ARCHIVED,
        at=at or timezone.now(),
        assertion=assertion,
    )


@transaction.atomic
def archive(
    organization: Organization,
    target: evidence_models.Structure | evidence_models.Metric | evidence_models.Link,
    assertion: evidence_models.Assertion,
    at: datetime.datetime | None = None,
) -> evidence_models.LifecycleEvent:
    """Retract a piece of evidence without destroying it.

    Writes the authoritative lifecycle row and refreshes the cached ``status``
    on the target in one transaction, so the cache cannot outlive a rolled-back
    log entry.
    """
    target_type = _TARGET_TYPES.get(type(target))
    if target_type is None:
        raise TypeError(f"{type(target).__name__} is not archivable evidence")

    if target.status == evidence_models.LifecycleStatus.ARCHIVED:
        # Archiving twice must be a no-op, not a second retraction. The caller
        # un-folds the metric's contribution from the state vector alongside
        # this, so a second archive would subtract a value that has already been
        # taken out — an error nothing would surface, because `recompute` fixes
        # `n` and the drift would only show on aggregations that never recompute.
        return evidence_models.LifecycleEvent.objects.for_organization(organization).filter(target_type=target_type, target_id=str(target.pk)).order_by("-at").first()

    event = archive_ref(
        organization,
        target_type=target_type,
        target_id=str(target.pk),
        assertion=assertion,
        at=at,
    )

    target.status = evidence_models.LifecycleStatus.ARCHIVED
    target.save(update_fields=["status"])
    return event


def active_metrics_for_structures(
    organization: Organization,
    structure_ids: Iterable[Any],
) -> Any:
    """Every un-retracted metric describing the given structures.

    The read path the projector will fold over in M3, and the SQL replacement
    for the Cypher `MATCH (m:Metric)-[:DESCRIBES]->(s)` that rollups used to
    walk.
    """
    return evidence_models.Metric.objects.for_organization(organization).filter(structure_id__in=list(structure_ids), status=evidence_models.LifecycleStatus.ACTIVE).order_by("measured_at")
