"""Instance-level tests for metric mutations via the GraphQL API."""

import uuid
import kante
import pytest
from kante.context import HttpContext
from core import models as core_models
from evidence import models as evidence_models
from graph_engine import input_models
from asgiref.sync import sync_to_async
from graph_engine import input_models as models
from graph_engine.materialize import materialize
from tests.support import writes


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

    created = await evidence_models.StructureKind.all_objects.filter(organization=test_graph.organization, identifier=identifier).acount()
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


CREATE_STRUCTURE = """
    mutation CreateStructure($input: AssertStructureExistsInput!) {
        assertStructureExists(input: $input) { structure { id } }
    }
"""
CREATE_ENTITY = """
    mutation CreateEntity($input: AssertEntityExistsInput!) {
        assertEntityExists(input: $input) { instance { id } }
    }
"""
CREATE_MEASUREMENT = """
    mutation CreateMeasurement($input: AssertMeasurementExistsInput!) {
        assertMeasurementExists(input: $input) {
            link {
                id
                kind
                source { ... on Structure { id object } }
                target { ... on Instance { id } }
            }
        }
    }
"""
ENTITY_PROPERTIES = """
    query Entity($id: ID!, $graph: ID!) {
        node(id: $id, graph: $graph) {
            ... on Entity { id properties }
        }
    }
"""


@pytest.fixture(scope="session")
def edge_schema() -> models.GraphDefinitionInput:
    """A schema that declares the two edge kinds the bio schema leaves out.

    `MEASURES` runs from an ROI to an AIS, and AIS carries a MEAN rollup over
    `vector_length` — so attaching a measurement has an observable consequence
    and the INFORMS claim can be tested through its effect rather than by
    inspecting rows.
    """
    return models.GraphDefinitionInput(
        system_version="1.0.0",
        extensions=models.GraphExtensionsInput(
            entities=[
                models.EntityDefinitionInput(
                    key="AIS",
                    property_definitions=[
                        models.PropertyDefinitionInput(
                            key="avg_length",
                            type=models.PropertyType.FLOAT,
                            index=True,
                            derivation=models.DerivationType.ROLLUP,
                            rule=models.DerivationRuleInput(source_node="ROI", key="vector_length", aggregation=models.AggregationFunction.MEAN),
                        )
                    ],
                )
            ],
            structure_relations=[
                models.StructureRelationDefinitionInput(
                    key="CONTAINS",
                    source=models.StructureDescriptorInput(identifiers=["ROI"]),
                    target=models.StructureDescriptorInput(identifiers=["ROI"]),
                )
            ],
            measurements=[
                models.MeasurementDefinitionInput(
                    key="MEASURES",
                    source=models.StructureDescriptorInput(identifiers=["ROI"]),
                    target=models.EntityDescriptorInput(keys=["AIS"]),
                )
            ],
        ),
    )


@pytest.fixture(scope="function")
def edge_graph(transactional_db, table_projector, edge_schema, authenticated_context) -> core_models.Graph:
    request = authenticated_context.request
    return materialize(
        edge_schema,
        table_projector,
        user=request._user,
        organization=request._organization,
        membership=request.membership,
        name="edge_graph",
    )


async def _structure(api_schema: kante.Schema, ctx: HttpContext, metrics: list[dict] | None = None) -> str:
    created = await api_schema.execute(
        CREATE_STRUCTURE,
        variable_values={"input": {"identifier": "ROI", "object": f"roi_{uuid.uuid4().hex[:8]}", "metrics": metrics or []}},
        context_value=ctx,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    return created.data["assertStructureExists"]["structure"]["id"]


async def _ais(api_schema: kante.Schema, ctx: HttpContext, graph: core_models.Graph) -> str:
    category = await core_models.EntityCategory.objects.filter(graph=graph, key="AIS").afirst()
    assert category is not None
    created = await api_schema.execute(
        CREATE_ENTITY,
        variable_values={"input": {"term": category.key, "supportingEvidence": []}},
        context_value=ctx,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    return created.data["assertEntityExists"]["instance"]["id"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_measurement_rolls_its_metrics_up(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    edge_graph: core_models.Graph,
) -> None:
    """The claim that makes measurements more than bookkeeping.

    `dirty()` matches on `kind=INFORMS`, so a measurement that recorded only its
    typed link would leave the entity deriving nothing at all — the exact
    silent-no-op this codebase treats as a defect.
    """
    category = await core_models.MeasurementCategory.objects.filter(graph=edge_graph, key="MEASURES").afirst()
    assert category is not None, "The schema declares a MEASURES measurement"

    structure = await _structure(api_schema, simple_api_context, metrics=[{"key": "vector_length", "value": 42.0, "valueKind": "FLOAT"}])
    entity = await _ais(api_schema, simple_api_context, edge_graph)

    before = await api_schema.execute(ENTITY_PROPERTIES, variable_values={"id": entity, "graph": str(edge_graph.id)}, context_value=simple_api_context)
    assert before.errors is None, f"GraphQL errors: {before.errors}"
    assert before.data["node"]["properties"].get("avg_length") is None, "Nothing may derive before the measurement is asserted"

    created = await api_schema.execute(
        CREATE_MEASUREMENT,
        variable_values={"input": {"term": category.key, "sourceId": structure, "targetId": entity}},
        context_value=simple_api_context,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    measurement = created.data["assertMeasurementExists"]["link"]

    # A measurement runs structure → entity, and both ends resolve. `source` and
    # `target` were stubs raising on a non-null field until now.
    assert measurement["source"]["object"], "The structure that did the measuring"
    assert measurement["target"]["id"], "and the entity it is about"

    after = await api_schema.execute(ENTITY_PROPERTIES, variable_values={"id": entity, "graph": str(edge_graph.id)}, context_value=simple_api_context)
    assert after.errors is None, f"GraphQL errors: {after.errors}"
    assert after.data["node"]["properties"].get("avg_length") == pytest.approx(42.0), "Asserting a measurement must move the derived value"

    @sync_to_async
    def link_kinds() -> list[str]:
        from evidence import selector as selector_module

        return sorted(evidence_models.Link.objects.for_organization(edge_graph.organization).filter(target_ref__in=selector_module.instance_ids_for(edge_graph)).values_list("kind", flat=True))

    kinds = await link_kinds()
    assert evidence_models.Link.Kind.MEASUREMENT in kinds, "The typed claim names which term of the schema was asserted"
    assert evidence_models.Link.Kind.INFORMS in kinds, "The plain claim is what dirty() matches, and without it nothing rolls up"


ASSERT_RELATION = """
    mutation AssertRelation($input: AssertRelationExistsInput!) {
        assertRelationExists(input: $input) {
            link {
                id
                kind
                term { key }
                sourceRef
                targetRef
                source { ... on Instance { id kind } }
                target { ... on Instance { id kind } }
            }
            drawings { graph { id } }
        }
    }
"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_evidence_can_inform_a_claim_rather_than_a_node(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The `INFORMS` fallback: a ref that names another claim, not an instance.

    Structures justifying "these two cells are connected" inform the **relation**, so
    `_attach_supporting_evidence` writes the INFORMS link against the edge's own ref.
    That is the one endpoint whose table `kind` alone cannot decide, so
    `_resolve_claim_endpoint` tries an instance and then a link — and this is the only
    test that reaches the second try.
    """
    source = await writes.create_entity(api_schema, simple_api_context, "Cell")
    target = await writes.create_entity(api_schema, simple_api_context, "Cell")

    created = await api_schema.execute(
        ASSERT_RELATION,
        variable_values={
            "input": {
                "term": "IS_CONNECTED_TO",
                "sourceId": source,
                "targetId": target,
                "supportingEvidence": [{"identifier": "@mikro/roi", "object": "roi-informs-an-edge", "metrics": [{"key": "vector_length", "value": 7.0, "valueKind": "FLOAT"}]}],
            }
        },
        context_value=simple_api_context,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    relation_id = created.data["assertRelationExists"]["link"]["id"]

    @sync_to_async
    def informs_id() -> str:
        from evidence import models as evidence_models

        link = evidence_models.Link.objects.for_organization(test_graph.organization).filter(kind=evidence_models.Link.Kind.INFORMS, target_ref=relation_id).first()
        assert link is not None, "The supporting structure informs the relation, not either endpoint"
        return str(link.pk)

    read = await api_schema.execute(
        """
        query ReadInforms($id: ID!) {
            link(id: $id) {
                kind
                source { ... on Structure { id identifier } }
                target { ... on Link { id kind } ... on Instance { id } }
            }
        }
        """,
        variable_values={"id": await informs_id()},
        context_value=simple_api_context,
    )

    assert read.errors is None, f"GraphQL errors: {read.errors}"
    informs = read.data["link"]
    assert informs["kind"] == "INFORMS"
    assert informs["source"]["identifier"] == "@mikro/roi", "The structure that justifies the claim"
    assert informs["target"]["id"] == relation_id, "and the claim it justifies, which is a link rather than a node"
    assert informs["target"]["kind"] == "RELATION"


async def _create_structure_row(
    api_schema: kante.Schema,
    ctx: HttpContext,
    test_graph: core_models.Graph,
    object_id: str,
) -> str:
    category = await _get_or_create_structure_kind(test_graph)
    result = await api_schema.execute(
        """
        mutation CreateStructure($input: AssertStructureExistsInput!) {
            assertStructureExists(input: $input) { structure { id } }
        }
        """,
        variable_values={
            "input": {
                "identifier": category.identifier,
                "object": object_id,
                "metrics": [{"key": "vector_length", "value": 45.2, "valueKind": "FLOAT"}],
            }
        },
        context_value=ctx,
    )
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    return result.data["assertStructureExists"]["structure"]["id"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_metrics_for_structure_reads_back_through_sql(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The metric written alongside a structure is retrievable by structure id."""
    structure_id = await _create_structure_row(api_schema, simple_api_context, test_graph, f"obj_{uuid.uuid4().hex[:8]}")

    result = await api_schema.execute(
        """
        query Metrics($structureId: ID!) {
            metricsForStructure(structureId: $structureId) { id value }
        }
        """,
        variable_values={"structureId": structure_id},
        context_value=simple_api_context,
    )

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    metrics = result.data["metricsForStructure"]
    assert [m["value"] for m in metrics] == [45.2]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_link_structure_to_entity_records_the_claim(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The mutation exists, writes an evidence link, and is readable back.

    M1's exit criteria name this mutation explicitly. Without this test the
    controller method was dead code carrying a docstring that claimed otherwise.
    """
    object_id = f"obj_{uuid.uuid4().hex[:8]}"
    await _create_structure_row(api_schema, simple_api_context, test_graph, object_id)

    category = await core_models.EntityCategory.objects.filter(graph=test_graph).afirst()
    assert category is not None, "The bio schema must materialize at least one entity category"

    created = await api_schema.execute(
        """
        mutation CreateEntity($input: AssertEntityExistsInput!) {
            assertEntityExists(input: $input) { instance { id } }
        }
        """,
        variable_values={"input": {"term": category.key}},
        context_value=simple_api_context,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    entity_id = created.data["assertEntityExists"]["instance"]["id"]

    linked = await api_schema.execute(
        """
        mutation Link($input: AssertInformsInput!) {
            assertInforms(input: $input) {
                assertion { id }
                link { id kind sourceRef targetRef }
            }
        }
        """,
        variable_values={
            "input": {
                "structureIdentifier": "roi_test",
                "structureObject": object_id,
                "entityId": entity_id,
            }
        },
        context_value=simple_api_context,
    )

    assert linked.errors is None, f"GraphQL errors: {linked.errors}"

    # The payload reports the **link**, not the structure. This act resolves a
    # structure that already exists and records an INFORMS claim about it, so
    # returning `structure` named the one thing the write did not produce and left
    # the claim it did produce unaddressable — which is what `description(id:)`
    # reads back.
    claim = linked.data["assertInforms"]["link"]
    assert claim["kind"] == "INFORMS", f"Expected an INFORMS claim, got {claim['kind']}"
    assert claim["targetRef"] == entity_id, "The claim should point at the entity it informs"
    assert linked.data["assertInforms"]["assertion"]["id"], "The act should be on the record"

    # And the link is readable from the other end.
    informing = await api_schema.execute(
        """
        query Informing($entityId: String!) {
            informingStructures(entityId: $entityId) { id object }
        }
        """,
        variable_values={"entityId": entity_id},
        context_value=simple_api_context,
    )

    assert informing.errors is None, f"GraphQL errors: {informing.errors}"
    assert [s["object"] for s in informing.data["informingStructures"]] == [object_id]
