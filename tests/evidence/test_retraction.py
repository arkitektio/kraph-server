"""Retracting a metric, and the two kinds of statistic it meets.

SUM, COUNT and MEAN are group operations: the contribution subtracts exactly, so
retraction stays O(1) and the row is immediately correct.

MIN, MAX, RANGE, LATEST and EUCLIDEAN_RANGE are not. The value being removed may
be the very one that set the extremum, and nothing in the row says what the
runner-up was. The honest response is to mark the row stale and rebuild it from
surviving evidence — not to leave the old maximum in place, which would report a
number no remaining measurement supports.
"""

from datetime import datetime, timedelta, timezone

import pytest
from authentikate.models import Organization

from core import models as core_models
from core.enums import ValueKind
from evidence import models as evidence_models
from evidence import state as state_module
from evidence import writer
from graph_engine import aggregate
from graph_engine.input_models import AggregationFunction

BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)
ENTITY_REF = "graph_a_evidence_org:844424930131971"


@pytest.fixture
def measured(
    organization: Organization,
    roi_category_a: evidence_models.StructureKind,
    length_category: evidence_models.MetricKind,
    assertion: evidence_models.Assertion,
) -> tuple[evidence_models.Structure, list[evidence_models.Metric]]:
    """Three measurements — 10, 30, 20 — where 30 is both the max and not the latest."""
    structure = writer.ensure_structure(organization, roi_category_a, "roi-retract", assertion)
    writer.create_link(
        organization,
        kind=evidence_models.Link.Kind.INFORMS,
        source_ref=str(structure.pk),
        target_ref=ENTITY_REF,
        assertion=assertion,
    )

    metrics = []
    for index, value in enumerate([10.0, 30.0, 20.0]):
        metric = writer.record_metric(
            organization,
            structure,
            length_category,
            key="vector_length",
            value=value,
            assertion=assertion,
            measured_at=BASE_TIME + timedelta(minutes=index),
        )
        state_module.merge(metric, [ENTITY_REF])
        metrics.append(metric)

    return structure, metrics


def test_group_statistics_subtract_without_a_recompute(
    organization: Organization,
    measured: tuple[evidence_models.Structure, list[evidence_models.Metric]],
) -> None:
    """Retracting the middle value fixes SUM and COUNT immediately.

    Note the row *is* still flagged, because 30 was also the max — but SUM and
    COUNT are already correct before any rebuild runs.
    """
    _, metrics = measured
    state_module.retract(metrics[1], [ENTITY_REF])

    state = evidence_models.State.objects.for_organization(organization).get(entity_ref=ENTITY_REF)

    assert aggregate.apply(AggregationFunction.COUNT, state) == 2
    assert aggregate.apply(AggregationFunction.SUM, state) == pytest.approx(30.0)
    assert aggregate.apply(AggregationFunction.MEAN, state) == pytest.approx(15.0)


def test_retracting_the_maximum_flags_the_row(
    organization: Organization,
    measured: tuple[evidence_models.Structure, list[evidence_models.Metric]],
) -> None:
    """MAX cannot be un-merged, so the row must admit it is stale."""
    _, metrics = measured
    state_module.retract(metrics[1], [ENTITY_REF])

    state = evidence_models.State.objects.for_organization(organization).get(entity_ref=ENTITY_REF)
    assert state.needs_recompute, "Removing the extremum must mark the row for rebuild"


def test_retracting_a_middling_value_does_not_flag_the_row(
    organization: Organization,
    measured: tuple[evidence_models.Structure, list[evidence_models.Metric]],
) -> None:
    """A value that set neither an extremum nor an endpoint costs nothing.

    If every retraction forced a rebuild, the O(1) claim would be hollow.
    """
    structure, metrics = measured
    extra = writer.record_metric(
        organization,
        structure,
        metrics[0].kind,
        key="vector_length",
        value=15.0,
        assertion=metrics[0].assertion,
        measured_at=BASE_TIME + timedelta(minutes=90),
    )
    state_module.merge(extra, [ENTITY_REF])

    # 15.0 is neither min (10) nor max (30); but it *is* now the latest, so
    # retract a genuinely interior one instead.
    state_module.retract(metrics[2], [ENTITY_REF])  # 20.0 at minute 2

    state = evidence_models.State.objects.for_organization(organization).get(entity_ref=ENTITY_REF)
    assert not state.needs_recompute
    assert aggregate.apply(AggregationFunction.MAX, state) == 30.0


def test_recompute_restores_correctness_after_a_flagged_retraction(
    organization: Organization,
    measured: tuple[evidence_models.Structure, list[evidence_models.Metric]],
) -> None:
    """The rebuild produces the answer the surviving evidence supports."""
    _, metrics = measured

    writer.retract(organization, metrics[1], metrics[1].assertion)
    state_module.retract(metrics[1], [ENTITY_REF])

    state = evidence_models.State.objects.for_organization(organization).get(entity_ref=ENTITY_REF)
    assert state.needs_recompute

    rebuilt = state_module.recompute(state)

    assert not rebuilt.needs_recompute
    assert aggregate.apply(AggregationFunction.MAX, rebuilt) == 20.0, "30 was retracted; 20 is the survivor"
    assert aggregate.apply(AggregationFunction.COUNT, rebuilt) == 2
    assert aggregate.apply(AggregationFunction.SUM, rebuilt) == pytest.approx(30.0)


def test_reading_a_stale_row_rebuilds_it_first(
    organization: Organization,
    roi_category_a: evidence_models.StructureKind,
    measured: tuple[evidence_models.Structure, list[evidence_models.Metric]],
) -> None:
    """A caller must never see a value the evidence no longer supports.

    `state_for` is the read entry point precisely so staleness cannot leak: a
    flagged row is rebuilt on the way out rather than returned as-is.
    """
    _, metrics = measured
    writer.retract(organization, metrics[1], metrics[1].assertion)
    state_module.retract(metrics[1], [ENTITY_REF])

    state = state_module.state_for(organization, ENTITY_REF, roi_category_a, "vector_length", [ValueKind.FLOAT.value])

    assert state is not None
    assert not state.needs_recompute
    assert aggregate.apply(AggregationFunction.MAX, state) == 20.0
