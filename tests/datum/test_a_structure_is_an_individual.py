"""A structure is an individual with an external identity (RFC 0023, C6).

Its existence has a standing, the folds honour it, and agreeing that it exists
is countable — the three things a datum-as-row could not do. Its `(identifier,
object)` is the identity; superseding the object is a claim about the same
individual, not a new one.
"""

import uuid
import pytest
from asgiref.sync import sync_to_async
from evidence import models as evidence_models
from tests.support import claims, drawing, reads, sdl, writes
from django.db import IntegrityError, transaction
from authentikate.models import Organization
import kante
from kante.context import HttpContext
from core import models as core_models
from evidence import claims as claims_module
from graph_engine import input_models as models
from graph_engine.materialize import materialize


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


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_retracting_a_datum_stops_its_evidence_counting(api_schema, simple_api_context, test_graph) -> None:
    """The datum's standing is honoured by the fold: retract it and the derived
    value it fed is refolded without it; attest it and the value returns. Its
    metric claims are untouched either way."""
    object_id = f"roi-{uuid.uuid4().hex[:8]}"
    entity = await _entity_with_roi(api_schema, simple_api_context, object_id, 30.0)
    assert await reads.property_of(api_schema, simple_api_context, test_graph, entity, "avg_length") == pytest.approx(30.0)
    structure = await _structure_id(api_schema, simple_api_context, object_id)

    retracted = await api_schema.execute("mutation R($input: RetractStructureInput!) { retractStructure(input: $input) { assertion { id } } }", variable_values={"input": {"id": structure}}, context_value=simple_api_context)
    assert retracted.errors is None, f"GraphQL errors: {retracted.errors}"
    assert await reads.property_of(api_schema, simple_api_context, test_graph, entity, "avg_length") is None, "a retracted datum informs nothing"

    metrics = await sync_to_async(lambda: evidence_models.Metric.all_objects.filter(structure_id=structure).count())()
    assert metrics == 1, "the metric claim is on the record, untouched"

    attested = await api_schema.execute("mutation A($input: AttestStructureInput!) { attestStructure(input: $input) { assertion { id } } }", variable_values={"input": {"id": structure}}, context_value=simple_api_context)
    assert attested.errors is None, f"GraphQL errors: {attested.errors}"
    assert await reads.property_of(api_schema, simple_api_context, test_graph, entity, "avg_length") == pytest.approx(30.0), "attested, it counts again"


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
    assert await reads.property_of(api_schema, simple_api_context, test_graph, entity, "avg_length") is None


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
    assert await reads.property_of(api_schema, simple_api_context, test_graph, entity, "avg_length") == pytest.approx(12.0)

    retracted = await api_schema.execute("mutation R($input: RetractLinksInput!) { retractLinks(input: $input) { assertion { id } } }", variable_values={"input": {"ids": [measurement]}}, context_value=simple_api_context)
    assert retracted.errors is None, f"GraphQL errors: {retracted.errors}"

    @sync_to_async
    def standings() -> dict[str, list[bool]]:
        rows = evidence_models.Link.all_objects.filter(source_ref=structure, target_ref=entity, kind__in=[evidence_models.Link.Kind.MEASUREMENT, evidence_models.Link.Kind.INFORMS])
        return {str(row.kind): [s.stands for s in evidence_models.Standing.all_objects.filter(target_type="link", target_id=str(row.pk))] for row in rows}

    assert await standings() == {str(evidence_models.Link.Kind.MEASUREMENT): [False], str(evidence_models.Link.Kind.INFORMS): [False]}
    assert await reads.property_of(api_schema, simple_api_context, test_graph, entity, "avg_length") is None


def test_same_object_from_two_projections_is_one_row(organization: Organization, roi_category_a: evidence_models.StructureKind, roi_category_b: evidence_models.StructureKind, assertion: evidence_models.Assertion) -> None:
    """The headline: two graphs, one structure.

    The categories differ — they are still graph-scoped at this point — but
    identity is `(organization, identifier, object)`, so the second write is a
    constraint violation rather than a duplicate.
    """
    evidence_models.Structure.objects.create_for_organization(
        organization=organization,
        kind=roi_category_a,
        identifier="@mikro/roi",
        object="roi-42",
        assertion=assertion,
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        evidence_models.Structure.objects.create_for_organization(
            organization=organization,
            kind=roi_category_b,
            identifier="@mikro/roi",
            object="roi-42",
            assertion=assertion,
        )

    assert evidence_models.Structure.objects.for_organization(organization).count() == 1


def test_different_objects_are_different_structures(organization: Organization, roi_category_a: evidence_models.StructureKind, assertion: evidence_models.Assertion) -> None:
    """Identity is per external object, not per identifier."""
    for object_id in ("roi-1", "roi-2"):
        evidence_models.Structure.objects.create_for_organization(
            organization=organization,
            kind=roi_category_a,
            identifier="@mikro/roi",
            object=object_id,
            assertion=assertion,
        )

    assert evidence_models.Structure.objects.for_organization(organization).count() == 2


def test_different_identifiers_over_the_same_object_are_distinct(organization: Organization, roi_category_a: evidence_models.StructureKind, assertion: evidence_models.Assertion) -> None:
    """An image and an ROI can share an id string without being the same thing.

    `object` is only unique within an `identifier` namespace, which is why both
    columns are in the constraint.
    """
    evidence_models.Structure.objects.create_for_organization(
        organization=organization,
        kind=roi_category_a,
        identifier="@mikro/roi",
        object="7",
        assertion=assertion,
    )
    evidence_models.Structure.objects.create_for_organization(
        organization=organization,
        kind=roi_category_a,
        identifier="@mikro/image",
        object="7",
        assertion=assertion,
    )

    assert evidence_models.Structure.objects.for_organization(organization).count() == 2


def test_dedup_does_not_span_organizations(organization: Organization, other_organization: Organization, roi_category_a: evidence_models.StructureKind, assertion: evidence_models.Assertion) -> None:
    """Two tenants may each hold a structure for the same object id.

    They are not the same datum — the id strings live in different namespaces —
    and collapsing them would be the leak, not the feature.
    """
    other_assertion = evidence_models.Assertion.objects.create_for_organization(
        organization=other_organization,
        subject="tester",
        app_id="pytest",
        asserted_at=assertion.asserted_at,
    )

    for org, assertion_row in ((organization, assertion), (other_organization, other_assertion)):
        evidence_models.Structure.objects.create_for_organization(
            organization=org,
            kind=roi_category_a,
            identifier="@mikro/roi",
            object="roi-42",
            assertion=assertion_row,
        )

    assert evidence_models.Structure.objects.for_organization(organization).count() == 1
    assert evidence_models.Structure.objects.for_organization(other_organization).count() == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_structure(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
):
    category = await claims.ensure_kind(test_graph)
    object_id = f"obj_{uuid.uuid4().hex[:8]}"

    mutation = """
        mutation CreateStructure($input: AssertStructureExistsInput!) {
            assertStructureExists(input: $input) { structure { id object } }
        }
    """

    result = await api_schema.execute(
        mutation,
        variable_values={
            "input": {
                "identifier": category.identifier,
                "object": object_id,
                "metrics": [],
            }
        },
        context_value=simple_api_context,
    )

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data is not None
    assert result.data["assertStructureExists"]["structure"]["id"]
    assert result.data["assertStructureExists"]["structure"]["object"] == object_id


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_supersede_structure_keeps_the_individual(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
):
    category = await claims.ensure_kind(test_graph)
    object_id = f"obj_{uuid.uuid4().hex[:8]}"
    updated_object_id = f"obj_{uuid.uuid4().hex[:8]}"

    create_mutation = """
        mutation CreateStructure($input: AssertStructureExistsInput!) {
            assertStructureExists(input: $input) { structure { id object } }
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
    structure_id = create_result.data["assertStructureExists"]["structure"]["id"]

    update_mutation = """
        mutation UpdateStructure($input: RecordMetricsInput!) {
            recordMetrics(input: $input) { structure { id object } }
        }
    """

    # A structure's (identifier, object) is its identity in the evidence base, so
    # repointing `object` is rejected rather than silently creating a second
    # identity or violating the uniqueness constraint. This test previously
    # asserted the opposite; the in-place `SET s.object = $obj` it exercised
    # no longer exists.
    reidentify_result = await api_schema.execute(
        update_mutation,
        variable_values={
            "input": {
                "id": structure_id,
                "object": updated_object_id,
                "metrics": [],
            }
        },
        context_value=simple_api_context,
    )

    assert reidentify_result.errors is not None, "Repointing a structure's object must be rejected"
    assert "immutable" in str(reidentify_result.errors[0])

    # What update *is* for: appending measurements to an existing structure.
    update_result = await api_schema.execute(
        update_mutation,
        variable_values={
            "input": {
                "id": structure_id,
                "object": object_id,
                "metrics": [{"key": "vector_length", "value": 42.0, "valueKind": "FLOAT"}],
            }
        },
        context_value=simple_api_context,
    )

    assert update_result.errors is None, f"GraphQL errors: {update_result.errors}"
    assert update_result.data is not None
    assert update_result.data["recordMetrics"]["structure"]["id"] == structure_id
    assert update_result.data["recordMetrics"]["structure"]["object"] == object_id


@pytest.fixture(scope="session")
def edge_schema() -> models.GraphDefinitionInput:
    """A schema that declares the two edge kinds the bio schema leaves out.

    `MEASURES` runs from an ROI to an AIS, and AIS carries a MEAN over
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


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_structure_relation_is_an_evidence_row_with_no_projection(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    edge_graph: core_models.Graph,
    table_projector,
) -> None:
    """The claim is recorded, addressed by its own id, and draws no edge."""
    category = await core_models.StructureRelationCategory.objects.filter(graph=edge_graph, key="CONTAINS").afirst()
    assert category is not None, "The schema declares a CONTAINS structure relation"

    source = await writes.create_structure(api_schema, simple_api_context)
    target = await writes.create_structure(api_schema, simple_api_context)

    created = await api_schema.execute(
        writes.ASSERT_STRUCTURE_RELATION,
        variable_values={"input": {"term": category.key, "sourceId": source, "targetId": target}},
        context_value=simple_api_context,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    payload = created.data["assertStructureRelationExists"]["link"]

    assert payload["sourceRef"] == source, "Endpoints are named the way evidence names them — opaque refs"
    assert payload["targetRef"] == target

    # Resolved through the union, and dispatched on `kind` rather than on the ref:
    # every ref is a bare uuid, so nothing about one says which table it names. A
    # structure relation runs structure → structure, and this is what proves the
    # table in `api/types.py::_ENDPOINT_TABLES` agrees with what the writer wrote.
    assert payload["source"]["id"] == source, "The structure this relation runs from"
    assert payload["target"]["id"] == target, "and the one it runs to"
    assert payload["source"]["object"], "resolved as a real structure, not a stub"

    @sync_to_async
    def links_and_edges() -> tuple[int, int]:
        links = evidence_models.Link.objects.for_organization(edge_graph.organization).filter(kind=evidence_models.Link.Kind.STRUCTURE_RELATION)
        return links.count(), drawing.edge_count(edge_graph, category.age_name)

    link_count, edge_count = await links_and_edges()
    assert link_count == 1, "The claim must be recorded as evidence"
    assert edge_count == 0, "Structures are not vertices, so there is nothing to draw an edge between"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_retracting_a_structure_relation_is_a_standing(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    edge_graph: core_models.Graph,
) -> None:
    """Retraction never deletes. This whole path previously raised AttributeError."""
    category = await core_models.StructureRelationCategory.objects.filter(graph=edge_graph, key="CONTAINS").afirst()
    source = await writes.create_structure(api_schema, simple_api_context)
    target = await writes.create_structure(api_schema, simple_api_context)

    created = await api_schema.execute(
        writes.ASSERT_STRUCTURE_RELATION,
        variable_values={"input": {"term": category.key, "sourceId": source, "targetId": target}},
        context_value=simple_api_context,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    relation_id = created.data["assertStructureRelationExists"]["link"]["id"]

    archived = await api_schema.execute(writes.RETRACT_STRUCTURE_RELATION, variable_values={"input": {"id": relation_id}}, context_value=simple_api_context)
    assert archived.errors is None, f"GraphQL errors: {archived.errors}"

    @sync_to_async
    def state() -> tuple[str, int]:
        link = evidence_models.Link.all_objects.get(pk=relation_id)
        events = evidence_models.Standing.objects.for_organization(edge_graph.organization).filter(target_type="link", target_id=relation_id)
        return claims_module.current(link.organization, "link", link.pk), events.count()

    status, standing_rows = await state()
    assert status == False
    assert standing_rows == 1, "The positions are the authority; the cached status is a projection of them"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_structure_relation_supersede_and_retract_reach_the_row(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    edge_graph: core_models.Graph,
) -> None:
    """The resolvers must address a UUID-keyed row, not a composite graph id.

    `extract_node_id` int-casts everything after the first hyphen, so the old
    composite scheme could not name one of these at all — reaching the row is the
    thing worth asserting, and it is what the whole row-backed edge surface is
    for.
    """
    category = await core_models.StructureRelationCategory.objects.filter(graph=edge_graph, key="CONTAINS").afirst()
    source = await writes.create_structure(api_schema, simple_api_context)
    target = await writes.create_structure(api_schema, simple_api_context)

    created = await api_schema.execute(
        writes.ASSERT_STRUCTURE_RELATION,
        variable_values={"input": {"term": category.key, "sourceId": source, "targetId": target}},
        context_value=simple_api_context,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    original = created.data["assertStructureRelationExists"]["link"]["id"]

    updated = await api_schema.execute(
        writes.SUPERSEDE_STRUCTURE_RELATION,
        variable_values={"input": {"id": original, "sourceId": source, "targetId": target}},
        context_value=simple_api_context,
    )
    assert updated.errors is None, f"GraphQL errors: {updated.errors}"
    replacement = updated.data["supersedeStructureRelation"]["link"]["id"]
    assert replacement != original, "An update supersedes a claim rather than editing it"

    @sync_to_async
    def statuses() -> tuple[str, str]:
        links = evidence_models.Link.all_objects
        organization = links.get(pk=original).organization
        return claims_module.current(organization, "link", original), claims_module.current(organization, "link", replacement)

    original_status, replacement_status = await statuses()
    assert original_status == False
    assert replacement_status == True

    archived = await api_schema.execute(writes.RETRACT_STRUCTURE_RELATION, variable_values={"input": {"id": replacement}}, context_value=simple_api_context)
    assert archived.errors is None, f"GraphQL errors: {archived.errors}"

    @sync_to_async
    def surviving_status() -> str:
        link = evidence_models.Link.all_objects.get(pk=replacement)
        return claims_module.current(link.organization, "link", link.pk)

    assert await surviving_status() == False, "Retraction keeps the row and marks it"


def test_a_datum_is_claimed_never_ensured() -> None:
    """C6: a structure is claimed to exist like any individual (`assertStructureExists`);
    there is no `ensureStructure`, which would have made it an upsert with no act."""
    fields = sdl.mutation_fields()
    assert "assertStructureExists" in fields
    assert "ensureStructure" not in fields
