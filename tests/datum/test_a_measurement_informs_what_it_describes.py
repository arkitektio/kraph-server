"""Instance-level tests for metric mutations via the GraphQL API."""

import uuid

import kante
import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext

from core import models as core_models
from evidence import models as evidence_models
from graph_engine import input_models
from graph_engine.materialize import materialize


async def _get_or_create_structure_kind(test_graph: core_models.Graph) -> evidence_models.StructureKind:
    """The organization's ROI term. No graph — kinds are organization vocabulary."""
    kind, _ = await evidence_models.StructureKind.all_objects.aget_or_create(
        organization=test_graph.organization,
        identifier="roi_test",
    )
    return kind


async def _create_structure(api_schema: kante.Schema, simple_api_context: HttpContext, test_graph: core_models.Graph) -> str:
    category = await _get_or_create_structure_kind(test_graph)
    object_id = f"obj_{uuid.uuid4().hex[:8]}"

    create_mutation = """
        mutation CreateStructure($input: AssertStructureExistsInput!) {
            assertStructureExists(input: $input) { structure { id } }
        }
    """

    create_result = await api_schema.execute(
        create_mutation,
        variable_values={
            "input": {
                "identifier": category.identifier,
                "object": object_id,
                "metrics": [],
            }
        },
        context_value=simple_api_context,
    )

    assert create_result.errors is None, f"GraphQL errors: {create_result.errors}"
    assert create_result.data is not None
    return create_result.data["assertStructureExists"]["structure"]["id"]


async def _prepare_record_metric_categories(graph: core_models.Graph, identifier: str, key: str) -> evidence_models.StructureKind:
    structure_category = await evidence_models.StructureKind.objects.filter(graph=graph, identifier=identifier).afirst()
    if structure_category is None:
        structure_category = await evidence_models.StructureKind.objects.acreate_from_structure_definition(
            graph=graph,
            definition=input_models.StructureDefinitionInput(
                key=identifier,
                identifier=identifier,
            ),
        )

    metric_category = await evidence_models.MetricKind.objects.filter(graph=graph, key=key, structure_category=structure_category).afirst()
    if metric_category is None:
        await evidence_models.MetricKind.objects.acreate_from_metric_definition(
            graph=graph,
            definition=input_models.MetricDefinitionInput(
                key=key,
                structure=structure_category.identifier,
                value_kind=input_models.PropertyType.FLOAT,
            ),
        )

    return structure_category


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_record_metric_creates_the_structure_it_needs(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
):
    """An unknown identifier is created, not rejected.

    This replaces a pair of tests that exercised the per-graph
    `AUTO_ADD_STRUCTURES` rule. That gate is gone: a structure identifier is
    owned by the service that produced the datum, so there is nothing for a graph
    to approve, and refusing a measurement because no graph had declared the term
    was refusing a fact about the world on a bookkeeping technicality.

    Note the mutation names no graph at all.
    """
    mutation = """
        mutation RecordMetric($input: AssertMetricValueInput!) {
            assertMetricValue(input: $input) { metric { id value } }
        }
    """

    identifier = f"@test/never_seen_{uuid.uuid4().hex[:6]}"
    result = await api_schema.execute(
        mutation,
        variable_values={
            "input": {
                "identifier": identifier,
                "object": f"obj_{uuid.uuid4().hex[:6]}",
                "key": "area",
                "value": 12.34,
                "valueKind": "FLOAT",
            }
        },
        context_value=simple_api_context,
    )

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data["assertMetricValue"]["metric"]["value"] == 12.34

    created = await evidence_models.StructureKind.all_objects.filter(
        organization=test_graph.organization, identifier=identifier
    ).acount()
    assert created == 1, "The kind must have been minted by the write that needed it"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_metric(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
):
    structure_id = await _create_structure(api_schema, simple_api_context, test_graph)

    mutation = """
        mutation CreateMetric($input: AssertMetricValueForStructureInput!) {
            assertMetricValueForStructure(input: $input) { metric { id } }
        }
    """

    result = await api_schema.execute(
        mutation,
        variable_values={
            "input": {
                "structure": structure_id,
                "key": "area",
                "value": 12.5,
                "valueKind": "FLOAT",
            }
        },
        context_value=simple_api_context,
    )

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data is not None
    assert result.data["assertMetricValueForStructure"]["metric"]["id"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_update_metric(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
):
    structure_id = await _create_structure(api_schema, simple_api_context, test_graph)

    create_mutation = """
        mutation CreateMetric($input: AssertMetricValueForStructureInput!) {
            assertMetricValueForStructure(input: $input) { metric { id } }
        }
    """

    create_result = await api_schema.execute(
        create_mutation,
        variable_values={
            "input": {
                "structure": structure_id,
                "key": "area",
                "value": 12.5,
                "valueKind": "FLOAT",
            }
        },
        context_value=simple_api_context,
    )

    assert create_result.errors is None, f"GraphQL errors: {create_result.errors}"
    assert create_result.data is not None
    metric_id = create_result.data["assertMetricValueForStructure"]["metric"]["id"]

    update_mutation = """
        mutation UpdateMetric($input: SupersedeMetricValueInput!) {
            supersedeMetricValue(input: $input) { metric { id } }
        }
    """

    update_result = await api_schema.execute(
        update_mutation,
        variable_values={
            "input": {
                "id": metric_id,
                "key": "area",
                "value": 99.0,
                "valueKind": "FLOAT",
            }
        },
        context_value=simple_api_context,
    )

    assert update_result.errors is None, f"GraphQL errors: {update_result.errors}"
    assert update_result.data is not None
    assert update_result.data["supersedeMetricValue"]["metric"]["id"] != metric_id


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_archive_metric(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
):
    structure_id = await _create_structure(api_schema, simple_api_context, test_graph)

    create_mutation = """
        mutation CreateMetric($input: AssertMetricValueForStructureInput!) {
            assertMetricValueForStructure(input: $input) { metric { id } }
        }
    """

    create_result = await api_schema.execute(
        create_mutation,
        variable_values={
            "input": {
                "structure": structure_id,
                "key": "area",
                "value": 12.5,
                "valueKind": "FLOAT",
            }
        },
        context_value=simple_api_context,
    )

    assert create_result.errors is None, f"GraphQL errors: {create_result.errors}"
    assert create_result.data is not None
    metric_id = create_result.data["assertMetricValueForStructure"]["metric"]["id"]

    archive_mutation = """
        mutation ArchiveMetric($input: RetractMetricInput!) {
            retractMetric(input: $input) { metric { id } }
        }
    """

    archive_result = await api_schema.execute(
        archive_mutation,
        variable_values={"input": {"id": metric_id}},
        context_value=simple_api_context,
    )

    assert archive_result.errors is None, f"GraphQL errors: {archive_result.errors}"
    assert archive_result.data is not None
    assert archive_result.data["retractMetric"]["metric"]["id"] == metric_id


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_archive_metric_retracts_and_is_idempotent(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
):
    structure_id = await _create_structure(api_schema, simple_api_context, test_graph)

    create_mutation = """
        mutation CreateMetric($input: AssertMetricValueForStructureInput!) {
            assertMetricValueForStructure(input: $input) { metric { id } }
        }
    """

    create_result = await api_schema.execute(
        create_mutation,
        variable_values={
            "input": {
                "structure": structure_id,
                "key": "area",
                "value": 12.5,
                "valueKind": "FLOAT",
            }
        },
        context_value=simple_api_context,
    )

    assert create_result.errors is None, f"GraphQL errors: {create_result.errors}"
    assert create_result.data is not None
    metric_id = create_result.data["assertMetricValueForStructure"]["metric"]["id"]

    # `deleteMetric` is gone: it destroyed the metric without retracting its
    # contribution from the state vector, so derived values kept counting a
    # measurement that no longer existed. `archiveMetric` retracts properly.
    archive_mutation = """
        mutation ArchiveMetric($input: RetractMetricInput!) {
            retractMetric(input: $input) { metric { id } }
        }
    """

    archive_result = await api_schema.execute(
        archive_mutation,
        variable_values={"input": {"id": metric_id}},
        context_value=simple_api_context,
    )

    assert archive_result.errors is None, f"GraphQL errors: {archive_result.errors}"
    assert archive_result.data["retractMetric"]["metric"]["id"] == metric_id

    # Archiving twice is a no-op rather than a second retraction, so the state
    # vector cannot have a contribution subtracted from it twice.
    second = await api_schema.execute(
        archive_mutation,
        variable_values={"input": {"id": metric_id}},
        context_value=simple_api_context,
    )
    assert second.errors is None, f"GraphQL errors: {second.errors}"
