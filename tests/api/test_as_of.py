"""What did we believe on March 3rd?

The question the bitemporal split exists to answer, and the one a single
`timestamp` column made unanswerable. `as_of` filters on `asserted_at` — belief
time — so a rule can be evaluated as it stood when a decision was made, rather
than as it stands now.

Since RFC 0009 the scope carrying these bounds is per rule, not per graph:
a category's clauses (`trust_filter`) or a property's `rule.evidence`
(`rule_metric_filter`), composed by `metric_scope`. Under per-graph silos this
needed a fork of the data; over shared evidence it is a `WHERE` clause on an
indexed column, which is what makes it cheap enough to be routine.
"""

from datetime import datetime, timedelta, timezone

import pytest
from authentikate.models import Organization

from core import models as core_models
from evidence import models as evidence_models
from evidence import selector as selector_module
from evidence import writer
from graph_engine import input_models
from tests import rules

MARCH_1 = datetime(2026, 3, 1, tzinfo=timezone.utc)
MARCH_3 = datetime(2026, 3, 3, tzinfo=timezone.utc)
MARCH_5 = datetime(2026, 3, 5, tzinfo=timezone.utc)
OBSERVED = datetime(2025, 6, 1, tzinfo=timezone.utc)


def _metrics(organization: Organization, rule: input_models.DerivationRuleInput | None = None, definition: dict | None = None):
    """The metrics one property would fold, under `metric_scope`."""
    claim_q, _ = selector_module.metric_scope(definition, rule)
    return evidence_models.Metric.objects.for_organization(organization).filter(claim_q)


def _rule(*conditions: dict) -> input_models.DerivationRuleInput:
    return input_models.DerivationRuleInput(source_node="ROI", key="vector_length", evidence=[input_models.ClaimConditionInput.model_validate(c) for c in conditions])


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
    believed_then = [m.value for m in _metrics(organization, _rule(rules.before(MARCH_3)))]
    believed_now = [m.value for m in _metrics(organization)]

    assert believed_then == [45.2], "The correction had not been made yet"
    assert sorted(believed_now) == [45.2, 47.9]


def test_as_of_is_belief_time_not_observation_time(organization: Organization, revised_measurement: core_models.Graph) -> None:
    """Both claims describe the same observation, so `measured_at` cannot separate them.

    If `as_of` filtered on observation time it would return both rows or neither,
    and the question would be unanswerable — which is exactly the state a single
    `timestamp` column left the system in.
    """
    measured_ats = {m.measured_at for m in evidence_models.Metric.objects.for_organization(organization)}
    assert measured_ats == {OBSERVED}, "The two claims are about the same moment in the world"

    assert _metrics(organization, _rule(rules.before(MARCH_3))).count() == 1


def test_a_property_can_be_scoped_to_one_source(organization: Organization, revised_measurement: core_models.Graph) -> None:
    """'Only what AI_Model_X asserted' is a rule filter, not a fork of the data."""
    rule = _rule(rules.by("AI_Model_X"))
    assert [m.value for m in _metrics(organization, rule)] == [45.2]


def test_a_categorys_clauses_are_the_default_metric_scope(organization: Organization, revised_measurement: core_models.Graph) -> None:
    """No `rule.evidence` → the owning category's clauses bound the fold."""
    definition = rules.definition(rules.rule(rules.word("Whatever"), rules.by("AI_Model_X")))
    assert [m.value for m in _metrics(organization, None, definition)] == [45.2]


def test_an_observation_window_selects_by_measured_at(
    organization: Organization,
    revised_measurement: core_models.Graph,
    roi_category_a: evidence_models.StructureKind,
    length_category: evidence_models.MetricKind,
) -> None:
    """The other axis, filtered independently.

    A measurement taken this year is excluded from a rule scoped to last
    year's run, however recently it was asserted.
    """
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

    rule = _rule(rules.measured_since(OBSERVED), rules.measured_before(OBSERVED + timedelta(days=1)))
    assert 99.0 not in [m.value for m in _metrics(organization, rule)]


def test_no_rule_means_everything(organization: Organization, revised_measurement: core_models.Graph) -> None:
    """A property with no evidence filter on a primitive category folds all of
    its organization's evidence."""
    assert _metrics(organization).count() == 2


def test_since_recovers_the_later_belief(organization: Organization, revised_measurement: core_models.Graph) -> None:
    """The lower bound `as_of` never had: "only what we have believed since March 3"."""
    assert [m.value for m in _metrics(organization, _rule(rules.since(MARCH_3)))] == [47.9], "the original March 1 claim is before the bound"
