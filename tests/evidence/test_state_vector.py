"""Incremental maintenance must agree with a full recompute.

The state vector's entire justification is that every aggregation is a monoid
over `{n, sum, min, max, first, last}`, so a metric can be folded in as it
arrives instead of re-reading history. That claim is easy to state and easy to
get subtly wrong — an off-by-one in `n`, a `min` that never updates, a `last`
that follows arrival order rather than observation time.

So it is checked the only way that means anything: fold a random sequence of
metrics incrementally, rebuild the same row from scratch, and require the two to
match for all eight aggregations.

**The generator emits mixed value kinds on purpose.** Equality between
incremental and recompute is blind to a whole class of bug on its own: when the
grain was `(entity, source_kind, key)` and a key had both a FLOAT and a STRING
term, both folded into one row, `MEAN` divided a numeric sum by a count that
included the strings — and `recompute` filtered the same way, so it reproduced
the error faithfully and this test passed. Two wrong answers agreeing is not
evidence. So the sequence below interleaves string measurements under the same
key, and the numeric row's `n` is asserted directly against the number of
numeric values rather than only against a rebuild of itself.
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
    key: str = "vector_length",
) -> evidence_models.Metric:
    return writer.record_metric(
        organization,
        structure,
        category,
        key=key,
        value=value,
        assertion=assertion,
        measured_at=BASE_TIME + timedelta(minutes=offset_minutes),
    )


def _term(organization: Organization, structure_kind: evidence_models.StructureKind, key: str, value_kind: ValueKind) -> evidence_models.MetricKind:
    """A measurement term of a given type. Declared, so it is never inferred."""
    return writer.ensure_metric_kind(organization, structure_kind, key, value_kind)


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
    followed insertion order instead of `measured_at` would be caught. String
    measurements are interleaved under the same key — see the module docstring
    for why equality alone would not notice them.
    """
    rng = random.Random(seed)
    values = [round(rng.uniform(-50, 50), 3) for _ in range(rng.randint(2, 12))]
    labels = [f"label-{index}" for index in range(rng.randint(1, 4))]
    offsets = rng.sample(range(0, 1000), len(values) + len(labels))

    label_term = _term(organization, linked_structure.kind, "vector_length", ValueKind.STRING)

    for value, offset in zip(values, offsets):
        metric = _record(organization, linked_structure, length_category, assertion, value, offset)
        state_module.merge(metric, [ENTITY_REF])

    for label, offset in zip(labels, offsets[len(values) :]):
        metric = _record(organization, linked_structure, label_term, assertion, label, offset)
        state_module.merge(metric, [ENTITY_REF])

    incremental = evidence_models.State.objects.for_organization(organization).get(entity_ref=ENTITY_REF, source_kind=linked_structure.kind, key="vector_length", value_kind=ValueKind.FLOAT.value)

    # The sighted assertion. Under the old grain the strings landed here too, so
    # `n` over-counted and MEAN was sum/(numeric + string) — and recompute made
    # the same mistake, which is exactly why the equality below could not see it.
    assert incremental.n == len(values), "The numeric row must count numeric measurements only"
    assert aggregate.apply(AggregationFunction.MEAN, incremental) == pytest.approx(sum(values) / len(values))

    incremental_reads = {agg: aggregate.apply(agg, incremental) for agg in ALL_AGGREGATIONS}

    rebuilt = state_module.recompute(incremental)
    rebuilt_reads = {agg: aggregate.apply(agg, rebuilt) for agg in ALL_AGGREGATIONS}

    for agg in ALL_AGGREGATIONS:
        incremental_value, rebuilt_value = incremental_reads[agg], rebuilt_reads[agg]
        if isinstance(incremental_value, float) and isinstance(rebuilt_value, float):
            assert incremental_value == pytest.approx(rebuilt_value), f"{agg.value} drifted"
        else:
            assert incremental_value == rebuilt_value, f"{agg.value} drifted"

    # The string row is maintained independently, and recompute agrees there too.
    strings = evidence_models.State.objects.for_organization(organization).get(entity_ref=ENTITY_REF, source_kind=linked_structure.kind, key="vector_length", value_kind=ValueKind.STRING.value)
    assert strings.n == len(labels)
    assert strings.sum is None, "Strings contribute to COUNT, never to SUM"
    rebuilt_strings = state_module.recompute(strings)
    assert rebuilt_strings.n == len(labels)
    assert aggregate.apply(AggregationFunction.LATEST, rebuilt_strings) == aggregate.apply(AggregationFunction.LATEST, strings)


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
    # The row's value kind is the term's, not an argument — see
    # `writer.record_metric`. A STRING measurement means a STRING term.
    label_term = _term(organization, linked_structure.kind, "label", ValueKind.STRING)
    metric = writer.record_metric(
        organization,
        linked_structure,
        label_term,
        key="label",
        value="apical",
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
    centroid_term = _term(organization, linked_structure.kind, "centroid", ValueKind.THREE_D_VECTOR)
    for offset, point in ((0, [0.0, 0.0, 0.0]), (10, [3.0, 4.0, 0.0])):
        metric = writer.record_metric(
            organization,
            linked_structure,
            centroid_term,
            key="centroid",
            value=point,
            assertion=assertion,
            measured_at=BASE_TIME + timedelta(minutes=offset),
        )
        state_module.merge(metric, [ENTITY_REF])

    state = evidence_models.State.objects.for_organization(organization).get(key="centroid")

    assert aggregate.apply(AggregationFunction.EUCLIDEAN_RANGE, state) == pytest.approx(5.0)
