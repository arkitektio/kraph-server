"""Every claim has a time of observation (RFC 0015).

`observed_at` is world time on every claim table — an instance, a link, a
metric — and `Standing.at` is the same axis on a position. It defaults to the
assertion's `asserted_at`, so the column is never null and a time rule is
total; a claimant who knows better says so. The rule field `OBSERVED_AT` names
it on every kind, where `MEASURED_AT` used to be legal on measurements alone.
"""

from datetime import datetime, timedelta, timezone
import kante
import pytest

from tests.support import graphs
from kante.context import HttpContext
from core import models as core_models
from evidence import models as evidence_models
from evidence import writer
from core.enums import ValueKind
from authentikate.models import Organization
from tests.support.writes import CREATE_GRAPH
from django.db import IntegrityError, transaction


TREATMENT = datetime(2026, 6, 1, tzinfo=timezone.utc)
BEFORE = TREATMENT - timedelta(days=30)
AFTER = TREATMENT + timedelta(days=30)


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
    event = writer.create_instance(organization, kind=evidence_models.Instance.Kind.NATURAL_EVENT, term=term, assertion=assertion, observed_at=BEFORE)
    link = writer.create_link(organization, kind=evidence_models.Link.Kind.CLASSIFIES, source_ref=event.ref, target_ref=str(term.pk), assertion=assertion, term=term, observed_at=BEFORE)

    event.refresh_from_db()
    link.refresh_from_db()
    assert event.observed_at == BEFORE != assertion.asserted_at, "when it happened, not when it was recorded"
    assert link.observed_at == BEFORE


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
ASSERT_ENTITY = """
    mutation N($input: AssertEntityExistsInput!) {
        assertEntityExists(input: $input) { instance { id observedAt } }
    }
"""
RETRACT_ENTITY_AT = """
    mutation X($input: RetractEntityInput!) {
        retractEntity(input: $input) { instance { id standings { stands at } } }
    }
"""
ASSERT_METRIC = """
    mutation M($input: AssertMetricValueInput!) {
        assertMetricValue(input: $input) { metric { id observedAt } }
    }
"""


async def _execute(api_schema: kante.Schema, ctx: HttpContext, document: str, payload: dict) -> dict:
    result = await api_schema.execute(document, variable_values={"input": payload}, context_value=ctx)
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    return result.data


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_events_time_of_occurrence_round_trips(api_schema, simple_api_context) -> None:
    """A natural event happened at a time; that time is the claim's `observedAt`
    and is not its `assertedAt`."""
    data = await _execute(api_schema, simple_api_context, ASSERT_EVENT, {"term": "Mitosis", "observedAt": BEFORE.isoformat()})
    instance = data["assertNaturalEventExists"]["instance"]
    assert datetime.fromisoformat(instance["observedAt"]) == BEFORE
    assert datetime.fromisoformat(instance["assertion"]["assertedAt"]) != BEFORE

    silent = await _execute(api_schema, simple_api_context, ASSERT_EVENT, {"term": "Mitosis"})
    silent_instance = silent["assertNaturalEventExists"]["instance"]
    assert silent_instance["observedAt"] == silent_instance["assertion"]["assertedAt"], "no time given — as of the claim"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_relation_and_a_metric_carry_observed_at(api_schema, simple_api_context) -> None:
    a = (await _execute(api_schema, simple_api_context, ASSERT_ENTITY, {"term": "Cell"}))["assertEntityExists"]["instance"]["id"]
    b = (await _execute(api_schema, simple_api_context, ASSERT_ENTITY, {"term": "Cell"}))["assertEntityExists"]["instance"]["id"]
    relation = await _execute(api_schema, simple_api_context, ASSERT_RELATION, {"term": "IS_CONNECTED_TO", "sourceId": a, "targetId": b, "observedAt": AFTER.isoformat()})
    assert datetime.fromisoformat(relation["assertRelationExists"]["link"]["observedAt"]) == AFTER

    metric = await _execute(
        api_schema,
        simple_api_context,
        ASSERT_METRIC,
        {"identifier": "@mikro/roi", "object": "roi-observed", "key": "vector_length", "value": 12.5, "valueKind": "FLOAT", "observedAt": BEFORE.isoformat()},
    )
    assert datetime.fromisoformat(metric["assertMetricValue"]["metric"]["observedAt"]) == BEFORE, "was `timestamp`, unix milliseconds"




def _rule(*conditions: dict) -> dict:
    return {"when": list(conditions)}


def _observed_before(moment: datetime) -> dict:
    return {"field": "OBSERVED_AT", "operator": "BEFORE", "value": moment.isoformat()}


def _observed_since(moment: datetime) -> dict:
    return {"field": "OBSERVED_AT", "operator": "SINCE", "value": moment.isoformat()}


DEFINITION = {
    "systemVersion": "2.0.0",
    "extensions": {
        "entities": [
            {
                "key": "Cell",
                "definition": {
                    "rules": [
                        # No KIND: the bound applies to every kind of claim about a
                        # Cell — a classification by when the cell was seen, a
                        # death by when it took effect (`Standing.at`).
                        _rule({"field": "WORD", "operator": "IS", "value": "Cell"}, _observed_before(TREATMENT)),
                    ]
                },
            }
        ],
        "relations": [
            {
                "key": "IS_CONNECTED_TO",
                "source": {"keys": ["Cell"]},
                "target": {"keys": ["Cell"]},
                "definition": {"rules": [_rule({"field": "WORD", "operator": "IS", "value": "IS_CONNECTED_TO"}, _observed_before(TREATMENT))]},
            }
        ],
        "events": [
            {
                "key": "Mitosis",
                "kind": "INTRINSIC",
                "definition": {"rules": [_rule({"field": "WORD", "operator": "IS", "value": "Mitosis"}, _observed_since(TREATMENT))]},
                "inputs": [{"key": "Cell", "role": "mother", "descriptor": {"keys": ["Cell"]}}],
                "outputs": [{"key": "Cell", "role": "daughter", "descriptor": {"keys": ["Cell"]}}],
            }
        ],
    },
}


async def _graph(api_schema: kante.Schema, ctx: HttpContext, name: str) -> str:
    made = await api_schema.execute(CREATE_GRAPH, variable_values={"input": {"name": name, "definition": DEFINITION}}, context_value=ctx)
    assert made.errors is None, f"GraphQL errors: {made.errors}"
    return made.data["createGraph"]["id"]


def _rebuild_by_id(graph_id: str, table_projector) -> core_models.Graph:
    graph = core_models.Graph.objects.get(pk=graph_id)
    graphs.rebuild(graph, table_projector)
    return graph


LAST_YEAR = datetime(2025, 3, 1, 9, 0, tzinfo=timezone.utc)
TODAY = datetime(2026, 8, 11, 9, 0, tzinfo=timezone.utc)


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


def test_the_two_axes_are_independently_settable(organization: Organization, roi_category_a: evidence_models.StructureKind, length_category: evidence_models.MetricKind, assertion: evidence_models.Assertion) -> None:
    """A claim made today about something observed last year."""
    structure = _structure(organization, roi_category_a, assertion)
    metric = _metric(
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
    structure = _structure(organization, roi_category_a, assertion)
    _metric(
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


ASSERT_ENTITY_WITH_CONFIDENCE = """
    mutation N($input: AssertEntityExistsInput!) {
        assertEntityExists(input: $input) { instance { id confidence } }
    }
"""


ASSERT_RELATION_WITH_CONFIDENCE = """
    mutation R($input: AssertRelationExistsInput!) {
        assertRelationExists(input: $input) { link { id confidence drawnIn { edge { confidence } } } }
    }
"""


RETRACT_ENTITY = """
    mutation X($input: RetractEntityInput!) {
        retractEntity(input: $input) { instance { id standings { stands confidence } } }
    }
"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_confidence_round_trips_on_an_instance_a_link_and_a_standing(api_schema, simple_api_context, test_graph) -> None:
    a = (await _execute(api_schema, simple_api_context, ASSERT_ENTITY_WITH_CONFIDENCE, {"term": "Cell", "confidence": 0.95}))["assertEntityExists"]["instance"]
    assert a["confidence"] == pytest.approx(0.95)
    b = (await _execute(api_schema, simple_api_context, ASSERT_ENTITY_WITH_CONFIDENCE, {"term": "Cell"}))["assertEntityExists"]["instance"]
    assert b["confidence"] is None, "no number given, none reported"

    relation = await _execute(api_schema, simple_api_context, ASSERT_RELATION_WITH_CONFIDENCE, {"term": "IS_CONNECTED_TO", "sourceId": a["id"], "targetId": b["id"], "confidence": 0.4})
    assert relation["assertRelationExists"]["link"]["confidence"] == pytest.approx(0.4)
    (drawn,) = relation["assertRelationExists"]["link"]["drawnIn"]
    assert drawn["edge"]["confidence"] == pytest.approx(0.4), "the Edge interface reports the link's number"

    retracted = await _execute(api_schema, simple_api_context, RETRACT_ENTITY, {"id": a["id"], "confidence": 0.7})
    (standing,) = retracted["retractEntity"]["instance"]["standings"]
    assert standing["stands"] is False
    assert standing["confidence"] == pytest.approx(0.7)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [-0.1, 1.5])
async def test_the_input_refuses_a_confidence_outside_the_unit_interval(api_schema, simple_api_context, bad: float) -> None:
    result = await api_schema.execute(ASSERT_ENTITY_WITH_CONFIDENCE, variable_values={"input": {"term": "Cell", "confidence": bad}}, context_value=simple_api_context)
    assert result.errors is not None and "confidence" in str(result.errors[0]).lower()
