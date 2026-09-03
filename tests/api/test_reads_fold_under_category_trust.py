"""Two reads that leaked past the view's trust, pinned (RFC 0008 → 0009).

- `supportingEvidence` / `contributingAssertions` re-implemented the INFORMS
  and metric lookups inline and applied no scoping at all, so the explanation
  disagreed with the number it explained.
- `inputParticipations(graph:)` / `outputParticipations(graph:)` used the
  view's membership but folded standing organization-wide and applied no claim
  scope, so they listed participations the same view refused to draw.

Both must answer under the category's rule now.
"""

from datetime import datetime, timezone

import kante
import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext

from core import models as core_models
from graph_engine.controller import GraphController
from tests import claims, rules

CREATE_GRAPH = """
    mutation G($input: CreateGraphInput!) {
        createGraph(input: $input) { id }
    }
"""

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
                    "propertyDefinitions": [
                        {"key": "avg_length", "valueKind": "FLOAT", "derivation": "ROLLUP", "rule": {"sourceNode": "ROI", "key": "vector_length", "aggregation": "MEAN", "evidence": [rules.via("good-tool")]}}
                    ],
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
        GraphController(projector=table_projector).rebuild_projection(graph)
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
async def test_participation_lists_fold_under_the_event_categorys_clauses(api_schema: kante.Schema, simple_api_context: HttpContext, table_projector) -> None:
    definition = {
        "extensions": {
            "entities": [{"key": "Cell"}],
            "events": [
                {
                    "key": "Mitosis",
                    "kind": "INTRINSIC",
                    "definition": rules.definition(rules.rule(rules.word("Mitosis"), rules.via("event-annotator"))),
                    "inputs": [{"key": "Cell", "role": "mother", "descriptor": {"keys": ["Cell"]}}],
                    "outputs": [],
                }
            ],
        }
    }
    made = await api_schema.execute(CREATE_GRAPH, variable_values={"input": {"name": "listed-honestly", "definition": definition}}, context_value=simple_api_context)
    assert made.errors is None, f"GraphQL errors: {made.errors}"
    graph_id = made.data["createGraph"]["id"]

    @sync_to_async
    def build():
        graph = core_models.Graph.objects.get(pk=graph_id)
        org = graph.organization
        cell = claims.mint(org, "Cell", "peter")
        event = claims.mint(org, "Mitosis", "anyone", app_id="event-annotator", kind="NATURAL_EVENT")
        trusted = claims.participate(org, "Mitosis", cell, event, "anyone", app_id="event-annotator", role="mother")
        untrusted = claims.participate(org, "Mitosis", claims.mint(org, "Cell", "peter"), event, "anyone", app_id="freehand", role="mother")
        return str(trusted.pk), str(untrusted.pk)

    trusted_id, untrusted_id = await build()
    listed = await api_schema.execute(INPUT_PARTICIPATIONS, variable_values={"graph": graph_id}, context_value=simple_api_context)
    assert listed.errors is None, f"GraphQL errors: {listed.errors}"
    ids = {row["id"] for row in listed.data["inputParticipations"]}
    assert trusted_id in ids, "the trusted app's participation is listed"
    assert untrusted_id not in ids, "one the event's clause refuses is not — the list agrees with the drawing"
