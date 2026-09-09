"""The state vector is a monoid: incremental maintenance agrees with a full recompute (A7).

Every aggregation folds over `{n, sum, min, max, first, last}`, so a metric can
be folded in as it arrives. Fold a random sequence incrementally, rebuild the
same row from scratch, and require the two to match for all eight
aggregations — with mixed value kinds interleaved, because two wrong answers
agreeing is not evidence. The rows are the organization-grain cache the
projection reads (`state_for_many`), not part of the log.
"""

import random
import pytest
from authentikate.models import Organization
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
        observed_at=BASE_TIME + timedelta(minutes=offset_minutes),
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
    followed insertion order instead of `observed_at` would be caught. String
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

    incremental = evidence_models.State.objects.for_organization(organization).get(claim_ref=ENTITY_REF, source_kind=linked_structure.kind, key="vector_length", value_kind=ValueKind.FLOAT.value)

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
    strings = evidence_models.State.objects.for_organization(organization).get(claim_ref=ENTITY_REF, source_kind=linked_structure.kind, key="vector_length", value_kind=ValueKind.STRING.value)
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

    state = evidence_models.State.objects.for_organization(organization).get(claim_ref=ENTITY_REF)

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


    History: the query this replaces hardcoded x/y/z and used an operator the
    graph database did not implement — so EUCLIDEAN_RANGE could never have run.
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
            observed_at=BASE_TIME + timedelta(minutes=offset),
        )
        state_module.merge(metric, [ENTITY_REF])

    state = evidence_models.State.objects.for_organization(organization).get(key="centroid")

    assert aggregate.apply(AggregationFunction.EUCLIDEAN_RANGE, state) == pytest.approx(5.0)
REINTERPRETED_REF = "graph_a_evidence_org:844424930131970"
VALUES = [10.0, 30.0, 20.0]
@pytest.fixture
def measured_entity(
    organization: Organization,
    roi_category_a: evidence_models.StructureKind,
    length_category: evidence_models.MetricKind,
    assertion: evidence_models.Assertion,
) -> evidence_models.State:
    """Three measurements folded into one state vector."""
    structure = writer.ensure_structure(organization, roi_category_a, "roi-reinterpret", assertion)
    writer.create_link(
        organization,
        kind=evidence_models.Link.Kind.INFORMS,
        source_ref=str(structure.pk),
        target_ref=REINTERPRETED_REF,
        assertion=assertion,
    )

    for index, value in enumerate(VALUES):
        metric = writer.record_metric(
            organization,
            structure,
            length_category,
            key="vector_length",
            value=value,
            assertion=assertion,
            observed_at=BASE_TIME + timedelta(minutes=index),
        )
        state_module.merge(metric, [REINTERPRETED_REF])

    return evidence_models.State.objects.for_organization(organization).get(claim_ref=REINTERPRETED_REF)
def test_switching_mean_to_max_changes_the_value_with_zero_writes(
    organization: Organization,
    measured_entity: evidence_models.State,
) -> None:
    """The headline claim, stated as plainly as it can be.

    Read MEAN. Read MAX. Get different answers. Verify nothing was written to
    either the evidence or the statistics in between — not even a timestamp.
    """
    metric_count_before = evidence_models.Metric.objects.for_organization(organization).count()
    state_updated_before = measured_entity.updated_at

    assert aggregate.apply(AggregationFunction.MEAN, measured_entity) == pytest.approx(20.0)

    # The "schema change": nothing but a different function reading the same row.
    assert aggregate.apply(AggregationFunction.MAX, measured_entity) == 30.0

    measured_entity.refresh_from_db()
    assert evidence_models.Metric.objects.for_organization(organization).count() == metric_count_before, "Re-aggregating must not touch the evidence"
    assert measured_entity.updated_at == state_updated_before, "Re-aggregating must not touch the statistics either"
def test_every_aggregation_reads_the_same_untouched_row(
    organization: Organization,
    measured_entity: evidence_models.State,
) -> None:
    """All eight are available simultaneously off one row.

    They are not alternative *storages*, they are alternative *readings* — which
    is why a graph can change its mind, and (after M7) why two graphs could
    disagree about the aggregation while sharing the evidence underneath.
    """
    readings = {
        AggregationFunction.MEAN: 20.0,
        AggregationFunction.SUM: 60.0,
        AggregationFunction.MIN: 10.0,
        AggregationFunction.MAX: 30.0,
        AggregationFunction.COUNT: 3,
        AggregationFunction.RANGE: 20.0,
        AggregationFunction.LATEST: 20.0,
    }

    state_updated_before = measured_entity.updated_at

    for aggregation, expected in readings.items():
        actual = aggregate.apply(aggregation, measured_entity)
        assert actual == pytest.approx(expected), f"{aggregation.value} read {actual}, expected {expected}"

    measured_entity.refresh_from_db()
    assert measured_entity.updated_at == state_updated_before
MIXED_REF = "graph_a_evidence_org:844424930131969"
@pytest.fixture
def informing_structure(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
    assertion: evidence_models.Assertion,
) -> evidence_models.Structure:
    """One ROI, informing one entity."""
    structure = writer.ensure_structure(organization, roi_kind, "roi-mixed", assertion)
    writer.create_link(
        organization,
        kind=evidence_models.Link.Kind.INFORMS,
        source_ref=str(structure.pk),
        target_ref=MIXED_REF,
        assertion=assertion,
    )
    return structure
def _record_typed(
    organization: Organization,
    structure: evidence_models.Structure,
    assertion: evidence_models.Assertion,
    value: object,
    value_kind: ValueKind,
    offset_minutes: int,
    key: str = "confidence",
) -> evidence_models.Metric:
    term = writer.ensure_metric_kind(organization, structure.kind, key, value_kind)
    metric = writer.record_metric(
        organization,
        structure,
        term,
        key=key,
        value=value,
        assertion=assertion,
        observed_at=BASE_TIME + timedelta(minutes=offset_minutes),
    )
    state_module.merge(metric, [MIXED_REF])
    return metric
def test_a_string_measurement_does_not_move_the_numeric_mean(
    organization: Organization,
    informing_structure: evidence_models.Structure,
    assertion: evidence_models.Assertion,
) -> None:
    """40, 60 and "big" under one key. MEAN is 50, not 33.3.

    The load-bearing assertion of this change. On the old grain the string
    incremented `n` without touching `sum`, so the mean of two numbers came out
    as their total over three.
    """
    _record_typed(organization, informing_structure, assertion, 40.0, ValueKind.FLOAT, 0)
    _record_typed(organization, informing_structure, assertion, 60.0, ValueKind.FLOAT, 10)
    _record_typed(organization, informing_structure, assertion, "big", ValueKind.STRING, 20)

    numeric = state_module.state_for(organization, MIXED_REF, informing_structure.kind, "confidence", [ValueKind.FLOAT.value])

    assert numeric is not None
    assert numeric.n == 2, "The string is not a contributor to the numeric statistic"
    assert aggregate.apply(AggregationFunction.MEAN, numeric) == pytest.approx(50.0)
    assert aggregate.apply(AggregationFunction.SUM, numeric) == pytest.approx(100.0)
def test_each_term_keeps_its_own_statistics(
    organization: Organization,
    informing_structure: evidence_models.Structure,
    assertion: evidence_models.Assertion,
) -> None:
    """And the string term is not merely discarded — it is maintained separately.

    Dropping the non-numeric measurements would be a different bug wearing the
    same fix: COUNT over the labels would report zero where three were recorded.
    """
    _record_typed(organization, informing_structure, assertion, 40.0, ValueKind.FLOAT, 0)
    _record_typed(organization, informing_structure, assertion, "big", ValueKind.STRING, 20)
    _record_typed(organization, informing_structure, assertion, "small", ValueKind.STRING, 30)

    rows = evidence_models.State.objects.for_organization(organization).filter(claim_ref=MIXED_REF, key="confidence")
    assert rows.count() == 2, "One row per value kind"

    labels = state_module.state_for(organization, MIXED_REF, informing_structure.kind, "confidence", [ValueKind.STRING.value])
    assert labels is not None
    assert aggregate.apply(AggregationFunction.COUNT, labels) == 2
    assert aggregate.apply(AggregationFunction.LATEST, labels) == "small"
    assert aggregate.apply(AggregationFunction.MEAN, labels) is None, "There is no mean of labels"
def test_recompute_agrees_per_row(
    organization: Organization,
    informing_structure: evidence_models.Structure,
    assertion: evidence_models.Assertion,
) -> None:
    """The backstop, now that it can actually see the split.

    `recompute` filters metrics by the row's `value_kind`. Before it did not, so
    rebuilding a mixed row reproduced the same over-count and this comparison was
    vacuous.
    """
    _record_typed(organization, informing_structure, assertion, 40.0, ValueKind.FLOAT, 0)
    _record_typed(organization, informing_structure, assertion, 60.0, ValueKind.FLOAT, 10)
    _record_typed(organization, informing_structure, assertion, "big", ValueKind.STRING, 20)

    for row in evidence_models.State.objects.for_organization(organization).filter(claim_ref=MIXED_REF, key="confidence"):
        before = row.n
        rebuilt = state_module.recompute(row)
        assert rebuilt.n == before, f"{row.value_kind} row changed on rebuild"

    numeric = evidence_models.State.objects.for_organization(organization).get(claim_ref=MIXED_REF, key="confidence", value_kind=ValueKind.FLOAT.value)
    assert aggregate.apply(AggregationFunction.MEAN, numeric) == pytest.approx(50.0)
def test_int_and_float_are_read_as_one_quantity(
    organization: Organization,
    informing_structure: evidence_models.Structure,
    assertion: evidence_models.Assertion,
) -> None:
    """Two terms, one statistic — the only widening the read path performs.

    INT and FLOAT are separate declarations, and honouring that is the point of
    the change. But they are the same quantity to every aggregation: both live in
    `value_num` and `state._numeric` accepts both. A rule naming FLOAT that read
    only the FLOAT row would silently drop half the evidence, which is exactly
    the under-derivation this grain exists to prevent.
    """
    _record_typed(organization, informing_structure, assertion, 40.0, ValueKind.FLOAT, 0)
    _record_typed(organization, informing_structure, assertion, 60, ValueKind.INT, 10)

    rows = evidence_models.State.objects.for_organization(organization).filter(claim_ref=MIXED_REF, key="confidence")
    assert rows.count() == 2, "Still two terms, and two rows"

    from graph_engine import projector

    combined = state_module.state_for(organization, MIXED_REF, informing_structure.kind, "confidence", projector.NUMERIC_FAMILY)

    assert combined is not None
    assert combined.n == 2, "Both measurements count"
    assert aggregate.apply(AggregationFunction.MEAN, combined) == pytest.approx(50.0)
    assert aggregate.apply(AggregationFunction.MIN, combined) == pytest.approx(40.0)
    assert aggregate.apply(AggregationFunction.MAX, combined) == pytest.approx(60.0)
    assert aggregate.apply(AggregationFunction.LATEST, combined) == 60, "Ordered by observation time across both terms"
def test_retracting_one_term_moves_the_combined_read(
    organization: Organization,
    informing_structure: evidence_models.Structure,
    assertion: evidence_models.Assertion,
) -> None:
    """Archiving an INT measurement changes what a FLOAT-family read returns.

    The interaction `combine()` introduced and nothing else covers: retraction
    still operates per term — `retract` finds its row by the metric's own value
    kind — while the read spans the family. If the two disagreed, an archived
    measurement would keep contributing to every combined read, and the
    retraction would look like it had worked when the per-term row was inspected
    directly.

    `state_for` is the entry point precisely so the stale row is rebuilt on the
    way out, and here that has to happen *before* the fold rather than after.
    """
    from graph_engine import projector

    _record_typed(organization, informing_structure, assertion, 40.0, ValueKind.FLOAT, 0)
    retracted = _record_typed(organization, informing_structure, assertion, 60, ValueKind.INT, 10)

    before = state_module.state_for(organization, MIXED_REF, informing_structure.kind, "confidence", projector.NUMERIC_FAMILY)
    assert before is not None
    assert aggregate.apply(AggregationFunction.MEAN, before) == pytest.approx(50.0)

    writer.retract(organization, retracted, assertion)
    state_module.retract(retracted, [MIXED_REF])

    after = state_module.state_for(organization, MIXED_REF, informing_structure.kind, "confidence", projector.NUMERIC_FAMILY)

    assert after is not None
    assert after.n == 1, "The archived measurement is no longer a contributor"
    assert aggregate.apply(AggregationFunction.MEAN, after) == pytest.approx(40.0)
    assert aggregate.apply(AggregationFunction.MAX, after) == pytest.approx(40.0), "MAX cannot be un-merged, so the stale row must have been rebuilt"
    assert aggregate.apply(AggregationFunction.LATEST, after) == 40.0, "…and LATEST falls back across the family"
def test_string_and_category_are_not_widened_together(
    organization: Organization,
    informing_structure: evidence_models.Structure,
    assertion: evidence_models.Assertion,
) -> None:
    """The widening is the numeric family and nothing else.

    STRING and CATEGORY share `value_txt`, so routing this through the storage
    column would have merged them — and collapsed all five vector arities with
    them. That is a separate semantic decision, and it is not being made here.
    """
    _record_typed(organization, informing_structure, assertion, "big", ValueKind.STRING, 0)
    _record_typed(organization, informing_structure, assertion, "neuron", ValueKind.CATEGORY, 10)

    strings = state_module.state_for(organization, MIXED_REF, informing_structure.kind, "confidence", [ValueKind.STRING.value])
    assert strings is not None
    assert strings.n == 1, "A CATEGORY measurement is not a STRING measurement"


RETRACTED_REF = "graph_a_evidence_org:844424930131971"


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
        target_ref=RETRACTED_REF,
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
            observed_at=BASE_TIME + timedelta(minutes=index),
        )
        state_module.merge(metric, [RETRACTED_REF])
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
    state_module.retract(metrics[1], [RETRACTED_REF])

    state = evidence_models.State.objects.for_organization(organization).get(claim_ref=RETRACTED_REF)

    assert aggregate.apply(AggregationFunction.COUNT, state) == 2
    assert aggregate.apply(AggregationFunction.SUM, state) == pytest.approx(30.0)
    assert aggregate.apply(AggregationFunction.MEAN, state) == pytest.approx(15.0)


def test_retracting_the_maximum_flags_the_row(
    organization: Organization,
    measured: tuple[evidence_models.Structure, list[evidence_models.Metric]],
) -> None:
    """MAX cannot be un-merged, so the row must admit it is stale."""
    _, metrics = measured
    state_module.retract(metrics[1], [RETRACTED_REF])

    state = evidence_models.State.objects.for_organization(organization).get(claim_ref=RETRACTED_REF)
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
        observed_at=BASE_TIME + timedelta(minutes=90),
    )
    state_module.merge(extra, [RETRACTED_REF])

    # 15.0 is neither min (10) nor max (30); but it *is* now the latest, so
    # retract a genuinely interior one instead.
    state_module.retract(metrics[2], [RETRACTED_REF])  # 20.0 at minute 2

    state = evidence_models.State.objects.for_organization(organization).get(claim_ref=RETRACTED_REF)
    assert not state.needs_recompute
    assert aggregate.apply(AggregationFunction.MAX, state) == 30.0


def test_recompute_restores_correctness_after_a_flagged_retraction(
    organization: Organization,
    measured: tuple[evidence_models.Structure, list[evidence_models.Metric]],
) -> None:
    """The rebuild produces the answer the surviving evidence supports."""
    _, metrics = measured

    writer.retract(organization, metrics[1], metrics[1].assertion)
    state_module.retract(metrics[1], [RETRACTED_REF])

    state = evidence_models.State.objects.for_organization(organization).get(claim_ref=RETRACTED_REF)
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
    state_module.retract(metrics[1], [RETRACTED_REF])

    state = state_module.state_for(organization, RETRACTED_REF, roi_category_a, "vector_length", [ValueKind.FLOAT.value])

    assert state is not None
    assert not state.needs_recompute
    assert aggregate.apply(AggregationFunction.MAX, state) == 20.0
