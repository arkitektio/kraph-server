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
from tests.support import rules
from core.enums import ValueKind


MARCH_1 = datetime(2026, 3, 1, tzinfo=timezone.utc)
MARCH_3 = datetime(2026, 3, 3, tzinfo=timezone.utc)
MARCH_5 = datetime(2026, 3, 5, tzinfo=timezone.utc)
OBSERVED = datetime(2025, 6, 1, tzinfo=timezone.utc)


def _metrics(organization: Organization, rule: input_models.DerivationRuleInput | None = None, definition: dict | None = None):
    """The metrics one property would fold, under `metric_scope`."""
    claim_q, _ = selector_module.metric_scope(definition, rule)
    return evidence_models.Metric.objects.for_organization(organization).filter(claim_q)


def _rule(*conditions: dict) -> input_models.DerivationRuleInput:
    return input_models.DerivationRuleInput(source_node="ROI", key="vector_length", evidence=rules.evidence(rules.rule(*conditions)))


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
            observed_at=OBSERVED,
        )

    return graph_a


def test_as_of_recovers_the_earlier_belief(organization: Organization, revised_measurement: core_models.Graph) -> None:
    """On March 3rd we believed 45.2; today we believe 47.9."""
    believed_then = [m.value for m in _metrics(organization, _rule(rules.before(MARCH_3)))]
    believed_now = [m.value for m in _metrics(organization)]

    assert believed_then == [45.2], "The correction had not been made yet"
    assert sorted(believed_now) == [45.2, 47.9]


def test_as_of_is_belief_time_not_observation_time(organization: Organization, revised_measurement: core_models.Graph) -> None:
    """Both claims describe the same observation, so `observed_at` cannot separate them.

    If `as_of` filtered on observation time it would return both rows or neither,
    and the question would be unanswerable — which is exactly the state a single
    `timestamp` column left the system in.
    """
    observed_ats = {m.observed_at for m in evidence_models.Metric.objects.for_organization(organization)}
    assert observed_ats == {OBSERVED}, "The two claims are about the same moment in the world"

    assert _metrics(organization, _rule(rules.before(MARCH_3))).count() == 1


def test_a_property_can_be_scoped_to_one_source(organization: Organization, revised_measurement: core_models.Graph) -> None:
    """'Only what AI_Model_X asserted' is a rule filter, not a fork of the data."""
    rule = _rule(rules.by("AI_Model_X"))
    assert [m.value for m in _metrics(organization, rule)] == [45.2]


def test_a_categorys_clauses_are_the_default_metric_scope(organization: Organization, revised_measurement: core_models.Graph) -> None:
    """No `rule.evidence` → the owning category's clauses bound the fold."""
    definition = rules.definition(rules.rule(rules.word("Whatever"), rules.by("AI_Model_X")))
    assert [m.value for m in _metrics(organization, None, definition)] == [45.2]


def test_an_observation_window_selects_by_observed_at(
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
        observed_at=OBSERVED + timedelta(days=365),
    )

    rule = _rule(rules.observed_since(OBSERVED), rules.observed_before(OBSERVED + timedelta(days=1)))
    assert 99.0 not in [m.value for m in _metrics(organization, rule)]


def test_no_rule_means_everything(organization: Organization, revised_measurement: core_models.Graph) -> None:
    """A property with no evidence filter on a primitive category folds all of
    its organization's evidence."""
    assert _metrics(organization).count() == 2


def test_since_recovers_the_later_belief(organization: Organization, revised_measurement: core_models.Graph) -> None:
    """The lower bound `as_of` never had: "only what we have believed since March 3"."""
    assert [m.value for m in _metrics(organization, _rule(rules.since(MARCH_3)))] == [47.9], "the original March 1 claim is before the bound"


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
    observed_at: datetime,
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
        observed_at=observed_at,
        asserted_at=asserted_at,
        assertion=assertion,
    )


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
        observed_at=LAST_YEAR,
        asserted_at=YESTERDAY,
    )
    _metric(
        organization,
        structure,
        length_category,
        assertion,
        value=47.9,
        observed_at=LAST_YEAR,
        asserted_at=TODAY,
    )

    believed_yesterday = evidence_models.Metric.objects.for_organization(organization).filter(asserted_at__lte=YESTERDAY).order_by("-asserted_at")
    believed_now = evidence_models.Metric.objects.for_organization(organization).order_by("-asserted_at")

    assert believed_yesterday.count() == 1
    assert believed_yesterday.first().value == 45.2
    assert believed_now.first().value == 47.9


def test_observation_window_selects_by_observed_at(organization: Organization, roi_category_a: evidence_models.StructureKind, length_category: evidence_models.MetricKind, assertion: evidence_models.Assertion) -> None:
    """The other axis: 'measurements taken during last year's run'.

    Both rows below were asserted at the same instant, so only `observed_at`
    can separate them.
    """
    structure = _structure(organization, roi_category_a, assertion)

    _metric(
        organization,
        structure,
        length_category,
        assertion,
        value=1.0,
        observed_at=LAST_YEAR,
        asserted_at=TODAY,
    )
    _metric(
        organization,
        structure,
        length_category,
        assertion,
        value=2.0,
        observed_at=TODAY,
        asserted_at=TODAY,
    )

    observed_last_year = evidence_models.Metric.objects.for_organization(organization).filter(observed_at__lt=datetime(2026, 1, 1, tzinfo=timezone.utc))

    assert [m.value for m in observed_last_year] == [1.0]
