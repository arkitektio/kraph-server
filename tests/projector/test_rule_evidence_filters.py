"""`rule.evidence`: a derived property's own metric rule (RFC 0009).

A `DerivationRuleInput` may carry an evidence filter — whose measurements this
property counts, through which apps, in which belief and observation windows.
When present it *is* the metric rule for that property; when absent, the owning
category's clauses apply to the metrics' assertions too, and a primitive
category folds everything, as always. `conflict_policy` is gone: it was read by
nothing, and every real way of saying "whose numbers count" now exists —
derivation types for ranking, `rule.evidence` for filtering.
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from core import models as core_models
from graph_engine import input_models as models
from graph_engine.controller import GraphController
from graph_engine.materialize import compute_definition_hash, materialize
from tests import claims, drawing, rules as R

SUMMER_START = datetime(2026, 6, 1, tzinfo=timezone.utc)
SUMMER_END = datetime(2026, 8, 31, tzinfo=timezone.utc)


def _definition(*, rule_evidence: list | None = None, category_definition: models.CategoryDefinitionInput | None = None) -> models.GraphDefinitionInput:
    return models.GraphDefinitionInput(
        system_version="1.0.0",
        extensions=models.GraphExtensionsInput(
            entities=[
                models.EntityDefinitionInput(
                    key="Probe",
                    definition=category_definition,
                    property_definitions=[
                        models.PropertyDefinitionInput(
                            key="avg_length",
                            type=models.PropertyType.FLOAT,
                            derivation=models.DerivationType.ROLLUP,
                            rule=models.DerivationRuleInput(source_node="ROI", key="vector_length", aggregation=models.AggregationFunction.MEAN, evidence=rule_evidence),
                        )
                    ],
                )
            ]
        ),
    )


def _graph(definition: models.GraphDefinitionInput, table_projector, authenticated_context, name: str) -> core_models.Graph:
    request = authenticated_context.request
    return materialize(definition, table_projector, user=request._user, organization=request._organization, membership=request.membership, name=name)


def _fold(graph: core_models.Graph, table_projector, ref: str) -> dict:
    GraphController(projector=table_projector).rebuild_projection(graph)
    return drawing.vertex_properties(graph, ref)


@pytest.mark.django_db(transaction=True)
def test_rule_evidence_applies_on_an_unscoped_category(transactional_db, table_projector, authenticated_context) -> None:
    """The gating fix: a primitive category, and the rule's filter still narrows."""
    graph = _graph(_definition(rule_evidence=[R.via("good-tool")]), table_projector, authenticated_context, "rule-unscoped")
    org = graph.organization
    ref = claims.mint(org, "Probe", "anyone")
    claims.measure(org, ref, obj="r1", key="vector_length", value=10.0, subject="pipeline", app_id="good-tool")
    claims.measure(org, ref, obj="r2", key="vector_length", value=30.0, subject="pipeline", app_id="good-tool")
    claims.measure(org, ref, obj="r3", key="vector_length", value=500.0, subject="pipeline", app_id="bad-tool")
    properties = _fold(graph, table_projector, ref)
    assert properties.get("avg_length") == pytest.approx(20.0), f"the rule's own filter must narrow even with no category clauses: {properties}"


@pytest.mark.django_db(transaction=True)
def test_category_clauses_are_the_default_metric_rule(transactional_db, table_projector, authenticated_context) -> None:
    """No `rule.evidence` → the category's clauses scope the metrics' assertions."""
    category_definition = models.CategoryDefinitionInput.model_validate(R.definition(R.rule(R.word("Probe"), R.by("peter"))))
    graph = _graph(_definition(category_definition=category_definition), table_projector, authenticated_context, "rule-default")
    org = graph.organization
    ref = claims.mint(org, "Probe", "peter")
    claims.measure(org, ref, obj="r1", key="vector_length", value=10.0, subject="peter", inform_subject="peter")
    claims.measure(org, ref, obj="r2", key="vector_length", value=999.0, subject="stranger", inform_subject="peter")
    properties = _fold(graph, table_projector, ref)
    assert properties.get("avg_length") == pytest.approx(10.0), f"a defined category's metrics default to its clauses: {properties}"


@pytest.mark.django_db(transaction=True)
def test_rule_evidence_replaces_the_default(transactional_db, table_projector, authenticated_context) -> None:
    """With `rule.evidence` present, it is the metric rule — the clauses do not
    also constrain the rows (classification annotators rarely produce metrics)."""
    category_definition = models.CategoryDefinitionInput.model_validate(R.definition(R.rule(R.word("Probe"), R.by("peter"))))
    graph = _graph(
        _definition(category_definition=category_definition, rule_evidence=[R.via("good-tool")]),
        table_projector,
        authenticated_context,
        "rule-replaces",
    )
    org = graph.organization
    ref = claims.mint(org, "Probe", "peter")
    claims.measure(org, ref, obj="r1", key="vector_length", value=10.0, subject="pipeline", app_id="good-tool", inform_subject="peter")
    claims.measure(org, ref, obj="r2", key="vector_length", value=100.0, subject="pipeline", app_id="bad-tool", inform_subject="peter")
    properties = _fold(graph, table_projector, ref)
    assert properties.get("avg_length") == pytest.approx(10.0), f"the rule's filter governs, the clause's subjects do not exclude the pipeline: {properties}"


@pytest.mark.django_db(transaction=True)
def test_observed_window_narrows_measured_at(transactional_db, table_projector, authenticated_context) -> None:
    graph = _graph(_definition(rule_evidence=[R.measured_since(SUMMER_START), R.measured_before(SUMMER_END)]), table_projector, authenticated_context, "rule-window")
    org = graph.organization
    ref = claims.mint(org, "Probe", "anyone")
    claims.measure(org, ref, obj="r1", key="vector_length", value=10.0, subject="pipeline", measured_at=datetime(2026, 7, 1, tzinfo=timezone.utc))
    claims.measure(org, ref, obj="r2", key="vector_length", value=999.0, subject="pipeline", measured_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    properties = _fold(graph, table_projector, ref)
    assert properties.get("avg_length") == pytest.approx(10.0), f"only observations inside the window fold: {properties}"


@pytest.mark.django_db(transaction=True)
def test_priority_latest_cannot_be_won_by_an_excluded_source(transactional_db, table_projector, authenticated_context) -> None:
    definition = models.GraphDefinitionInput(
        system_version="1.0.0",
        extensions=models.GraphExtensionsInput(
            entities=[
                models.EntityDefinitionInput(
                    key="Probe",
                    property_definitions=[
                        models.PropertyDefinitionInput(
                            key="length",
                            type=models.PropertyType.FLOAT,
                            derivation=models.DerivationType.PRIORITY_LATEST,
                            rule=models.DerivationRuleInput(
                                source_node="ROI",
                                key="vector_length",
                                subject_priority=["expert", "pipeline"],
                                evidence=[models.ClaimConditionInput.model_validate(R.by("pipeline"))],
                            ),
                        )
                    ],
                )
            ]
        ),
    )
    graph = _graph(definition, table_projector, authenticated_context, "rule-priority")
    org = graph.organization
    ref = claims.mint(org, "Probe", "anyone")
    claims.measure(org, ref, obj="r1", key="vector_length", value=10.0, subject="pipeline")
    claims.measure(org, ref, obj="r2", key="vector_length", value=999.0, subject="expert")
    properties = _fold(graph, table_projector, ref)
    assert properties.get("length") == pytest.approx(10.0), "a source the rule's evidence excludes cannot win, even ranked first"


def test_evidence_without_a_source_is_refused() -> None:
    with pytest.raises(ValidationError, match="source_node"):
        models.DerivationRuleInput(evidence=[models.ClaimConditionInput.model_validate(R.by("x"))])


def test_conflict_policy_is_gone() -> None:
    """The dead knob is unspellable, not silently accepted."""
    with pytest.raises(ValidationError):
        models.DerivationRuleInput(source_node="ROI", key="k", conflict_policy="COMBINE")
    assert not hasattr(models, "ConflictPolicy"), "the enum goes with the field"


def test_a_rule_evidence_change_moves_the_definition_hash() -> None:
    """Trust edits are versioned: the hash the staleness machinery reads moves."""
    plain = _definition(rule_evidence=[R.via("a")])
    other = _definition(rule_evidence=[R.via("b")])
    assert compute_definition_hash(plain) != compute_definition_hash(other)


@pytest.mark.django_db(transaction=True)
def test_a_measurement_only_rule_is_the_category_default_metric_scope(transactional_db, table_projector, authenticated_context) -> None:
    """RFC 0011: a `KIND IS MEASUREMENT` rule scopes the fold for every property
    without its own `rule.evidence` — and may bound observation time.

    Grants union, so the general rule must carve MEASUREMENT out (`NOT_IN`) or
    it would keep granting every measurer — the same carve-out shape the
    sameness flagship uses."""
    category_definition = models.CategoryDefinitionInput.model_validate(
        R.definition(
            R.rule(R.word("Probe"), R.not_kind("MEASUREMENT")),
            R.rule(R.of_kind("MEASUREMENT"), R.via("good-tool"), R.measured_since(SUMMER_START)),
        )
    )
    graph = _graph(_definition(category_definition=category_definition), table_projector, authenticated_context, "measurement-kind")
    org = graph.organization
    ref = claims.mint(org, "Probe", "anyone")
    claims.measure(org, ref, obj="m1", key="vector_length", value=10.0, subject="pipeline", app_id="good-tool", measured_at=datetime(2026, 7, 1, tzinfo=timezone.utc))
    claims.measure(org, ref, obj="m2", key="vector_length", value=500.0, subject="pipeline", app_id="bad-tool", measured_at=datetime(2026, 7, 1, tzinfo=timezone.utc))
    claims.measure(org, ref, obj="m3", key="vector_length", value=900.0, subject="pipeline", app_id="good-tool", measured_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    properties = _fold(graph, table_projector, ref)
    assert properties.get("avg_length") == pytest.approx(10.0), f"only the trusted app inside the window folds: {properties}"
