"""One key, two types, two sets of statistics.

The regression test for the behaviour change. `MetricKind` identity now includes
`value_kind`, so `confidence` recorded as a float and `confidence` recorded as a
category label are two terms rather than one rejected write.

That is only coherent because `State`'s grain includes `value_kind` too. Without
it both terms fold into one row, and `state._numeric` returns None for a string —
so the string bumps `n` but contributes nothing to `sum`, and `MEAN` becomes a
numeric total divided by a count that includes non-numbers. Over 40, 60 and
"big" that reads 33.3.

What made it worth a dedicated file is that `recompute` filtered the same way, so
it reproduced the error exactly. The incremental fold and its own correctness
backstop agreed, and `test_state_vector`'s property test — the one written to
catch fold errors — certified the wrong answer. Nothing in the suite could see
this, so the assertion below is on the *value*, not on two computations matching.
"""

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
        target_ref=ENTITY_REF,
        assertion=assertion,
    )
    return structure


def _record(
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
        measured_at=BASE_TIME + timedelta(minutes=offset_minutes),
    )
    state_module.merge(metric, [ENTITY_REF])
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
    _record(organization, informing_structure, assertion, 40.0, ValueKind.FLOAT, 0)
    _record(organization, informing_structure, assertion, 60.0, ValueKind.FLOAT, 10)
    _record(organization, informing_structure, assertion, "big", ValueKind.STRING, 20)

    numeric = state_module.state_for(organization, ENTITY_REF, informing_structure.kind, "confidence", [ValueKind.FLOAT.value])

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
    _record(organization, informing_structure, assertion, 40.0, ValueKind.FLOAT, 0)
    _record(organization, informing_structure, assertion, "big", ValueKind.STRING, 20)
    _record(organization, informing_structure, assertion, "small", ValueKind.STRING, 30)

    rows = evidence_models.State.objects.for_organization(organization).filter(entity_ref=ENTITY_REF, key="confidence")
    assert rows.count() == 2, "One row per value kind"

    labels = state_module.state_for(organization, ENTITY_REF, informing_structure.kind, "confidence", [ValueKind.STRING.value])
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
    _record(organization, informing_structure, assertion, 40.0, ValueKind.FLOAT, 0)
    _record(organization, informing_structure, assertion, 60.0, ValueKind.FLOAT, 10)
    _record(organization, informing_structure, assertion, "big", ValueKind.STRING, 20)

    for row in evidence_models.State.objects.for_organization(organization).filter(entity_ref=ENTITY_REF, key="confidence"):
        before = row.n
        rebuilt = state_module.recompute(row)
        assert rebuilt.n == before, f"{row.value_kind} row changed on rebuild"

    numeric = evidence_models.State.objects.for_organization(organization).get(entity_ref=ENTITY_REF, key="confidence", value_kind=ValueKind.FLOAT.value)
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
    _record(organization, informing_structure, assertion, 40.0, ValueKind.FLOAT, 0)
    _record(organization, informing_structure, assertion, 60, ValueKind.INT, 10)

    rows = evidence_models.State.objects.for_organization(organization).filter(entity_ref=ENTITY_REF, key="confidence")
    assert rows.count() == 2, "Still two terms, and two rows"

    from graph_engine import projector

    combined = state_module.state_for(organization, ENTITY_REF, informing_structure.kind, "confidence", projector.NUMERIC_FAMILY)

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

    _record(organization, informing_structure, assertion, 40.0, ValueKind.FLOAT, 0)
    retracted = _record(organization, informing_structure, assertion, 60, ValueKind.INT, 10)

    before = state_module.state_for(organization, ENTITY_REF, informing_structure.kind, "confidence", projector.NUMERIC_FAMILY)
    assert before is not None
    assert aggregate.apply(AggregationFunction.MEAN, before) == pytest.approx(50.0)

    writer.archive(organization, retracted, assertion)
    state_module.retract(retracted, [ENTITY_REF])

    after = state_module.state_for(organization, ENTITY_REF, informing_structure.kind, "confidence", projector.NUMERIC_FAMILY)

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
    _record(organization, informing_structure, assertion, "big", ValueKind.STRING, 0)
    _record(organization, informing_structure, assertion, "neuron", ValueKind.CATEGORY, 10)

    strings = state_module.state_for(organization, ENTITY_REF, informing_structure.kind, "confidence", [ValueKind.STRING.value])
    assert strings is not None
    assert strings.n == 1, "A CATEGORY measurement is not a STRING measurement"
