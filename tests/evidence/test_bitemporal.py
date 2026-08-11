"""Observation time and belief time move independently.

The old model had a single ms-epoch `timestamp` property doing both jobs, which
makes the scientifically interesting question — *what did we believe on March
3rd?* — unanswerable, because there is no way to distinguish "measured later"
from "claimed later". Splitting the axes is a column decision, which is why it
lands with the tables rather than in the API milestone that consumes it.

The shape that matters: a re-analysis run **today** can assert a fact about an
image taken **last year**, and a correction issued today about the same
observation must be orderable against the original claim.
"""

from datetime import datetime, timezone

from core.enums import ValueKind
from evidence import models as evidence_models
from authentikate.models import Organization
from core import models as core_models

LAST_YEAR = datetime(2025, 3, 1, 9, 0, tzinfo=timezone.utc)
TODAY = datetime(2026, 8, 11, 9, 0, tzinfo=timezone.utc)
YESTERDAY = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)


def _structure(
    organization: Organization,
    category: evidence_models.StructureKind,
    assertion: evidence_models.Assertion,
    object_id: str = "roi-1",
) -> evidence_models.Structure:
    """A structure to hang measurements off."""
    return evidence_models.Structure.objects.create_for_organization(
        organization=organization,
        kind=category,
        identifier="@mikro/roi",
        object=object_id,
        assertion=assertion,
    )


def _metric(
    organization: Organization,
    structure: evidence_models.Structure,
    category: evidence_models.MetricKind,
    assertion: evidence_models.Assertion,
    *,
    value: float,
    measured_at: datetime,
    asserted_at: datetime,
) -> evidence_models.Metric:
    """One measurement, with both time axes set explicitly."""
    return evidence_models.Metric.objects.create_for_organization(
        organization=organization,
        structure=structure,
        kind=category,
        key="vector_length",
        value_kind=ValueKind.FLOAT.value,
        value_num=value,
        measured_at=measured_at,
        asserted_at=asserted_at,
        assertion=assertion,
    )


def test_the_two_axes_are_independently_settable(organization: Organization, roi_category_a: evidence_models.StructureKind, length_category: evidence_models.MetricKind, assertion: evidence_models.Assertion) -> None:
    """A claim made today about something observed last year."""
    structure = _structure(organization, roi_category_a, assertion)
    metric = _metric(
        organization,
        structure,
        length_category,
        assertion,
        value=45.2,
        measured_at=LAST_YEAR,
        asserted_at=TODAY,
    )

    metric.refresh_from_db()
    assert metric.measured_at == LAST_YEAR
    assert metric.asserted_at == TODAY


def test_as_of_selects_by_belief_time_not_observation_time(organization: Organization, roi_category_a: evidence_models.StructureKind, length_category: evidence_models.MetricKind, assertion: evidence_models.Assertion) -> None:
    """The query `as_of` will be built on.

    Two claims about the *same* observation, one correcting the other. Filtering
    on `asserted_at` recovers what was believed at a chosen moment — which is
    impossible if the two axes share a column.
    """
    structure = _structure(organization, roi_category_a, assertion)

    _metric(
        organization,
        structure,
        length_category,
        assertion,
        value=45.2,
        measured_at=LAST_YEAR,
        asserted_at=YESTERDAY,
    )
    _metric(
        organization,
        structure,
        length_category,
        assertion,
        value=47.9,
        measured_at=LAST_YEAR,
        asserted_at=TODAY,
    )

    believed_yesterday = evidence_models.Metric.objects.for_organization(organization).filter(asserted_at__lte=YESTERDAY).order_by("-asserted_at")
    believed_now = evidence_models.Metric.objects.for_organization(organization).order_by("-asserted_at")

    assert believed_yesterday.count() == 1
    assert believed_yesterday.first().value == 45.2
    assert believed_now.first().value == 47.9


def test_observation_window_selects_by_measured_at(organization: Organization, roi_category_a: evidence_models.StructureKind, length_category: evidence_models.MetricKind, assertion: evidence_models.Assertion) -> None:
    """The other axis: 'measurements taken during last year's run'.

    Both rows below were asserted at the same instant, so only `measured_at`
    can separate them.
    """
    structure = _structure(organization, roi_category_a, assertion)

    _metric(
        organization,
        structure,
        length_category,
        assertion,
        value=1.0,
        measured_at=LAST_YEAR,
        asserted_at=TODAY,
    )
    _metric(
        organization,
        structure,
        length_category,
        assertion,
        value=2.0,
        measured_at=TODAY,
        asserted_at=TODAY,
    )

    observed_last_year = evidence_models.Metric.objects.for_organization(organization).filter(measured_at__lt=datetime(2026, 1, 1, tzinfo=timezone.utc))

    assert [m.value for m in observed_last_year] == [1.0]


def test_recorded_at_is_not_asserted_at(organization: Organization, roi_category_a: evidence_models.StructureKind, length_category: evidence_models.MetricKind, assertion: evidence_models.Assertion) -> None:
    """Ingest time is a third thing, and must not be mistaken for belief time.

    `recorded_at` is auto-stamped when the row is stored. Backfilling a year of
    historical claims would give every row the same `recorded_at` and wildly
    different `asserted_at`, so answering questions from `recorded_at` would be
    silently wrong.
    """
    structure = _structure(organization, roi_category_a, assertion)
    _metric(
        organization,
        structure,
        length_category,
        assertion,
        value=1.0,
        measured_at=LAST_YEAR,
        asserted_at=LAST_YEAR,
    )

    assertion.refresh_from_db()
    assert assertion.asserted_at == datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    assert assertion.recorded_at > assertion.asserted_at


def test_value_kind_selects_the_value_column(organization: Organization, roi_category_a: evidence_models.StructureKind, length_category: evidence_models.MetricKind, assertion: evidence_models.Assertion) -> None:
    """Each ValueKind reads back through the column its kind designates.

    The typed-column split is what keeps numeric aggregation in the database
    instead of in Python, so the mapping has to be exhaustive and exercised.
    """
    structure = _structure(organization, roi_category_a, assertion)

    cases = [
        (ValueKind.FLOAT, {"value_num": 45.2}, 45.2),
        (ValueKind.INT, {"value_num": 3}, 3),
        (ValueKind.STRING, {"value_txt": "apical"}, "apical"),
        (ValueKind.CATEGORY, {"value_txt": "neuron"}, "neuron"),
        (ValueKind.BOOLEAN, {"value_bool": True}, True),
        (ValueKind.DATETIME, {"value_time": LAST_YEAR}, LAST_YEAR),
        (ValueKind.THREE_D_VECTOR, {"value_json": [1.0, 2.0, 3.0]}, [1.0, 2.0, 3.0]),
    ]

    for kind, columns, expected in cases:
        metric = evidence_models.Metric.objects.create_for_organization(
            organization=organization,
            structure=structure,
            kind=length_category,
            key=f"probe_{kind.value}",
            value_kind=kind.value,
            measured_at=LAST_YEAR,
            asserted_at=TODAY,
            assertion=assertion,
            **columns,
        )
        metric.refresh_from_db()
        assert metric.value == expected, f"{kind.value} did not round-trip"
        # `==` is not enough for INT: it shares `value_num` with FLOAT, and
        # `3.0 == 3` would let an integer metric silently come back as a float.
        assert type(metric.value) is type(expected), f"{kind.value} round-tripped as {type(metric.value).__name__}"
