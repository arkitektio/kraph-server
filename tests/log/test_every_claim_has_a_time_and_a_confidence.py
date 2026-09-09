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
from asgiref.sync import sync_to_async
from kante.context import HttpContext

from core import models as core_models
from evidence import models as evidence_models
from evidence import writer
from graph_engine.controller import GraphController
from tests.support import claims, drawing

TREATMENT = datetime(2026, 6, 1, tzinfo=timezone.utc)
BEFORE = TREATMENT - timedelta(days=30)
AFTER = TREATMENT + timedelta(days=30)


# --- the columns ------------------------------------------------------------


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


# --- the API ------------------------------------------------------------------

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

RETRACT_ENTITY = """
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


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_retraction_may_say_when_it_took_effect(api_schema, simple_api_context) -> None:
    """`at` on a retract input is `Standing.at` — the cell died in June, whenever
    that was recorded."""
    ref = (await _execute(api_schema, simple_api_context, ASSERT_ENTITY, {"term": "Cell"}))["assertEntityExists"]["instance"]["id"]
    data = await _execute(api_schema, simple_api_context, RETRACT_ENTITY, {"id": ref, "at": TREATMENT.isoformat()})
    (standing,) = data["retractEntity"]["instance"]["standings"]
    assert standing["stands"] is False
    assert datetime.fromisoformat(standing["at"]) == TREATMENT


# --- the rule field, on every kind ---------------------------------------------

CREATE_GRAPH = """
    mutation G($input: CreateGraphInput!) {
        createGraph(input: $input) { id }
    }
"""


def _rule(*conditions: dict) -> dict:
    return {"when": list(conditions)}


def _observed_before(moment: datetime) -> dict:
    return {"field": "OBSERVED_AT", "operator": "BEFORE", "value": moment.isoformat()}


def _observed_since(moment: datetime) -> dict:
    return {"field": "OBSERVED_AT", "operator": "SINCE", "value": moment.isoformat()}


#: Cells as they were before the treatment: a classification counts when the
#: cell was *seen* before it (world time, whenever the label was typed in), a
#: death counts only when it *took effect* before it, a connection is drawn when
#: it *held* before it — and a division event when it *happened* since it.
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


def _rebuild(graph_id: str, table_projector) -> core_models.Graph:
    graph = core_models.Graph.objects.get(pk=graph_id)
    GraphController(projector=table_projector).rebuild_projection(graph)
    return graph


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_classification_rule_bounds_when_the_world_was_seen(api_schema, simple_api_context, table_projector) -> None:
    """Both claims were *recorded* after the treatment; only the one that says
    the cell was seen before it is admitted. `ASSERTED_AT` could not tell them
    apart."""
    graph_id = await _graph(api_schema, simple_api_context, "observed-classification")

    @sync_to_async
    def build_and_read():
        graph = core_models.Graph.objects.get(pk=graph_id)
        org = graph.organization
        seen_before = claims.mint(org, "Cell", "peter", asserted_at=AFTER, observed_at=BEFORE)
        seen_after = claims.mint(org, "Cell", "peter", asserted_at=AFTER, observed_at=AFTER)
        silent = claims.mint(org, "Cell", "peter", asserted_at=AFTER)
        _rebuild(graph_id, table_projector)
        return drawing.vertices_with_ref(graph, seen_before), drawing.vertices_with_ref(graph, seen_after), drawing.vertices_with_ref(graph, silent)

    before, after, silent = await build_and_read()
    assert before == 1, "seen before the treatment — in the view"
    assert after == 0, "seen after — not a pre-treatment cell"
    assert silent == 0, "no time given means as of the claim, which was after"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_existence_rule_reads_the_standings_own_time(api_schema, simple_api_context, table_projector) -> None:
    """The same rule, read against `Standing` rows, compiles OBSERVED_AT to the
    standing's own `at`: a death that took effect before the treatment removes
    the cell from this view; one after it does not, however early it was
    recorded."""
    graph_id = await _graph(api_schema, simple_api_context, "observed-existence")

    @sync_to_async
    def build_and_read():
        graph = core_models.Graph.objects.get(pk=graph_id)
        org = graph.organization
        died_before = claims.mint(org, "Cell", "peter", observed_at=BEFORE)
        died_after = claims.mint(org, "Cell", "peter", observed_at=BEFORE)
        claims.retract_node(org, died_before, "peter", asserted_at=AFTER, at=BEFORE + timedelta(days=1))
        claims.retract_node(org, died_after, "peter", asserted_at=BEFORE, at=AFTER)
        _rebuild(graph_id, table_projector)
        return drawing.vertices_with_ref(graph, died_before), drawing.vertices_with_ref(graph, died_after)

    before, after = await build_and_read()
    assert before == 0, "a death that took effect before the treatment counts"
    assert after == 1, "one that took effect after it is outside the rule, recorded early or not"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_relation_rule_bounds_when_the_relation_held(api_schema, simple_api_context, table_projector) -> None:
    graph_id = await _graph(api_schema, simple_api_context, "observed-relation")

    @sync_to_async
    def build_and_read():
        graph = core_models.Graph.objects.get(pk=graph_id)
        org = graph.organization
        a = claims.mint(org, "Cell", "peter", observed_at=BEFORE)
        b = claims.mint(org, "Cell", "peter", observed_at=BEFORE)
        c = claims.mint(org, "Cell", "peter", observed_at=BEFORE)
        claims.relate(org, "IS_CONNECTED_TO", a, b, "karl", asserted_at=AFTER, observed_at=BEFORE)
        claims.relate(org, "IS_CONNECTED_TO", b, c, "karl", asserted_at=AFTER, observed_at=AFTER)
        _rebuild(graph_id, table_projector)
        return drawing.edges_between(graph, a, b, "IS_CONNECTED_TO"), drawing.edges_between(graph, b, c, "IS_CONNECTED_TO")

    held_before, held_after = await build_and_read()
    assert held_before == 1
    assert held_after == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_event_rule_bounds_when_the_event_happened(api_schema, simple_api_context, table_projector) -> None:
    """The event category's rule governs the event and its participations alike
    (`create_event` stamps both with the event's time): a division after the
    treatment is drawn with its edge, one before it is not."""
    graph_id = await _graph(api_schema, simple_api_context, "observed-event")

    @sync_to_async
    def build_and_read():
        graph = core_models.Graph.objects.get(pk=graph_id)
        org = graph.organization
        mother = claims.mint(org, "Cell", "peter", observed_at=BEFORE)
        late = claims.mint(org, "Mitosis", "peter", kind="NATURAL_EVENT", observed_at=AFTER)
        claims.participate(org, "Mitosis", mother, late, "peter", role="mother", observed_at=AFTER)
        early = claims.mint(org, "Mitosis", "peter", kind="NATURAL_EVENT", observed_at=BEFORE)
        claims.participate(org, "Mitosis", mother, early, "peter", role="mother", observed_at=BEFORE)
        _rebuild(graph_id, table_projector)
        return (
            drawing.vertices_with_ref(graph, late),
            drawing.edges_between(graph, mother, late),
            drawing.vertices_with_ref(graph, early),
        )

    late_drawn, late_edge, early_drawn = await build_and_read()
    assert late_drawn == 1 and late_edge == 1, "happened since the treatment — event and participation drawn"
    assert early_drawn == 0, "happened before it — outside the event category's rule"
