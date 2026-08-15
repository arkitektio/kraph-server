"""Structure relations and measurements are evidence rows and nothing else.

Both have a structure at one end, and structures stopped being AGE vertices in
M1 — so neither has an edge to draw. That is not a gap in the projection: both
endpoints of a structure relation are organization-scoped, so keeping the claim
in one graph's projection would put it in the wrong place entirely.

What that costs is the composite `{graph}-{vertex_id}` identifier, which cannot
name a row. These edges are addressed by their `Link` primary key instead, the
same way structures already are. `graphId` is null for them rather than `0`,
because every unprojected edge would otherwise report the same id — a collision
dressed up as an identifier.

The measurement tests carry the load-bearing claim: a measurement writes the
plain INFORMS link alongside its typed one, because `dirty()` matches on
`kind=INFORMS`. A measurement that skipped it would record the claim and
silently never roll its metrics up.
"""

import uuid

import kante
import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext

from core import models as core_models
from evidence import claims as claims_module
from evidence import models as evidence_models
from graph_engine import input_models as models
from graph_engine.materialize import materialize

CREATE_STRUCTURE = """
    mutation CreateStructure($input: AssertStructureExistsInput!) {
        assertStructureExists(input: $input) { structure { id } }
    }
"""

CREATE_ENTITY = """
    mutation CreateEntity($input: AssertEntityExistsInput!) {
        assertEntityExists(input: $input) { entity { id } }
    }
"""

CREATE_STRUCTURE_RELATION = """
    mutation CreateStructureRelation($input: AssertStructureRelationExistsInput!) {
        assertStructureRelationExists(input: $input) {
            structureRelation { id graphId sourceId targetId source { id object } target { id object } }
        }
    }
"""

ARCHIVE_STRUCTURE_RELATION = """
    mutation ArchiveStructureRelation($input: RetractStructureRelationInput!) {
        retractStructureRelation(input: $input) { structureRelation { id } }
    }
"""

UPDATE_STRUCTURE_RELATION = """
    mutation UpdateStructureRelation($input: UpdateStructureRelationInput!) {
        updateStructureRelation(input: $input) { structureRelation { id } }
    }
"""

CREATE_MEASUREMENT = """
    mutation CreateMeasurement($input: AssertMeasurementExistsInput!) {
        assertMeasurementExists(input: $input) {
            measurement { id graphId source { id object } target { id } }
        }
    }
"""

ENTITY_PROPERTIES = """
    query Entity($id: GraphID!) {
        node(id: $id) {
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
def edge_graph(transactional_db, age_engine, edge_schema, authenticated_context) -> core_models.Graph:
    request = authenticated_context.request
    return materialize(
        edge_schema,
        age_engine,
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
    return created.data["assertEntityExists"]["entity"]["id"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_structure_relation_is_an_evidence_row_with_no_projection(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    edge_graph: core_models.Graph,
    age_engine,
) -> None:
    """The claim is recorded, addressed by its own id, and draws no edge."""
    category = await core_models.StructureRelationCategory.objects.filter(graph=edge_graph, key="CONTAINS").afirst()
    assert category is not None, "The schema declares a CONTAINS structure relation"

    source = await _structure(api_schema, simple_api_context)
    target = await _structure(api_schema, simple_api_context)

    created = await api_schema.execute(
        CREATE_STRUCTURE_RELATION,
        variable_values={"input": {"term": category.key, "sourceId": source, "targetId": target}},
        context_value=simple_api_context,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    payload = created.data["assertStructureRelationExists"]["structureRelation"]

    assert payload["graphId"] is None, "An unprojected edge has no AGE id, and 0 would collide across every one of them"
    assert payload["sourceId"] == source, "Endpoints are named the way evidence names them"
    assert payload["targetId"] == target

    # `source`/`target` were `raise NotImplementedError` on every edge type while
    # being **non-null** in the SDL, so selecting either was a guaranteed error on
    # a query the schema advertised as valid. They resolve the endpoint through
    # the authorizing controller path, so this also exercises the tenancy check —
    # `get_structure_by_id` skips it entirely when handed no `info`.
    assert payload["source"]["id"] == source, "The structure this relation runs from"
    assert payload["target"]["id"] == target, "and the one it runs to"
    assert payload["source"]["object"], "resolved as a real structure, not a stub"

    @sync_to_async
    def links_and_edges() -> tuple[int, int]:
        links = evidence_models.Link.objects.for_organization(edge_graph.organization).filter(kind=evidence_models.Link.Kind.STRUCTURE_RELATION)
        rows = age_engine.execute(edge_graph, f"MATCH ()-[r:{category.age_name}]->() RETURN count(r) as c", {})
        return links.count(), int(rows[0]["c"]) if rows else 0

    link_count, edge_count = await links_and_edges()
    assert link_count == 1, "The claim must be recorded as evidence"
    assert edge_count == 0, "Structures are not vertices, so there is nothing to draw an edge between"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_archiving_a_structure_relation_is_a_lifecycle_row(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    edge_graph: core_models.Graph,
) -> None:
    """Retraction never deletes. This whole path previously raised AttributeError."""
    category = await core_models.StructureRelationCategory.objects.filter(graph=edge_graph, key="CONTAINS").afirst()
    source = await _structure(api_schema, simple_api_context)
    target = await _structure(api_schema, simple_api_context)

    created = await api_schema.execute(
        CREATE_STRUCTURE_RELATION,
        variable_values={"input": {"term": category.key, "sourceId": source, "targetId": target}},
        context_value=simple_api_context,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    relation_id = created.data["assertStructureRelationExists"]["structureRelation"]["id"]

    archived = await api_schema.execute(ARCHIVE_STRUCTURE_RELATION, variable_values={"input": {"id": relation_id}}, context_value=simple_api_context)
    assert archived.errors is None, f"GraphQL errors: {archived.errors}"

    @sync_to_async
    def state() -> tuple[str, int]:
        link = evidence_models.Link.all_objects.get(pk=relation_id)
        events = evidence_models.Claim.objects.for_organization(edge_graph.organization).filter(target_type="link", target_id=relation_id)
        return claims_module.current(link.organization, "link", link.pk), events.count()

    status, lifecycle_rows = await state()
    assert status == False
    assert lifecycle_rows == 1, "The lifecycle log is the authority; the cached status is a projection of it"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_structure_relation_update_and_archive_reach_the_row(
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
    source = await _structure(api_schema, simple_api_context)
    target = await _structure(api_schema, simple_api_context)

    created = await api_schema.execute(
        CREATE_STRUCTURE_RELATION,
        variable_values={"input": {"term": category.key, "sourceId": source, "targetId": target}},
        context_value=simple_api_context,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    original = created.data["assertStructureRelationExists"]["structureRelation"]["id"]

    updated = await api_schema.execute(
        UPDATE_STRUCTURE_RELATION,
        variable_values={"input": {"id": original, "sourceId": source, "targetId": target}},
        context_value=simple_api_context,
    )
    assert updated.errors is None, f"GraphQL errors: {updated.errors}"
    replacement = updated.data["updateStructureRelation"]["structureRelation"]["id"]
    assert replacement != original, "An update supersedes a claim rather than editing it"

    @sync_to_async
    def statuses() -> tuple[str, str]:
        links = evidence_models.Link.all_objects
        organization = links.get(pk=original).organization
        return claims_module.current(organization, "link", original), claims_module.current(organization, "link", replacement)

    original_status, replacement_status = await statuses()
    assert original_status == False
    assert replacement_status == True

    archived = await api_schema.execute(ARCHIVE_STRUCTURE_RELATION, variable_values={"input": {"id": replacement}}, context_value=simple_api_context)
    assert archived.errors is None, f"GraphQL errors: {archived.errors}"

    @sync_to_async
    def surviving_status() -> str:
        link = evidence_models.Link.all_objects.get(pk=replacement)
        return claims_module.current(link.organization, "link", link.pk)

    assert await surviving_status() == False, "Retraction keeps the row and marks it"


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

    before = await api_schema.execute(ENTITY_PROPERTIES, variable_values={"id": entity}, context_value=simple_api_context)
    assert before.errors is None, f"GraphQL errors: {before.errors}"
    assert before.data["node"]["properties"].get("avg_length") is None, "Nothing may derive before the measurement is asserted"

    created = await api_schema.execute(
        CREATE_MEASUREMENT,
        variable_values={"input": {"term": category.key, "sourceId": structure, "targetId": entity}},
        context_value=simple_api_context,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    measurement = created.data["assertMeasurementExists"]["measurement"]
    assert measurement["graphId"] is None, "A measurement has a structure at one end, so it has no projected edge"

    # A measurement runs structure → entity, and both ends resolve. `source` and
    # `target` were stubs raising on a non-null field until now.
    assert measurement["source"]["object"], "The structure that did the measuring"
    assert measurement["target"]["id"], "and the entity it is about"

    after = await api_schema.execute(ENTITY_PROPERTIES, variable_values={"id": entity}, context_value=simple_api_context)
    assert after.errors is None, f"GraphQL errors: {after.errors}"
    assert after.data["node"]["properties"].get("avg_length") == pytest.approx(42.0), "Asserting a measurement must move the derived value"

    @sync_to_async
    def link_kinds() -> list[str]:
        from evidence import selector as selector_module

        return sorted(
            evidence_models.Link.objects.for_organization(edge_graph.organization)
            .filter(target_ref__in=selector_module.node_ids_for(edge_graph))
            .values_list("kind", flat=True)
        )

    kinds = await link_kinds()
    assert evidence_models.Link.Kind.MEASUREMENT in kinds, "The typed claim names which term of the schema was asserted"
    assert evidence_models.Link.Kind.INFORMS in kinds, "The plain claim is what dirty() matches, and without it nothing rolls up"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_resolving_an_edge_endpoint_checks_the_endpoint_s_own_tenant(
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Making `source`/`target` work must not open a way around tenancy.

    Those fields were `raise NotImplementedError`, so implementing them meant
    reaching structures and nodes by bare primary key. `get_structure_by_id`
    takes `info` as an **optional** argument, and `_assert_can_access` returns
    early when it is `None` — so a resolver that forgot to pass it would resolve
    any tenant's structure through any edge id.

    Driven at the helper rather than through GraphQL, because the guard under
    test is the helper's, and a full round trip would need a second graph, a
    second membership and a second schema just to reach it.
    """
    from asgiref.sync import sync_to_async
    from authentikate.models import Organization

    from api import types as api_types
    from evidence import writer as evidence_writer

    @sync_to_async
    def foreign_structure() -> str:
        other, _ = Organization.objects.get_or_create(slug="an-unrelated-tenant")
        assertion = evidence_writer.create_assertion(other, subject="someone-else", app_id="elsewhere")
        kind = evidence_writer.ensure_structure_kind(other, "@mikro/roi")
        structure = evidence_writer.ensure_structure(other, kind=kind, object="not-yours", assertion=assertion)
        return str(structure.pk)

    ref = await foreign_structure()

    class _Info:
        """Just enough of `Info` for the guard, which reads `context.request.user`."""

        context = simple_api_context

    with pytest.raises(PermissionError):
        await api_types._endpoint_structure(ref, _Info())
