"""What did we believe on March 3rd?

The question the bitemporal split exists to answer, and the one a single
`timestamp` column made unanswerable. `as_of` filters on `asserted_at` — belief
time — so a graph can be evaluated as it stood when a decision was made, rather
than as it stands now.

Under per-graph silos this needed a fork of the data. Over shared evidence it is
a `WHERE` clause on an indexed column, which is what makes it cheap enough to be
routine rather than a special case.
"""

from datetime import datetime, timedelta, timezone

import pytest
from authentikate.models import Organization

from core import models as core_models
from evidence import models as evidence_models
from evidence import selector as selector_module
from evidence import writer

MARCH_1 = datetime(2026, 3, 1, tzinfo=timezone.utc)
MARCH_3 = datetime(2026, 3, 3, tzinfo=timezone.utc)
MARCH_5 = datetime(2026, 3, 5, tzinfo=timezone.utc)
OBSERVED = datetime(2025, 6, 1, tzinfo=timezone.utc)


@pytest.fixture
def revised_measurement(
    organization: Organization,
    graph_a: core_models.Graph,
    roi_category_a: evidence_models.StructureKind,
    length_category: evidence_models.MetricKind,
) -> core_models.Graph:
    """One observation, measured once and then corrected.

    Both claims describe the same moment in the world; they differ only in when
    they were made. Nothing but `asserted_at` can separate them.
    """
    original = writer.create_assertion(organization, subject="AI_Model_X", app_id="mikro", asserted_at=MARCH_1)
    correction = writer.create_assertion(organization, subject="human", app_id="review", asserted_at=MARCH_5)

    structure = writer.ensure_structure(organization, roi_category_a, "roi-as-of", original)

    for value, assertion in ((45.2, original), (47.9, correction)):
        writer.record_metric(
            organization,
            structure,
            length_category,
            key="vector_length",
            value=value,
            assertion=assertion,
            measured_at=OBSERVED,
        )

    return graph_a


def test_as_of_recovers_the_earlier_belief(organization: Organization, revised_measurement: core_models.Graph) -> None:
    """On March 3rd we believed 45.2; today we believe 47.9."""
    graph = revised_measurement

    graph.selector = {"as_of": MARCH_3.isoformat()}
    believed_then = [m.value for m in selector_module.metrics_for(graph)]

    graph.selector = {}
    believed_now = [m.value for m in selector_module.metrics_for(graph)]

    assert believed_then == [45.2], "The correction had not been made yet"
    assert sorted(believed_now) == [45.2, 47.9]


def test_as_of_is_belief_time_not_observation_time(organization: Organization, revised_measurement: core_models.Graph) -> None:
    """Both claims describe the same observation, so `measured_at` cannot separate them.

    If `as_of` filtered on observation time it would return both rows or neither,
    and the question would be unanswerable — which is exactly the state a single
    `timestamp` column left the system in.
    """
    graph = revised_measurement
    measured_ats = {m.measured_at for m in evidence_models.Metric.objects.for_organization(organization)}

    assert measured_ats == {OBSERVED}, "The two claims are about the same moment in the world"

    graph.selector = {"as_of": MARCH_3.isoformat()}
    assert len(list(selector_module.metrics_for(graph))) == 1


def test_a_projection_can_be_scoped_to_one_source(organization: Organization, revised_measurement: core_models.Graph) -> None:
    """'Only what AI_Model_X asserted' is a selector, not a fork of the data."""
    graph = revised_measurement
    graph.selector = {"assertion_filter": {"subjects": ["AI_Model_X"]}}

    assert [m.value for m in selector_module.metrics_for(graph)] == [45.2]


def test_an_observation_window_selects_by_measured_at(
    organization: Organization,
    revised_measurement: core_models.Graph,
    roi_category_a: evidence_models.StructureKind,
    length_category: evidence_models.MetricKind,
) -> None:
    """The other axis, filtered independently.

    A measurement taken this year is excluded from a projection scoped to last
    year's run, however recently it was asserted.
    """
    graph = revised_measurement
    recent = writer.create_assertion(organization, subject="AI_Model_X", app_id="mikro", asserted_at=MARCH_5)
    structure = evidence_models.Structure.objects.for_organization(organization).get(object="roi-as-of")

    writer.record_metric(
        organization,
        structure,
        length_category,
        key="vector_length",
        value=99.0,
        assertion=recent,
        measured_at=OBSERVED + timedelta(days=365),
    )

    graph.selector = {"observed_window": [OBSERVED.isoformat(), (OBSERVED + timedelta(days=1)).isoformat()]}

    assert 99.0 not in [m.value for m in selector_module.metrics_for(graph)]


def test_an_empty_selector_means_everything(organization: Organization, revised_measurement: core_models.Graph) -> None:
    """A graph that declares no scope projects all of its organization's evidence."""
    graph = revised_measurement
    graph.selector = {}

    assert len(list(selector_module.metrics_for(graph))) == 2
