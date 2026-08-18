"""Every claim kind that can be retracted can be re-attested.

`attest*` used to exist for four of ten claim kinds — entity, natural event,
protocol event and comment. Structures, metrics, relations, measurements,
structure relations, participations and sameness could all be retracted and had
no counterpart, so a retraction of any of them was one-way through the API.

That contradicts the rule the write side is built on, stated in CLAUDE.md:
existence is evidence, two people may disagree about it, and each graph's
selector decides whose word it counts. A position you cannot restate is not
evidence, it is a state machine.

`attestStructure`, `attestMetric` and `attestLink` close the gap — `attestLink`
covering every `Link.Kind` in one act, as `retractLinks` already does, because
the act does not differ by kind and the row says which kind it is.
"""

import uuid

import kante
import pytest
from kante.context import HttpContext

from core import models as core_models
from evidence import models as evidence_models


async def _structure_kind(test_graph: core_models.Graph) -> evidence_models.StructureKind:
    kind, _ = await evidence_models.StructureKind.all_objects.aget_or_create(
        organization=test_graph.organization,
        identifier="roi_attest",
    )
    return kind


async def _make_structure(api_schema: kante.Schema, ctx: HttpContext, test_graph: core_models.Graph) -> str:
    kind = await _structure_kind(test_graph)
    result = await api_schema.execute(
        """
        mutation CreateStructure($input: AssertStructureExistsInput!) {
            assertStructureExists(input: $input) { structure { id } }
        }
        """,
        variable_values={
            "input": {
                "identifier": kind.identifier,
                "object": f"obj_{uuid.uuid4().hex[:8]}",
                "metrics": [{"key": "vector_length", "value": 12.5, "valueKind": "FLOAT"}],
            }
        },
        context_value=ctx,
    )
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    return result.data["assertStructureExists"]["structure"]["id"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_retracted_structure_can_be_attested(api_schema, simple_api_context, test_graph):
    structure_id = await _make_structure(api_schema, simple_api_context, test_graph)

    retracted = await api_schema.execute(
        "mutation R($input: RetractStructureInput!) { retractStructure(input: $input) { assertion { id } } }",
        variable_values={"input": {"id": structure_id}},
        context_value=simple_api_context,
    )
    assert retracted.errors is None, f"GraphQL errors: {retracted.errors}"

    attested = await api_schema.execute(
        "mutation A($input: AttestStructureInput!) { attestStructure(input: $input) { assertion { id } structure { id } } }",
        variable_values={"input": {"id": structure_id}},
        context_value=simple_api_context,
    )

    assert attested.errors is None, f"GraphQL errors: {attested.errors}"
    assert attested.data["attestStructure"]["structure"]["id"] == structure_id

    # Both positions stay on the record — an attestation is new evidence, not an
    # undo, so the retraction is still there to be read.
    standings = await api_schema.execute(
        "query S($id: ID!) { standings(id: $id) { stands } }",
        variable_values={"id": structure_id},
        context_value=simple_api_context,
    )
    assert standings.errors is None, f"GraphQL errors: {standings.errors}"
    positions = [s["stands"] for s in standings.data["standings"]]
    assert True in positions and False in positions, f"Both positions should survive, got {positions}"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_retracted_metric_can_be_attested(api_schema, simple_api_context, test_graph):
    structure_id = await _make_structure(api_schema, simple_api_context, test_graph)

    metrics = await api_schema.execute(
        "query M($structureId: ID!) { metricsForStructure(structureId: $structureId) { id } }",
        variable_values={"structureId": structure_id},
        context_value=simple_api_context,
    )
    assert metrics.errors is None, f"GraphQL errors: {metrics.errors}"
    metric_id = metrics.data["metricsForStructure"][0]["id"]

    retracted = await api_schema.execute(
        "mutation R($input: RetractMetricInput!) { retractMetric(input: $input) { assertion { id } } }",
        variable_values={"input": {"id": metric_id}},
        context_value=simple_api_context,
    )
    assert retracted.errors is None, f"GraphQL errors: {retracted.errors}"

    attested = await api_schema.execute(
        "mutation A($input: AttestMetricInput!) { attestMetric(input: $input) { assertion { id } metric { id } } }",
        variable_values={"input": {"id": metric_id}},
        context_value=simple_api_context,
    )

    assert attested.errors is None, f"GraphQL errors: {attested.errors}"
    assert attested.data["attestMetric"]["metric"]["id"] == metric_id


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_retracted_link_can_be_attested(api_schema, simple_api_context, test_graph):
    """One mutation for every `Link.Kind` — here a relation between two entities.

    A relation rather than a classification: `connections` deliberately reports
    neither labels nor merges, so a CLASSIFIES claim is not reachable that way —
    it surfaces as `labels` instead.
    """
    category = await core_models.EntityCategory.objects.filter(graph=test_graph).afirst()
    assert category is not None, "The bio schema must materialize at least one entity category"

    relation_category = await core_models.RelationCategory.objects.filter(graph=test_graph).afirst()
    assert relation_category is not None, "The bio schema must materialize at least one relation category"

    async def _entity() -> str:
        created = await api_schema.execute(
            "mutation C($input: AssertEntityExistsInput!) { assertEntityExists(input: $input) { instance { id } } }",
            variable_values={"input": {"term": category.key}},
            context_value=simple_api_context,
        )
        assert created.errors is None, f"GraphQL errors: {created.errors}"
        return created.data["assertEntityExists"]["instance"]["id"]

    source_id, target_id = await _entity(), await _entity()

    related = await api_schema.execute(
        "mutation Rel($input: AssertRelationExistsInput!) { assertRelationExists(input: $input) { link { id kind } } }",
        variable_values={"input": {"sourceId": source_id, "targetId": target_id, "term": relation_category.key}},
        context_value=simple_api_context,
    )
    assert related.errors is None, f"GraphQL errors: {related.errors}"
    link_id = related.data["assertRelationExists"]["link"]["id"]

    retracted = await api_schema.execute(
        "mutation R($input: RetractLinksInput!) { retractLinks(input: $input) { links { id } } }",
        variable_values={"input": {"ids": [link_id]}},
        context_value=simple_api_context,
    )
    assert retracted.errors is None, f"GraphQL errors: {retracted.errors}"

    attested = await api_schema.execute(
        "mutation A($input: AttestLinkInput!) { attestLink(input: $input) { assertion { id } links { id kind } } }",
        variable_values={"input": {"id": link_id}},
        context_value=simple_api_context,
    )

    assert attested.errors is None, f"GraphQL errors: {attested.errors}"
    assert attested.data["attestLink"]["links"][0]["id"] == link_id
    assert attested.data["attestLink"]["links"][0]["kind"] == "RELATION"
