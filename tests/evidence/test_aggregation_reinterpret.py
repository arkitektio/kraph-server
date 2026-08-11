"""Changing a property's aggregation writes nothing.

This is the load-bearing test for M2, and the claim the whole state vector
exists to support: schema iteration stops implying a backfill.

Under the old design each derived value was materialized onto the entity at
write time, so switching `avg_length` from MEAN to MAX meant re-deriving every
entity that used it — an O(entities x evidence) migration triggered by a
one-line schema edit. Here the row holds statistics rather than an answer, and
which aggregation reads them is decided at read time. The swap is free.

If this test fails, the milestone is not done regardless of what else passes.
"""

from datetime import datetime, timedelta, timezone

import pytest
from authentikate.models import Organization

from core import models as core_models
from evidence import models as evidence_models
from evidence import state as state_module
from evidence import writer
from graph_engine import aggregate
from graph_engine.input_models import AggregationFunction

BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)
ENTITY_REF = "graph_a_evidence_org:844424930131970"
VALUES = [10.0, 30.0, 20.0]


@pytest.fixture
def measured_entity(
    organization: Organization,
    roi_category_a: core_models.StructureCategory,
    length_category: core_models.MetricCategory,
    assertion: evidence_models.Assertion,
) -> evidence_models.State:
    """Three measurements folded into one state vector."""
    structure = writer.ensure_structure(organization, roi_category_a, "roi-reinterpret", assertion)
    writer.create_link(
        organization,
        kind=evidence_models.Link.Kind.INFORMS,
        source_ref=str(structure.pk),
        target_ref=ENTITY_REF,
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
            measured_at=BASE_TIME + timedelta(minutes=index),
        )
        state_module.merge(metric, [ENTITY_REF])

    return evidence_models.State.objects.for_organization(organization).get(entity_ref=ENTITY_REF)


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
