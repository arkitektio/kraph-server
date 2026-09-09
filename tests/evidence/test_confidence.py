"""Confidence is a property of any claim (RFC 0016).

A `Metric` had `confidence`; nothing else did, so "the model is 95% sure this
is an AIS" had nowhere to go and no rule could read it. Now `Instance`, `Link`
and `Standing` carry the same nullable float in [0, 1], and `CONFIDENCE` is a
rule field with two operators: `AT_LEAST` (>=) and `BELOW` (<). Null means the
claimant gave no number — and a rule that asks for a number does not admit
silence.
"""

import kante
import pytest
from django.db import IntegrityError, transaction
from kante.context import HttpContext

from core import models as core_models
from evidence import models as evidence_models
from evidence import writer
from graph_engine import input_models as models
from graph_engine.controller import GraphController
from graph_engine.materialize import materialize
from tests.support import claims, drawing
from tests.support import rules as R

# --- the columns ------------------------------------------------------------


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


# --- the API ------------------------------------------------------------------

ASSERT_ENTITY = """
    mutation N($input: AssertEntityExistsInput!) {
        assertEntityExists(input: $input) { instance { id confidence } }
    }
"""

ASSERT_RELATION = """
    mutation R($input: AssertRelationExistsInput!) {
        assertRelationExists(input: $input) { link { id confidence drawnIn { edge { confidence } } } }
    }
"""

RETRACT_ENTITY = """
    mutation X($input: RetractEntityInput!) {
        retractEntity(input: $input) { instance { id standings { stands confidence } } }
    }
"""


async def _execute(api_schema: kante.Schema, ctx: HttpContext, document: str, payload: dict) -> dict:
    result = await api_schema.execute(document, variable_values={"input": payload}, context_value=ctx)
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    return result.data


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_confidence_round_trips_on_an_instance_a_link_and_a_standing(api_schema, simple_api_context, test_graph) -> None:
    a = (await _execute(api_schema, simple_api_context, ASSERT_ENTITY, {"term": "Cell", "confidence": 0.95}))["assertEntityExists"]["instance"]
    assert a["confidence"] == pytest.approx(0.95)
    b = (await _execute(api_schema, simple_api_context, ASSERT_ENTITY, {"term": "Cell"}))["assertEntityExists"]["instance"]
    assert b["confidence"] is None, "no number given, none reported"

    relation = await _execute(api_schema, simple_api_context, ASSERT_RELATION, {"term": "IS_CONNECTED_TO", "sourceId": a["id"], "targetId": b["id"], "confidence": 0.4})
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
    result = await api_schema.execute(ASSERT_ENTITY, variable_values={"input": {"term": "Cell", "confidence": bad}}, context_value=simple_api_context)
    assert result.errors is not None and "confidence" in str(result.errors[0]).lower()


# --- the rule field ----------------------------------------------------------------


def test_confidence_takes_the_numeric_operators_only() -> None:
    models.CategoryDefinitionInput.model_validate(R.definition(R.rule(R.word("X"), R.at_least(0.9))))
    models.CategoryDefinitionInput.model_validate(R.definition(R.rule(R.word("X"), unless=[[R.below(0.3)]])))
    models.MetricEvidenceInput.model_validate(R.evidence(R.rule(R.at_least(0.5))))
    with pytest.raises(Exception, match="CONFIDENCE"):  # identity operator on a number
        models.CategoryDefinitionInput.model_validate(R.definition(R.rule(R.word("X"), R.condition("CONFIDENCE", "IS", "0.9"))))
    with pytest.raises(Exception, match="CONFIDENCE"):  # time operator on a number
        models.CategoryDefinitionInput.model_validate(R.definition(R.rule(R.word("X"), R.condition("CONFIDENCE", "BEFORE", 0.9))))
    with pytest.raises(Exception, match="SUBJECT"):  # numeric operator on an identity field
        models.CategoryDefinitionInput.model_validate(R.definition(R.rule(R.word("X"), R.condition("SUBJECT", "AT_LEAST", 0.9))))
    with pytest.raises(Exception, match="ASSERTED_AT"):  # numeric operator on a time field
        models.CategoryDefinitionInput.model_validate(R.definition(R.rule(R.word("X"), R.condition("ASSERTED_AT", "AT_LEAST", 0.9))))


@pytest.mark.parametrize("bad", [-0.1, 1.5, "0.9", None])
def test_a_confidence_bound_is_a_number_in_the_unit_interval(bad) -> None:
    with pytest.raises(Exception, match="CONFIDENCE"):
        models.CategoryDefinitionInput.model_validate(R.definition(R.rule(R.word("X"), R.condition("CONFIDENCE", "AT_LEAST", bad))))


def test_a_confidence_condition_compiles_to_a_bound_on_the_claims_own_column() -> None:
    from evidence import selector

    admitted = selector.trust_filter(R.definition(R.rule(R.word("X"), R.at_least(0.9))), kind="CLASSIFICATION")
    assert "confidence__gte" in str(admitted) and "0.9" in str(admitted)
    blocked = selector.trust_filter(R.definition(R.rule(R.word("X"), unless=[[R.below(0.3)]])), kind="EXISTENCE")
    assert "confidence__lt" in str(blocked)
    evidence = selector.rule_metric_filter(models.DerivationRuleInput(source_node="ROI", key="k", aggregation=models.AggregationFunction.MEAN, evidence=R.evidence(R.rule(R.at_least(0.5)))))
    assert "confidence__gte" in str(evidence)


# --- the rule field, folded -------------------------------------------------------


def _entity_graph(table_projector, authenticated_context, name: str, definition: dict, *, evidence: dict | None = None) -> core_models.Graph:
    request = authenticated_context.request
    graph_definition = models.GraphDefinitionInput(
        system_version="1.0.0",
        extensions=models.GraphExtensionsInput(
            entities=[
                models.EntityDefinitionInput(
                    key="Cell",
                    definition=models.CategoryDefinitionInput.model_validate(definition),
                    property_definitions=[
                        models.PropertyDefinitionInput(
                            key="avg_length",
                            type=models.PropertyType.FLOAT,
                            derivation=models.DerivationType.ROLLUP,
                            rule=models.DerivationRuleInput(source_node="ROI", key="vector_length", aggregation=models.AggregationFunction.MEAN, evidence=evidence),
                        )
                    ],
                )
            ]
        ),
    )
    return materialize(graph_definition, table_projector, user=request._user, organization=request._organization, membership=request.membership, name=name)


def _rebuild(graph: core_models.Graph, table_projector) -> None:
    GraphController(projector=table_projector).rebuild_projection(graph)


@pytest.mark.django_db(transaction=True)
def test_a_classification_rule_may_demand_a_confidence(transactional_db, table_projector, authenticated_context) -> None:
    """`AT_LEAST 0.9` admits the 0.95 classification, excludes the 0.5 one, and
    excludes the one nobody scored: silence is not confidence."""
    graph = _entity_graph(table_projector, authenticated_context, "confidence-classification", R.definition(R.rule(R.word("Cell"), R.at_least(0.9))))
    org = graph.organization
    sure = claims.mint(org, "Cell", "model", confidence=0.95)
    unsure = claims.mint(org, "Cell", "model", confidence=0.5)
    silent = claims.mint(org, "Cell", "model")
    _rebuild(graph, table_projector)
    assert drawing.vertices_with_ref(graph, sure) == 1
    assert drawing.vertices_with_ref(graph, unsure) == 0
    assert drawing.vertices_with_ref(graph, silent) == 0, "a rule that asks for a number does not admit a claim without one"


@pytest.mark.django_db(transaction=True)
def test_an_unless_group_may_subtract_the_unconfident(transactional_db, table_projector, authenticated_context) -> None:
    """The other idiom: everything counts unless the claimant scored it below
    0.3. A claim with no number is not below anything, so it stays."""
    graph = _entity_graph(table_projector, authenticated_context, "confidence-unless", R.definition(R.rule(R.word("Cell"), unless=[[R.below(0.3)]])))
    org = graph.organization
    low = claims.mint(org, "Cell", "model", confidence=0.1)
    mid = claims.mint(org, "Cell", "model", confidence=0.5)
    silent = claims.mint(org, "Cell", "model")
    _rebuild(graph, table_projector)
    assert drawing.vertices_with_ref(graph, low) == 0
    assert drawing.vertices_with_ref(graph, mid) == 1
    assert drawing.vertices_with_ref(graph, silent) == 1


@pytest.mark.django_db(transaction=True)
def test_an_existence_rule_reads_the_standings_confidence(transactional_db, table_projector, authenticated_context) -> None:
    """The same bound over `Standing` rows: a confident retraction removes the
    node, a hesitant one is outside the rule and counts for nothing."""
    graph = _entity_graph(
        table_projector,
        authenticated_context,
        "confidence-existence",
        R.definition(R.rule(R.word("Cell"), R.not_kind("EXISTENCE")), R.rule(R.of_kind("EXISTENCE"), R.at_least(0.9))),
    )
    org = graph.organization
    surely_dead = claims.mint(org, "Cell", "model")
    maybe_dead = claims.mint(org, "Cell", "model")
    claims.retract_node(org, surely_dead, "model", confidence=0.99)
    claims.retract_node(org, maybe_dead, "model", confidence=0.2)
    _rebuild(graph, table_projector)
    assert drawing.vertices_with_ref(graph, surely_dead) == 0
    assert drawing.vertices_with_ref(graph, maybe_dead) == 1


@pytest.mark.django_db(transaction=True)
def test_a_property_may_fold_only_confident_measurements(transactional_db, table_projector, authenticated_context) -> None:
    graph = _entity_graph(
        table_projector,
        authenticated_context,
        "confidence-evidence",
        R.definition(R.rule(R.word("Cell"))),
        evidence=R.evidence(R.rule(R.at_least(0.8))),
    )
    org = graph.organization
    ref = claims.mint(org, "Cell", "peter")
    claims.measure(org, ref, obj="r1", key="vector_length", value=10.0, subject="pipeline", confidence=0.9)
    claims.measure(org, ref, obj="r2", key="vector_length", value=30.0, subject="pipeline", confidence=0.85)
    claims.measure(org, ref, obj="r3", key="vector_length", value=500.0, subject="pipeline", confidence=0.4)
    claims.measure(org, ref, obj="r4", key="vector_length", value=900.0, subject="pipeline")
    _rebuild(graph, table_projector)
    assert drawing.vertex_properties(graph, ref).get("avg_length") == pytest.approx(20.0), "only the measurements scored at least 0.8"


@pytest.mark.django_db(transaction=True)
def test_a_relation_rule_may_demand_a_confidence(transactional_db, table_projector, authenticated_context) -> None:
    request = authenticated_context.request
    definition = models.GraphDefinitionInput(
        system_version="1.0.0",
        extensions=models.GraphExtensionsInput(
            entities=[models.EntityDefinitionInput(key="Cell")],
            relations=[
                models.RelationDefinitionInput(
                    key="IS_CONNECTED_TO",
                    source=models.EntityDescriptorInput(keys=["Cell"]),
                    target=models.EntityDescriptorInput(keys=["Cell"]),
                    definition=models.CategoryDefinitionInput.model_validate(R.definition(R.rule(R.word("IS_CONNECTED_TO"), R.at_least(0.9)))),
                )
            ],
        ),
    )
    graph = materialize(definition, table_projector, user=request._user, organization=request._organization, membership=request.membership, name="confidence-relation")
    org = graph.organization
    a = claims.mint(org, "Cell", "peter")
    b = claims.mint(org, "Cell", "peter")
    c = claims.mint(org, "Cell", "peter")
    claims.relate(org, "IS_CONNECTED_TO", a, b, "tracer", confidence=0.95)
    claims.relate(org, "IS_CONNECTED_TO", b, c, "tracer", confidence=0.6)
    _rebuild(graph, table_projector)
    assert drawing.edges_between(graph, a, b, "IS_CONNECTED_TO") == 1
    assert drawing.edges_between(graph, b, c, "IS_CONNECTED_TO") == 0
