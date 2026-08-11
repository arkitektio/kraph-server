"""Incremental maintenance must agree with a full recompute.

The state vector's entire justification is that every aggregation is a monoid
over `{n, sum, min, max, first, last}`, so a metric can be folded in as it
arrives instead of re-reading history. That claim is easy to state and easy to
get subtly wrong — an off-by-one in `n`, a `min` that never updates, a `last`
that follows arrival order rather than observation time.

So it is checked the only way that means anything: fold a random sequence of
metrics incrementally, rebuild the same row from scratch, and require the two to
match for all eight aggregations.
"""

import random

import pytest
from authentikate.models import Organization

from core import models as core_models
from core.enums import ValueKind
from evidence import models as evidence_models
from evidence import state as state_module
from evidence import writer
from graph_engine import aggregate
from graph_engine.input_models import AggregationFunction

from datetime import datetime, timedelta, timezone

BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)
ENTITY_REF = "graph_a_evidence_org:844424930131969"

ALL_AGGREGATIONS = [
    AggregationFunction.MEAN,
    AggregationFunction.SUM,
    AggregationFunction.MIN,
    AggregationFunction.MAX,
    AggregationFunction.COUNT,
    AggregationFunction.RANGE,
    AggregationFunction.LATEST,
]


def _record(
    organization: Organization,
    structure: evidence_models.Structure,
    category: evidence_models.MetricKind,
    assertion: evidence_models.Assertion,
    value: float,
    offset_minutes: int,
) -> evidence_models.Metric:
    return writer.record_metric(
        organization,
        structure,
        category,
        key="vector_length",
        value=value,
        assertion=assertion,
        measured_at=BASE_TIME + timedelta(minutes=offset_minutes),
    )


@pytest.fixture
def linked_structure(
    organization: Organization,
    roi_category_a: evidence_models.StructureKind,
    assertion: evidence_models.Assertion,
) -> evidence_models.Structure:
    """A structure that informs one entity, so its metrics have somewhere to roll up to."""
    structure = writer.ensure_structure(organization, roi_category_a, "roi-state", assertion)
    writer.create_link(
        organization,
        kind=evidence_models.Link.Kind.INFORMS,
        source_ref=str(structure.pk),
        target_ref=ENTITY_REF,
        assertion=assertion,
    )
    return structure


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_incremental_merge_equals_full_recompute(
    seed: int,
    organization: Organization,
    linked_structure: evidence_models.Structure,
    length_category: evidence_models.MetricKind,
    assertion: evidence_models.Assertion,
) -> None:
    """Folding one at a time must land where rebuilding from scratch lands.

    Values and observation times are both shuffled, so a `last_value` that
    followed insertion order instead of `measured_at` would be caught.
    """
    rng = random.Random(seed)
    values = [round(rng.uniform(-50, 50), 3) for _ in range(rng.randint(2, 12))]
    offsets = rng.sample(range(0, 1000), len(values))

    for value, offset in zip(values, offsets):
        metric = _record(organization, linked_structure, length_category, assertion, value, offset)
        state_module.merge(metric, [ENTITY_REF])

    incremental = evidence_models.State.objects.for_organization(organization).get(entity_ref=ENTITY_REF, source_kind=linked_structure.kind, key="vector_length")
    incremental_reads = {agg: aggregate.apply(agg, incremental) for agg in ALL_AGGREGATIONS}

    rebuilt = state_module.recompute(incremental)
    rebuilt_reads = {agg: aggregate.apply(agg, rebuilt) for agg in ALL_AGGREGATIONS}

    for agg in ALL_AGGREGATIONS:
        incremental_value, rebuilt_value = incremental_reads[agg], rebuilt_reads[agg]
        if isinstance(incremental_value, float) and isinstance(rebuilt_value, float):
            assert incremental_value == pytest.approx(rebuilt_value), f"{agg.value} drifted"
        else:
            assert incremental_value == rebuilt_value, f"{agg.value} drifted"


def test_last_value_follows_observation_time_not_arrival(
    organization: Organization,
    linked_structure: evidence_models.Structure,
    length_category: evidence_models.MetricKind,
    assertion: evidence_models.Assertion,
) -> None:
    """A backfilled old measurement must not become LATEST.

    This is the bitemporal split doing real work: ingesting a year-old
    observation today should not overwrite what we currently believe.
    """
    recent = _record(organization, linked_structure, length_category, assertion, 10.0, offset_minutes=500)
    state_module.merge(recent, [ENTITY_REF])

    backfilled = _record(organization, linked_structure, length_category, assertion, 99.0, offset_minutes=1)
    state_module.merge(backfilled, [ENTITY_REF])

    state = evidence_models.State.objects.for_organization(organization).get(entity_ref=ENTITY_REF)

    assert aggregate.apply(AggregationFunction.LATEST, state) == 10.0
    assert state.first_value == 99.0, "The backfilled row is the earliest observation"


def test_count_counts_non_numeric_values_too(
    organization: Organization,
    linked_structure: evidence_models.Structure,
    length_category: evidence_models.MetricKind,
    assertion: evidence_models.Assertion,
) -> None:
    """A string measurement contributes to COUNT and LATEST but not to SUM.

    Silently dropping it from `n` would make COUNT disagree with the number of
    metrics actually recorded.
    """
    metric = writer.record_metric(
        organization,
        linked_structure,
        length_category,
        key="label",
        value="apical",
        value_kind=ValueKind.STRING.value,
        assertion=assertion,
    )
    state_module.merge(metric, [ENTITY_REF])

    state = evidence_models.State.objects.for_organization(organization).get(key="label")

    assert aggregate.apply(AggregationFunction.COUNT, state) == 1
    assert aggregate.apply(AggregationFunction.LATEST, state) == "apical"
    assert aggregate.apply(AggregationFunction.SUM, state) is None
    assert aggregate.apply(AggregationFunction.MEAN, state) is None


def test_no_evidence_reads_as_none_for_every_aggregation() -> None:
    """A missing row means "nobody measured", and COUNT must say so too.

    Returning 0 for COUNT would be a claim that somebody looked and found
    nothing, which is a different statement.
    """
    for agg in ALL_AGGREGATIONS:
        assert aggregate.apply(agg, None) is None


def test_euclidean_range_is_dimension_agnostic(
    organization: Organization,
    linked_structure: evidence_models.Structure,
    length_category: evidence_models.MetricKind,
    assertion: evidence_models.Assertion,
) -> None:
    """Distance between first and last point, for any vector length.

    The Cypher this replaces hardcoded x/y/z and used `^`, which Apache AGE does
    not implement — so EUCLIDEAN_RANGE could never actually have run.
    """
    for offset, point in ((0, [0.0, 0.0, 0.0]), (10, [3.0, 4.0, 0.0])):
        metric = writer.record_metric(
            organization,
            linked_structure,
            length_category,
            key="centroid",
            value=point,
            value_kind=ValueKind.THREE_D_VECTOR.value,
            assertion=assertion,
            measured_at=BASE_TIME + timedelta(minutes=offset),
        )
        state_module.merge(metric, [ENTITY_REF])

    state = evidence_models.State.objects.for_organization(organization).get(key="centroid")

    assert aggregate.apply(AggregationFunction.EUCLIDEAN_RANGE, state) == pytest.approx(5.0)
