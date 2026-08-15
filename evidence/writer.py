"""The write path for the relational evidence base.

Deliberately knows nothing about Apache AGE, Cypher, or graphs. Evidence is the
base relation; projections are built from it, never the other way round, so a
dependency in this direction would put the source of truth downstream of its own
cache.

Every function here is append-only against the **log**: there is no update and no
delete of a `Structure`, `Metric`, `Link`, `Node`, `Claim` or `Assertion`.
Correcting a claim means writing a new assertion, and changing whether something
stands means writing a :class:`~evidence.models.Claim`. That is what keeps a
derived value explainable after the evidence behind it stops counting.

This paragraph used to be false, and worth knowing why. `claim()` wrote the row
*and* flipped a cached `stands` boolean on the target — an `UPDATE` on a log
table, four lines below a docstring promising there were none. The cache is now
:class:`~evidence.models.ClaimCurrent`, a projection, and :func:`claim` writes to
that instead. Projections are mutable by definition; the log is not, and can now
be held to it by the database rather than by this comment.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any, Iterable, NamedTuple

from authentikate.models import Organization
from django.db import transaction
from django.utils import timezone

from core.enums import ValueKind
from evidence import claims as claims_module
from evidence import models as evidence_models

if TYPE_CHECKING:
    # `create_link` annotates `category: core_models.Category`, which named a
    # module this file never imported. `from __future__ import annotations` kept
    # it from failing at runtime, so it only ever surfaced under a type checker
    # or `typing.get_type_hints`. A real import here, not a runtime one: the
    # write path deliberately does not depend on the ontology layer.
    from core import models as core_models

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


#: Deliberately absent: an `infer_value_kind` that guessed a kind from
#: `type(value)`. Every write now states its own kind, so nothing here has to
#: choose — and inference could not tell a CATEGORY from a STRING, nor keep `45`
#: and `45.2` under one key from becoming an INT term and a FLOAT one.


def value_columns(value: Any, value_kind: str, key: str = "?") -> dict[str, Any]:
    """Map a value onto the single typed column its kind designates.

    Raises rather than silently dropping the value, because a metric that
    round-trips as ``None`` is indistinguishable from one that was never
    recorded — and the aggregation layer would treat it as absent evidence.

    ``key`` is only for the error. Now that the caller states the value kind, a
    mismatch is their own declaration disagreeing with what they sent, so the
    message names all three — `float('high')` on its own says
    ``could not convert string to float: 'high'`` and leaves them to work out
    which of a batch of measurements it came from.
    """
    column = _COLUMN_FOR_KIND.get(value_kind)
    if column is None:
        raise ValueError(f"Unknown value_kind {value_kind!r}; expected one of {sorted(_COLUMN_FOR_KIND)}")

    try:
        if value_kind in _VECTOR_KINDS:
            return {column: list(value)}
        if column == "value_num":
            return {column: float(value)}
        if column == "value_bool":
            return {column: bool(value)}
        if column == "value_txt":
            return {column: str(value)}
        return {column: value}
    except (TypeError, ValueError) as error:
        raise ValueError(f"'{key}' is declared {value_kind}, but {value!r} is not a {value_kind} value ({error}). Declare the kind that matches what you are recording.") from error


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


def ensure_term(organization: Organization, kind: Any, key: str) -> evidence_models.Term:
    """Get or create the organization's word for a kind of thing.

    Always allowed, for the same reason :func:`ensure_structure_kind` is: refusing
    to record "this is an AIS" because no graph had declared the word would be
    refusing a claim on a bookkeeping technicality. A graph's `Category` says what
    the word means *there*; this is only the word.

    ``kind`` is part of identity, so "AIS" as an entity and "AIS" as a relation are
    two terms rather than one term two things disagree about.
    """
    resolved = getattr(kind, "value", kind)
    term, _ = evidence_models.Term.all_objects.get_or_create(
        organization=organization,
        kind=str(resolved),
        key=key,
    )
    return term


def canonical_value_kind(value_kind: Any) -> str | None:
    """The canonical spelling of a value kind, or None if nothing was declared.

    Accepts a `ValueKind`, its string value, or the lowercase `PropertyType`
    spelling the GraphQL inputs still speak.
    """
    if value_kind is None:
        return None
    declared = getattr(value_kind, "value", value_kind)
    declared = _PROPERTY_TYPE_TO_VALUE_KIND.get(declared, declared)
    if declared not in _COLUMN_FOR_KIND:
        raise ValueError(f"Unknown value kind {value_kind!r}; expected one of {sorted(_COLUMN_FOR_KIND)}")
    return declared


def ensure_metric_kind(
    organization: Organization,
    structure_kind: evidence_models.StructureKind,
    key: str,
    value_kind: Any,
) -> evidence_models.MetricKind:
    """Get or create the organization's term for a kind of measurement.

    One branch, because the caller states the value kind and nothing guesses it.
    A declaration is therefore never refused: two tools measuring
    `roi.confidence`, one as a float and one as a category label, get two terms
    and both measurements are recorded.

    This used to guess when the caller said nothing — adopt the key's single
    existing term, or infer one from ``type(value)`` and mint, or raise when
    several terms existed. All three are gone, and the raise is why. Its message
    said "Declare one" while the inputs that reached it — `createMetric`,
    `updateMetric`, supporting evidence — had no field to declare with, so a key
    with two terms became unwritable through them. Requiring the kind removes the
    branch rather than repairing it, and takes the rest of the guessing with it:
    a term's identity is no longer decided by whether a measurement happened to
    be written ``45`` or ``45.2``.
    """
    declared = canonical_value_kind(value_kind)
    if declared is None:
        raise ValueError(f"Cannot record '{structure_kind.identifier}'.{key} without a value kind: it decides which column the value is stored in and which term it is recorded under, and nothing infers it.")

    kind, _ = evidence_models.MetricKind.all_objects.get_or_create(
        organization=organization,
        structure_kind=structure_kind,
        key=key,
        value_kind=declared,
    )
    return kind


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
) -> evidence_models.Metric:
    """Append a measurement.

    The row's value kind is the *term's*, not a separate argument. Since
    ``value_kind`` became part of `MetricKind`'s identity there is no coherent
    way for the two to differ: a row claiming STRING under a FLOAT term would be
    filed in a column its own term says nothing lives in, and would then fold
    into the state vector of a grain it does not belong to. Callers who want a
    different kind resolve a different term.

    ``measured_at`` defaults to the assertion time when the caller does not know
    when the observation happened, which is honest about the two axes being
    equal in that case rather than leaving the column null and unqueryable.
    """
    resolved = kind.value_kind

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
        **value_columns(value, resolved, key),
    )


def create_link(
    organization: Organization,
    *,
    kind: str,
    source_ref: str,
    target_ref: str,
    assertion: evidence_models.Assertion,
    term: evidence_models.Term | None = None,
    role: str | None = None,
) -> evidence_models.Link:
    """Attach evidence to something. Refs stay opaque — see `Link`.

    ``term`` is the organization's word for the claim, not a graph's category. A
    link that named a category could only be understood by the graph that owned
    it, which is not what a claim is.
    """
    return evidence_models.Link.objects.create_for_organization(
        organization=organization,
        kind=kind,
        source_ref=source_ref,
        target_ref=target_ref,
        assertion=assertion,
        term=term,
        role=role,
    )


#: Which claim target type each evidence row is. There is no longer a companion
#: set of "types that cache the answer": the answer is cached in `ClaimCurrent`
#: for all of them except `Node`, whose standing is per-view, and that exception
#: is expressed once — in `claims.CACHED_TARGETS` — rather than here as well.
_TARGET_TYPES: dict[type, str] = {
    evidence_models.Structure: "structure",
    evidence_models.Metric: "metric",
    evidence_models.Link: "link",
    evidence_models.Node: "node",
}


class ClaimResult(NamedTuple):
    """A recorded claim, and whether it changed the organization-wide answer.

    Two values because the two questions came apart when the log stopped
    deduplicating. A claim is always written — that is what makes concurrence
    countable — but `State` is folded from deltas, so it must move only on the
    edge. A caller that un-folds on ``claim`` rather than on ``moved`` subtracts a
    contribution that was already taken out.
    """

    claim: evidence_models.Claim
    moved: bool


def claim_ref(
    organization: Organization,
    *,
    target_type: str,
    target_id: str,
    stands: bool,
    assertion: evidence_models.Assertion,
    at: datetime.datetime | None = None,
) -> evidence_models.Claim:
    """Record somebody's position on whether a target stands.

    The low-level primitive: it takes a target type and a ref rather than a row,
    so it can be used for things that are not evidence rows. Prefer
    :func:`claim`, which resolves both from the object and maintains the cache.
    """
    return evidence_models.Claim.objects.create_for_organization(
        organization=organization,
        target_type=target_type,
        target_id=str(target_id),
        stands=stands,
        at=at or timezone.now(),
        assertion=assertion,
    )


@transaction.atomic
def claim(
    organization: Organization,
    target: Any,
    *,
    stands: bool,
    assertion: evidence_models.Assertion,
    at: datetime.datetime | None = None,
) -> ClaimResult:
    """Claim that a piece of evidence does or does not stand.

    **The only writer of retraction and attestation, for every kind of target.**
    There were two — one that wrote a lifecycle row and flipped a cached status,
    and one that only wrote the row — and which you got depended on whether the
    target happened to be in a lookup table. Nodes fell through to the second, so
    their cached status was never written and the filter that read it was a no-op.

    **Every claim is written.** Restating a position already held used to be
    suppressed: if the cached boolean already equalled the requested position, no
    row was created and the caller was handed somebody else's earlier claim. So a
    second annotator independently retracting the same metric left no trace, and
    agreement was not countable on the existence axis — while `__assertion_count`
    exists on the relation axis to make exactly that countable. The log records
    who said what; concurrence is not noise.

    The suppression was load-bearing for something else, which is why it could not
    simply be deleted: `state.merge`/`state.retract` are deltas rather than
    idempotent operations, so folding the same retraction twice subtracts a value
    already taken out. That guard now lives on the transition instead — see the
    ``moved`` flag below and :func:`evidence.claims.record_current`. The claim is
    always recorded; only the *fold* is conditional.

    Returns the claim, and whether the organization-wide answer moved. Callers
    that un-fold state must act on the second value, never on the first.
    """
    target_type = _TARGET_TYPES.get(type(target))
    if target_type is None:
        raise TypeError(f"{type(target).__name__} is not something a claim can be about")

    written = claim_ref(
        organization,
        target_type=target_type,
        target_id=str(target.pk),
        stands=stands,
        assertion=assertion,
        at=at,
    )

    # The projection, not the log row. `ClaimCurrent` is what the hot read paths
    # narrow by, and updating it here rather than on the target is what leaves the
    # log tables immutable.
    moved = claims_module.record_current(organization, target_type, target.pk, written)
    return ClaimResult(claim=written, moved=moved)


def retract(
    organization: Organization,
    target: Any,
    assertion: evidence_models.Assertion,
    at: datetime.datetime | None = None,
) -> ClaimResult:
    """Claim that a target no longer stands. Named for what it does to the record."""
    return claim(organization, target, stands=False, assertion=assertion, at=at)


def attest(
    organization: Organization,
    target: Any,
    assertion: evidence_models.Assertion,
    at: datetime.datetime | None = None,
) -> ClaimResult:
    """Claim that a target stands — new evidence, not the undoing of a retraction."""
    return claim(organization, target, stands=True, assertion=assertion, at=at)


def standing_metrics_for_kind(kind: evidence_models.MetricKind) -> Any:
    """Every un-retracted metric recorded under one metric kind.

    Sibling of :func:`active_metrics_for_structures` — same standing filter, a
    different axis to slice on. Ordered by observation time so a caller reading a
    kind's history gets it in the order the world happened, not the order rows
    arrived.
    """
    standing = claims_module.standing(
        evidence_models.Metric.objects.for_organization(kind.organization).filter(kind=kind),
        "metric",
    )
    return standing.order_by("measured_at")


def active_metrics_for_structures(
    organization: Organization,
    structure_ids: Iterable[Any],
) -> Any:
    """Every un-retracted metric describing the given structures.

    The read path the projector will fold over in M3, and the SQL replacement
    for the Cypher `MATCH (m:Metric)-[:DESCRIBES]->(s)` that rollups used to
    walk.
    """
    standing = claims_module.standing(
        evidence_models.Metric.objects.for_organization(organization).filter(structure_id__in=list(structure_ids)),
        "metric",
    )
    return standing.order_by("measured_at")
