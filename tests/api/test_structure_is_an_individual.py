"""A structure is an individual with an external identity (RFC 0023).

Its existence has a standing, the folds honour it, and agreeing that it exists
is countable — the three things a datum-as-row could not do.
"""

import uuid

import pytest
from asgiref.sync import sync_to_async

from evidence import models as evidence_models
from tests.support import writes

STRUCTURE_BY_IDENTIFIER = """
    query S($identifier: StructureIdentifier!, $object: StructureObject!) {
        structureByIdentifier(identifier: $identifier, object: $object) { id observedAt confidence }
    }
"""

NODE_PROPERTIES = """
    query N($id: ID!, $graph: ID!) { node(id: $id, graph: $graph) { ... on Entity { properties } } }
"""

STANDINGS = """
    query S($id: ID!) { standings(id: $id) { stands assertion { id } } }
"""


async def _entity_with_roi(api_schema, ctx, object_id: str, length: float) -> str:
    result = await api_schema.execute(
        writes.ASSERT_ENTITY_EXISTS,
        variable_values={"input": {"term": "AIS", "supportingEvidence": [{"identifier": "ROI", "object": object_id, "metrics": [{"key": "vector_length", "value": length, "valueKind": "FLOAT"}]}]}},
        context_value=ctx,
    )
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    return result.data["assertEntityExists"]["instance"]["id"]


async def _structure_id(api_schema, ctx, object_id: str) -> str:
    found = await api_schema.execute(STRUCTURE_BY_IDENTIFIER, variable_values={"identifier": "ROI", "object": object_id}, context_value=ctx)
    assert found.errors is None, f"GraphQL errors: {found.errors}"
    return found.data["structureByIdentifier"]["id"]


async def _avg_length(api_schema, ctx, graph, entity: str):
    result = await api_schema.execute(NODE_PROPERTIES, variable_values={"id": entity, "graph": str(graph.pk)}, context_value=ctx)
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    return result.data["node"]["properties"].get("avg_length")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_retracting_a_datum_stops_its_evidence_counting(api_schema, simple_api_context, test_graph) -> None:
    """The datum's standing is honoured by the fold: retract it and the derived
    value it fed is refolded without it; attest it and the value returns. Its
    metric claims are untouched either way."""
    object_id = f"roi-{uuid.uuid4().hex[:8]}"
    entity = await _entity_with_roi(api_schema, simple_api_context, object_id, 30.0)
    assert await _avg_length(api_schema, simple_api_context, test_graph, entity) == pytest.approx(30.0)
    structure = await _structure_id(api_schema, simple_api_context, object_id)

    retracted = await api_schema.execute("mutation R($input: RetractStructureInput!) { retractStructure(input: $input) { assertion { id } } }", variable_values={"input": {"id": structure}}, context_value=simple_api_context)
    assert retracted.errors is None, f"GraphQL errors: {retracted.errors}"
    assert await _avg_length(api_schema, simple_api_context, test_graph, entity) is None, "a retracted datum informs nothing"

    metrics = await sync_to_async(lambda: evidence_models.Metric.all_objects.filter(structure_id=structure).count())()
    assert metrics == 1, "the metric claim is on the record, untouched"

    attested = await api_schema.execute("mutation A($input: AttestStructureInput!) { attestStructure(input: $input) { assertion { id } } }", variable_values={"input": {"id": structure}}, context_value=simple_api_context)
    assert attested.errors is None, f"GraphQL errors: {attested.errors}"
    assert await _avg_length(api_schema, simple_api_context, test_graph, entity) == pytest.approx(30.0), "attested, it counts again"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_second_existence_claim_is_agreement(api_schema, simple_api_context, test_graph) -> None:
    """One datum, one row; the second explicit claim is a standing under its own
    act, so agreement is countable and identity stays external."""
    object_id = f"roi-{uuid.uuid4().hex[:8]}"
    mutation = "mutation C($input: AssertStructureExistsInput!) { assertStructureExists(input: $input) { assertion { id } structure { id observedAt confidence } } }"

    first = await api_schema.execute(mutation, variable_values={"input": {"identifier": "ROI", "object": object_id, "metrics": [], "confidence": 0.9}}, context_value=simple_api_context)
    assert first.errors is None, f"GraphQL errors: {first.errors}"
    second = await api_schema.execute(mutation, variable_values={"input": {"identifier": "ROI", "object": object_id, "metrics": []}}, context_value=simple_api_context)
    assert second.errors is None, f"GraphQL errors: {second.errors}"

    assert first.data["assertStructureExists"]["structure"]["id"] == second.data["assertStructureExists"]["structure"]["id"]
    assert first.data["assertStructureExists"]["structure"]["confidence"] == pytest.approx(0.9)
    assert first.data["assertStructureExists"]["structure"]["observedAt"]

    standings = await api_schema.execute(STANDINGS, variable_values={"id": second.data["assertStructureExists"]["structure"]["id"]}, context_value=simple_api_context)
    assert standings.errors is None, f"GraphQL errors: {standings.errors}"
    assert [(row["stands"], row["assertion"]["id"]) for row in standings.data["standings"]] == [(True, second.data["assertStructureExists"]["assertion"]["id"])]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_retracting_an_informs_claim_refolds_what_it_fed(api_schema, simple_api_context, test_graph) -> None:
    """`_reproject_claim` used to redraw the node from a `State` row still holding
    the withdrawn datum's contribution."""
    object_id = f"roi-{uuid.uuid4().hex[:8]}"
    entity = await _entity_with_roi(api_schema, simple_api_context, object_id, 30.0)
    structure = await _structure_id(api_schema, simple_api_context, object_id)

    @sync_to_async
    def informs_link() -> str:
        return str(evidence_models.Link.all_objects.get(kind=evidence_models.Link.Kind.INFORMS, source_ref=structure, target_ref=entity).pk)

    link = await informs_link()
    retracted = await api_schema.execute("mutation R($input: RetractLinksInput!) { retractLinks(input: $input) { assertion { id } } }", variable_values={"input": {"ids": [link]}}, context_value=simple_api_context)
    assert retracted.errors is None, f"GraphQL errors: {retracted.errors}"
    assert await _avg_length(api_schema, simple_api_context, test_graph, entity) is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_retracting_a_measurement_retracts_its_informs_row(api_schema, simple_api_context, test_graph) -> None:
    """A measurement is one claim written as two rows; the act that retracts it
    retracts both, and the values it fed are refolded."""
    entity = await writes.create_entity(api_schema, simple_api_context, "AIS")
    object_id = f"roi-{uuid.uuid4().hex[:8]}"
    made = await api_schema.execute(
        "mutation C($input: AssertStructureExistsInput!) { assertStructureExists(input: $input) { structure { id } } }",
        variable_values={"input": {"identifier": "ROI", "object": object_id, "metrics": [{"key": "vector_length", "value": 12.0, "valueKind": "FLOAT"}]}},
        context_value=simple_api_context,
    )
    assert made.errors is None, f"GraphQL errors: {made.errors}"
    structure = made.data["assertStructureExists"]["structure"]["id"]

    measured = await api_schema.execute(
        "mutation M($input: AssertMeasurementExistsInput!) { assertMeasurementExists(input: $input) { link { id } } }",
        variable_values={"input": {"term": "measured_by", "sourceId": structure, "targetId": entity, "supportingEvidence": []}},
        context_value=simple_api_context,
    )
    assert measured.errors is None, f"GraphQL errors: {measured.errors}"
    measurement = measured.data["assertMeasurementExists"]["link"]["id"]
    assert await _avg_length(api_schema, simple_api_context, test_graph, entity) == pytest.approx(12.0)

    retracted = await api_schema.execute("mutation R($input: RetractLinksInput!) { retractLinks(input: $input) { assertion { id } } }", variable_values={"input": {"ids": [measurement]}}, context_value=simple_api_context)
    assert retracted.errors is None, f"GraphQL errors: {retracted.errors}"

    @sync_to_async
    def standings() -> dict[str, list[bool]]:
        rows = evidence_models.Link.all_objects.filter(source_ref=structure, target_ref=entity, kind__in=[evidence_models.Link.Kind.MEASUREMENT, evidence_models.Link.Kind.INFORMS])
        return {str(row.kind): [s.stands for s in evidence_models.Standing.all_objects.filter(target_type="link", target_id=str(row.pk))] for row in rows}

    assert await standings() == {str(evidence_models.Link.Kind.MEASUREMENT): [False], str(evidence_models.Link.Kind.INFORMS): [False]}
    assert await _avg_length(api_schema, simple_api_context, test_graph, entity) is None
