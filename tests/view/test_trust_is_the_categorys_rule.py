"""Trust is the category's rule (RFC 0009): the discussed example, end to end.

There is no `Graph.selector` any more. A category's `definition` — the union of
clauses RFC 0007 built — is the complete rule for its word in a view:

- which CLASSIFIES claims admit a node (as before),
- whose EXISTENCE standings count for its nodes,
- for a relation or event category, whose LINK claims draw its edges,
- and, by default, whose measurements its properties fold — overridden per
  property by `rule.evidence`, which is the property's own metric rule.

Sameness stays organization grain: a view cannot veto a merge claim.

This file is the acceptance test for the design discussion: the definition
below is the example agreed there, verbatim in spirit.
"""

import pytest
from asgiref.sync import sync_to_async
from core import models as core_models
from tests.support import claims, drawing, graphs
from tests.support.graphs import example_graph as _example_graph, rebuild as _rebuild
from tests.support.writes import CREATE_GRAPH
import kante
from kante.context import HttpContext
from tests.support import rules
from tests.support import writes
from tests.support.graphs import graph_declaring as _graph_declaring
from graph_engine import input_models as models
from graph_engine.materialize import materialize
from tests.support import rules as R
from datetime import datetime, timedelta, timezone


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_metrics_fold_under_rule_evidence(api_schema, simple_api_context, table_projector) -> None:
    """`rule.evidence` is the property's own metric rule; INFORMS routing stays
    the category's (who may attach evidence to this node)."""
    graph_id = await _example_graph(api_schema, simple_api_context, "trust-metrics")

    @sync_to_async
    def build_and_read():
        graph = core_models.Graph.objects.get(pk=graph_id)
        org = graph.organization
        ais = claims.mint(org, "AIS", "peter", asserted_at=BEFORE)
        # Routing (INFORMS) by Peter inside his clause; the numbers by the
        # pipeline app the rule names — and one by a rival app, excluded.
        claims.measure(org, ais, obj="roi-1", key="vector_length", value=10.0, subject="pipeline", app_id="segmenter-v3", inform_subject="peter", inform_asserted_at=BEFORE)
        claims.measure(org, ais, obj="roi-2", key="vector_length", value=30.0, subject="pipeline", app_id="segmenter-v3", inform_subject="peter", inform_asserted_at=BEFORE)
        claims.measure(org, ais, obj="roi-3", key="vector_length", value=1000.0, subject="pipeline", app_id="rival-tool", inform_subject="peter", inform_asserted_at=BEFORE)
        _rebuild(graph_id, table_projector)
        return drawing.vertex_properties(graph, ais)

    properties = await build_and_read()
    assert properties.get("avg_length") == pytest.approx(20.0), f"only the named app's numbers fold: {properties}"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_informs_routing_folds_under_the_categorys_clauses(api_schema, simple_api_context, table_projector) -> None:
    """Evidence routed to a node by somebody its category does not trust is not counted."""
    graph_id = await _example_graph(api_schema, simple_api_context, "trust-informs")

    @sync_to_async
    def build_and_read():
        graph = core_models.Graph.objects.get(pk=graph_id)
        org = graph.organization
        ais = claims.mint(org, "AIS", "peter", asserted_at=BEFORE)
        # The numbers come from the trusted app either way; only the INFORMS
        # claim's author differs.
        claims.measure(org, ais, obj="roi-good", key="vector_length", value=20.0, subject="pipeline", app_id="segmenter-v3", inform_subject="peter", inform_asserted_at=BEFORE)
        claims.measure(org, ais, obj="roi-smuggled", key="vector_length", value=9000.0, subject="pipeline", app_id="segmenter-v3", inform_subject="stranger", inform_asserted_at=BEFORE)
        _rebuild(graph_id, table_projector)
        return drawing.vertex_properties(graph, ais)

    properties = await build_and_read()
    assert properties.get("avg_length") == pytest.approx(20.0), f"a stranger cannot route evidence under a trusted node: {properties}"


SAMENESS_DEFINITION = {
    "systemVersion": "1.0.0",
    "extensions": {
        "entities": [
            {
                "key": "Axon",
                "definition": {
                    "rules": [
                        # Peter and Karl decide what exists and what classifies.
                        {
                            "when": [
                                {"field": "WORD", "operator": "IN", "value": ["AIS", "AxonInitialSegment"]},
                                {"field": "SUBJECT", "operator": "IN", "value": ["peter", "karl"]},
                            ]
                        },
                    ]
                },
            },
            {"key": "Cell"},
        ],
    },
}
CURATOR_MERGES = {"rules": [{"when": [{"field": "SUBJECT", "operator": "IS", "value": "curator"}]}]}
EXPLAIN = """
    query Explain($id: ID!, $graph: ID!) {
        node(id: $id, graph: $graph) {
            ... on Entity {
                richProperties {
                    key
                    value
                    nEvidence
                    supportingEvidence { id value }
                    contributingAssertions { id appId }
                }
            }
        }
    }
"""
INPUT_PARTICIPATIONS = """
    query P($graph: ID!) {
        inputParticipations(graph: $graph) { id }
    }
"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_supporting_evidence_agrees_with_the_fold(api_schema: kante.Schema, simple_api_context: HttpContext, table_projector) -> None:
    definition = {
        "extensions": {
            "entities": [
                {
                    "key": "Probe",
                    "propertyDefinitions": [{"key": "avg_length", "valueKind": "FLOAT", "derivation": "ROLLUP", "rule": {"sourceNode": "ROI", "key": "vector_length", "aggregation": "MEAN", "evidence": rules.evidence(rules.rule(rules.via("good-tool")))}}],
                }
            ]
        }
    }
    made = await api_schema.execute(CREATE_GRAPH, variable_values={"input": {"name": "explained-honestly", "definition": definition}}, context_value=simple_api_context)
    assert made.errors is None, f"GraphQL errors: {made.errors}"
    graph_id = made.data["createGraph"]["id"]

    @sync_to_async
    def build():
        graph = core_models.Graph.objects.get(pk=graph_id)
        org = graph.organization
        ref = claims.mint(org, "Probe", "anyone")
        claims.measure(org, ref, obj="r1", key="vector_length", value=10.0, subject="pipeline", app_id="good-tool")
        claims.measure(org, ref, obj="r2", key="vector_length", value=999.0, subject="pipeline", app_id="bad-tool")
        graphs.rebuild(graph, table_projector)
        return ref

    ref = await build()
    read = await api_schema.execute(EXPLAIN, variable_values={"id": ref, "graph": graph_id}, context_value=simple_api_context)
    assert read.errors is None, f"GraphQL errors: {read.errors}"
    prop = next(p for p in read.data["node"]["richProperties"] if p["key"] == "avg_length")
    assert prop["value"] == pytest.approx(10.0)
    assert [m["value"] for m in prop["supportingEvidence"]] == [10.0], "the explanation lists exactly what the fold counted"
    assert {a["appId"] for a in prop["contributingAssertions"]} == {"good-tool"}
    assert prop["nEvidence"] == 1, "and the count agrees"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_narrowing_a_categorys_trust_takes_derived_values_and_windows_with_it(api_schema: kante.Schema, simple_api_context: HttpContext, table_projector, backend_stack) -> None:
    """The metric lane, end to end, at category grain (RFC 0009).

    A Probe measured through two ROIs derives `size` and an observation window
    when its category trusts the measurers. Rebuilt under clauses naming only
    the curator, the INFORMS links and metrics stop counting: the node stays —
    the curator classified it — but its derived knowledge is gone. This pins the
    leaks RFC 0008 closed staying closed under the per-category fold: informs
    routing, the scoped state, and `_observation_window` all follow the clauses.
    """
    graph_id = await _graph_declaring(api_schema, simple_api_context, "Probe", name="metric-lane")

    @sync_to_async
    def declare_property():
        category = core_models.EntityCategory.objects.get(graph_id=graph_id, key="Probe")
        category.property_definitions = [{"key": "size", "value_kind": "FLOAT", "derivation": "ROLLUP", "rule": {"source_node": "ROI", "key": "size", "aggregation": "MEAN"}}]
        category.save()

    await declare_property()

    # The baseline goes through the write path so the cached state vector is
    # maintained — the primitive category's fast path is exactly what is being
    # narrowed away below.
    ref = await writes.create_entity(
        api_schema,
        simple_api_context,
        "Probe",
        evidence=[
            {"identifier": "ROI", "object": "probe-roi-1", "metrics": [{"key": "size", "value": 10.0, "valueKind": "FLOAT"}]},
            {"identifier": "ROI", "object": "probe-roi-2", "metrics": [{"key": "size", "value": 30.0, "valueKind": "FLOAT"}]},
        ],
    )

    @sync_to_async
    def narrow_and_read():
        from tests.support import drawing

        graph = core_models.Graph.objects.get(pk=graph_id)
        category = core_models.EntityCategory.objects.get(graph=graph, key="Probe")
        graphs.rebuild(graph, table_projector)
        before = drawing.vertex_properties(graph, ref)

        # The curator also classified it, so narrowing to the curator keeps the
        # node while dropping the request identity's measurements and routing.
        claims.classify(graph, ref, category, "curator")
        category.definition = rules.definition(rules.rule(rules.word("Probe"), rules.by("curator")))
        category.save()
        graphs.rebuild(graph, table_projector)
        after = drawing.vertex_properties(graph, ref)
        return before, after

    before, after = await narrow_and_read()
    assert before.get("size") == pytest.approx(20.0), f"trusting everyone: mean size — got {before}"
    assert before.get("valid_from") is not None, "and a real observation window"
    assert after.get("id") == ref, "the node stands — the curator classified it"
    assert after.get("size") is None, f"but the untrusted measurements no longer derive a size — got {after}"
    assert after.get("valid_from") is None, "and the observation window they stretched is gone with them"


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


async def _execute(api_schema: kante.Schema, ctx: HttpContext, document: str, payload: dict) -> dict:
    result = await api_schema.execute(document, variable_values={"input": payload}, context_value=ctx)
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    return result.data


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


TREATMENT = datetime(2026, 6, 1, tzinfo=timezone.utc)
BEFORE = TREATMENT - timedelta(days=30)
AFTER = TREATMENT + timedelta(days=30)


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
