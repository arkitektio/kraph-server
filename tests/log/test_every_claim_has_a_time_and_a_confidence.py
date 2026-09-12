"""Every claim has a time of observation and may carry a confidence (RFC 0015, RFC 0016, A2).

`observed_at` is world time on every claim table and `Standing.at` is the same
axis on a position; it defaults to the assertion's `asserted_at`, so a time
rule is total. `confidence` is the claimant's own number in [0, 1], null when
they gave none. Both are readable back through the API.
"""

from datetime import datetime, timezone
import pytest

from tests.support import claims, graphs, writes
from core import models as core_models
from evidence import models as evidence_models
from evidence import writer
from authentikate.models import Organization
from django.db import IntegrityError, transaction


@pytest.mark.django_db(transaction=True)
def test_observed_at_defaults_to_the_assertions_time(organization, assertion: evidence_models.Assertion) -> None:
    """Silence means "as of when I said so": every claim table and the standing agree."""
    term = writer.ensure_term(organization, "ENTITY", "Cell")
    instance = writer.create_instance(organization, kind=evidence_models.Instance.Kind.ENTITY, term=term, assertion=assertion)
    link = writer.create_link(organization, kind=evidence_models.Link.Kind.CLASSIFIES, source_ref=instance.ref, target_ref=str(term.pk), assertion=assertion, term=term)
    standing = writer.record_standing_for_ref(organization, target_type="node", target_id=instance.ref, stands=False, assertion=assertion)

    assert instance.observed_at == assertion.asserted_at
    assert link.observed_at == assertion.asserted_at
    assert standing.at == assertion.asserted_at


@pytest.mark.django_db(transaction=True)
def test_an_explicit_time_of_observation_is_stored(organization, assertion: evidence_models.Assertion) -> None:
    term = writer.ensure_term(organization, "NATURAL_EVENT", "Mitosis")
    event = writer.create_instance(organization, kind=evidence_models.Instance.Kind.NATURAL_EVENT, term=term, assertion=assertion, observed_at=graphs.BEFORE_TREATMENT)
    link = writer.create_link(organization, kind=evidence_models.Link.Kind.CLASSIFIES, source_ref=event.ref, target_ref=str(term.pk), assertion=assertion, term=term, observed_at=graphs.BEFORE_TREATMENT)

    event.refresh_from_db()
    link.refresh_from_db()
    assert event.observed_at == graphs.BEFORE_TREATMENT != assertion.asserted_at, "when it happened, not when it was recorded"
    assert link.observed_at == graphs.BEFORE_TREATMENT


@pytest.mark.django_db(transaction=True)
def test_a_direct_row_insert_gets_the_default_too(organization, assertion: evidence_models.Assertion) -> None:
    """The default lives on the model, not only in the writer: the column is
    NOT NULL, and a caller that bypasses `writer.create_instance` must not
    trip on it."""
    term = writer.ensure_term(organization, "ENTITY", "Cell")
    row = evidence_models.Instance.objects.create_for_organization(organization=organization, kind=evidence_models.Instance.Kind.ENTITY, term=term, assertion=assertion)
    row.refresh_from_db()
    assert row.observed_at == assertion.asserted_at


ASSERT_EVENT = """
    mutation E($input: AssertNaturalEventExistsInput!) {
        assertNaturalEventExists(input: $input) {
            instance { id observedAt assertion { assertedAt } }
        }
    }
"""
ASSERT_RELATION = """
    mutation R($input: AssertRelationExistsInput!) {
        assertRelationExists(input: $input) { link { id observedAt } }
    }
"""
ASSERT_METRIC = """
    mutation M($input: AssertMetricValueInput!) {
        assertMetricValue(input: $input) { metric { id observedAt } }
    }
"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_events_time_of_occurrence_round_trips(api_schema, simple_api_context) -> None:
    """A natural event happened at a time; that time is the claim's `observedAt`
    and is not its `assertedAt`."""
    data = await writes.execute(api_schema, simple_api_context, ASSERT_EVENT, {"input": {"term": "Mitosis", "observedAt": graphs.BEFORE_TREATMENT.isoformat()}})
    instance = data["assertNaturalEventExists"]["instance"]
    assert datetime.fromisoformat(instance["observedAt"]) == graphs.BEFORE_TREATMENT
    assert datetime.fromisoformat(instance["assertion"]["assertedAt"]) != graphs.BEFORE_TREATMENT

    silent = await writes.execute(api_schema, simple_api_context, ASSERT_EVENT, {"input": {"term": "Mitosis"}})
    silent_instance = silent["assertNaturalEventExists"]["instance"]
    assert silent_instance["observedAt"] == silent_instance["assertion"]["assertedAt"], "no time given — as of the claim"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_relation_and_a_metric_carry_observed_at(api_schema, simple_api_context) -> None:
    a = (await writes.execute(api_schema, simple_api_context, writes.ASSERT_ENTITY_OBSERVED, {"input": {"term": "Cell"}}))["assertEntityExists"]["instance"]["id"]
    b = (await writes.execute(api_schema, simple_api_context, writes.ASSERT_ENTITY_OBSERVED, {"input": {"term": "Cell"}}))["assertEntityExists"]["instance"]["id"]
    relation = await writes.execute(api_schema, simple_api_context, ASSERT_RELATION, {"input": {"term": "IS_CONNECTED_TO", "sourceId": a, "targetId": b, "observedAt": graphs.AFTER_TREATMENT.isoformat()}})
    assert datetime.fromisoformat(relation["assertRelationExists"]["link"]["observedAt"]) == graphs.AFTER_TREATMENT

    metric = await writes.execute(
        api_schema,
        simple_api_context,
        ASSERT_METRIC,
        {"input": {"identifier": "@mikro/roi", "object": "roi-observed", "key": "vector_length", "value": 12.5, "valueKind": "FLOAT", "observedAt": graphs.BEFORE_TREATMENT.isoformat()}},
    )
    assert datetime.fromisoformat(metric["assertMetricValue"]["metric"]["observedAt"]) == graphs.BEFORE_TREATMENT, "was `timestamp`, unix milliseconds"




def _rebuild_by_id(graph_id: str, table_projector) -> core_models.Graph:
    graph = core_models.Graph.objects.get(pk=graph_id)
    graphs.rebuild(graph, table_projector)
    return graph


LAST_YEAR = datetime(2025, 3, 1, 9, 0, tzinfo=timezone.utc)
TODAY = datetime(2026, 8, 11, 9, 0, tzinfo=timezone.utc)


def test_the_two_axes_are_independently_settable(organization: Organization, roi_category_a: evidence_models.StructureKind, length_category: evidence_models.MetricKind, assertion: evidence_models.Assertion) -> None:
    """A claim made today about something observed last year."""
    structure = claims.structure_row(organization, roi_category_a, assertion)
    metric = claims.metric_row(
        organization,
        structure,
        length_category,
        assertion,
        value=45.2,
        observed_at=LAST_YEAR,
        asserted_at=TODAY,
    )

    metric.refresh_from_db()
    assert metric.observed_at == LAST_YEAR
    assert metric.asserted_at == TODAY


def test_recorded_at_is_not_asserted_at(organization: Organization, roi_category_a: evidence_models.StructureKind, length_category: evidence_models.MetricKind, assertion: evidence_models.Assertion) -> None:
    """Ingest time is a third thing, and must not be mistaken for belief time.

    `recorded_at` is auto-stamped when the row is stored. Backfilling a year of
    historical claims would give every row the same `recorded_at` and wildly
    different `asserted_at`, so answering questions from `recorded_at` would be
    silently wrong.
    """
    structure = claims.structure_row(organization, roi_category_a, assertion)
    claims.metric_row(
        organization,
        structure,
        length_category,
        assertion,
        value=1.0,
        observed_at=LAST_YEAR,
        asserted_at=LAST_YEAR,
    )

    assertion.refresh_from_db()
    assert assertion.asserted_at == datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    assert assertion.recorded_at > assertion.asserted_at


@pytest.mark.django_db(transaction=True)
def test_every_claim_may_carry_a_confidence(organization, assertion: evidence_models.Assertion) -> None:
    term = writer.ensure_term(organization, "ENTITY", "Cell")
    instance = writer.create_instance(organization, kind=evidence_models.Instance.Kind.ENTITY, term=term, assertion=assertion, confidence=0.95)
    link = writer.create_link(organization, kind=evidence_models.Link.Kind.CLASSIFIES, source_ref=instance.ref, target_ref=str(term.pk), assertion=assertion, term=term, confidence=0.9)
    standing = writer.record_standing_for_ref(organization, target_type="node", target_id=instance.ref, stands=False, assertion=assertion, confidence=0.5)

    instance.refresh_from_db()
    link.refresh_from_db()
    standing.refresh_from_db()
    assert instance.confidence == 0.95
    assert link.confidence == 0.9
    assert standing.confidence == 0.5


@pytest.mark.django_db(transaction=True)
def test_silence_is_null_not_a_number(organization, assertion: evidence_models.Assertion) -> None:
    """No default: a claim without a number is one nobody scored, which is not 1.0 and not 0.0."""
    term = writer.ensure_term(organization, "ENTITY", "Cell")
    instance = writer.create_instance(organization, kind=evidence_models.Instance.Kind.ENTITY, term=term, assertion=assertion)
    link = writer.create_link(organization, kind=evidence_models.Link.Kind.CLASSIFIES, source_ref=instance.ref, target_ref=str(term.pk), assertion=assertion, term=term)
    standing = writer.record_standing_for_ref(organization, target_type="node", target_id=instance.ref, stands=True, assertion=assertion)
    assert instance.confidence is None and link.confidence is None and standing.confidence is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("bad", [-0.1, 1.5])
def test_the_database_refuses_a_confidence_outside_the_unit_interval(organization, assertion: evidence_models.Assertion, bad: float) -> None:
    """The input layer refuses it first; the constraint is for every writer that is not the API."""
    term = writer.ensure_term(organization, "ENTITY", "Cell")
    with pytest.raises(IntegrityError), transaction.atomic():
        writer.create_instance(organization, kind=evidence_models.Instance.Kind.ENTITY, term=term, assertion=assertion, confidence=bad)
    instance = writer.create_instance(organization, kind=evidence_models.Instance.Kind.ENTITY, term=term, assertion=assertion)
    with pytest.raises(IntegrityError), transaction.atomic():
        writer.create_link(organization, kind=evidence_models.Link.Kind.CLASSIFIES, source_ref=instance.ref, target_ref=str(term.pk), assertion=assertion, term=term, confidence=bad)
    with pytest.raises(IntegrityError), transaction.atomic():
        writer.record_standing_for_ref(organization, target_type="node", target_id=instance.ref, stands=False, assertion=assertion, confidence=bad)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_confidence_round_trips_on_an_instance_a_link_and_a_standing(api_schema, simple_api_context, test_graph) -> None:
    a = (await writes.execute(api_schema, simple_api_context, writes.ASSERT_ENTITY_WITH_CONFIDENCE, {"input": {"term": "Cell", "confidence": 0.95}}))["assertEntityExists"]["instance"]
    assert a["confidence"] == pytest.approx(0.95)
    b = (await writes.execute(api_schema, simple_api_context, writes.ASSERT_ENTITY_WITH_CONFIDENCE, {"input": {"term": "Cell"}}))["assertEntityExists"]["instance"]
    assert b["confidence"] is None, "no number given, none reported"

    relation = await writes.execute(api_schema, simple_api_context, writes.ASSERT_RELATION_WITH_CONFIDENCE, {"input": {"term": "IS_CONNECTED_TO", "sourceId": a["id"], "targetId": b["id"], "confidence": 0.4}})
    assert relation["assertRelationExists"]["link"]["confidence"] == pytest.approx(0.4)
    (drawn,) = relation["assertRelationExists"]["link"]["drawnIn"]
    assert drawn["edge"]["confidence"] == pytest.approx(0.4), "the Edge interface reports the link's number"

    retracted = await writes.execute(api_schema, simple_api_context, writes.RETRACT_ENTITY_SCORED, {"input": {"id": a["id"], "confidence": 0.7}})
    (standing,) = retracted["retractEntity"]["instance"]["standings"]
    assert standing["stands"] is False
    assert standing["confidence"] == pytest.approx(0.7)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [-0.1, 1.5])
async def test_the_input_refuses_a_confidence_outside_the_unit_interval(api_schema, simple_api_context, bad: float) -> None:
    result = await api_schema.execute(writes.ASSERT_ENTITY_WITH_CONFIDENCE, variable_values={"input": {"term": "Cell", "confidence": bad}}, context_value=simple_api_context)
    assert result.errors is not None and "confidence" in str(result.errors[0]).lower()
