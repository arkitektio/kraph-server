"""Standing is a claim on a claim (A3).

Every claim kind that can be retracted can be re-attested, and both are
positions on the record — the claim row survives untouched, the positions are
readable newest first, and `CurrentStanding` is the cached fold over them.

History: `attest*` used to exist for four of ten claim kinds, so a retraction
of the other six was one-way through the API.
"""

from __future__ import annotations
import uuid
import kante
import pytest
from kante.context import HttpContext
from core import models as core_models
from evidence import models as evidence_models
from evidence import claims as claims_module
from evidence import writer
from tests.support import claims, reads, writes
from datetime import datetime, timezone


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


@pytest.mark.django_db(transaction=True)
def test_the_cache_agrees_with_the_fold(organization, roi_kind) -> None:
    """`CurrentStanding` must say what `claims.stands_for` says.

    Nothing asserted this while the cache lived on the log row, which is how the
    two were free to drift — a queryset `.update(stands=False)` wrote no claim at
    all, and no test would have noticed.
    """
    minting = writer.create_assertion(organization, subject="minter", app_id="app")
    structures = [writer.ensure_structure(organization, kind=roi_kind, object=f"roi-agree-{index}", assertion=minting) for index in range(4)]

    writer.retract(organization, structures[1], writer.create_assertion(organization, subject="a", app_id="app"))
    writer.retract(organization, structures[2], writer.create_assertion(organization, subject="b", app_id="app"))
    writer.attest(organization, structures[2], writer.create_assertion(organization, subject="c", app_id="app"))

    ids = [str(structure.pk) for structure in structures]
    folded = claims_module.stands_for(organization, "structure", ids)
    cached = {target_id: claims_module.current(organization, "structure", target_id) for target_id in ids}

    assert cached == folded, "The cache and the fold must be the same answer"
    assert folded[ids[1]] is False
    assert folded[ids[2]] is True, "Re-attesting after a retraction restores it — and both claims stay on the record"


@pytest.mark.django_db(transaction=True)
def test_a_rebuild_reproduces_the_cache(organization, roi_kind) -> None:
    """Drop the projection, replay it, and nothing changes.

    The honesty test for `CurrentStanding`, and the reason `rebuild` folds it before
    it draws anything: every "which of these still count" narrowing reads it, so
    replaying against an unproved cache would prove nothing.
    """
    minting = writer.create_assertion(organization, subject="minter", app_id="app")
    structures = [writer.ensure_structure(organization, kind=roi_kind, object=f"roi-replay-{index}", assertion=minting) for index in range(3)]
    writer.retract(organization, structures[0], writer.create_assertion(organization, subject="a", app_id="app"))

    before = {str(row.target_id): row.stands for row in evidence_models.CurrentStanding.objects.for_organization(organization)}

    claims_module.refold_current(organization)

    after = {str(row.target_id): row.stands for row in evidence_models.CurrentStanding.objects.for_organization(organization)}
    assert after == before, "A replay of the projection must reproduce it exactly"


@pytest.mark.django_db(transaction=True)
def test_the_standing_cache_is_total(test_graph) -> None:
    """RFC 0024: the trust-everyone fold caches an instance's standing like any
    claim's. What a view says is still its category's rule."""
    from evidence import claims as claims_module

    org = test_graph.organization
    node = claims.mint(org, "AIS", "peter")
    assert claims_module.current(org, "node", node) is True
    writer.retract(org, evidence_models.Instance.all_objects.get(pk=node), writer.create_assertion(org, subject="peter", app_id="pytest"))
    assert claims_module.current(org, "node", node) is False
    assert not claims_module.standing(evidence_models.Instance.objects.for_organization(org).filter(pk=node), "node").exists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_retraction_shows_up_as_a_standing(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """ "Does it still hold" is answerable from the claim, and disagreement is visible.

    The positions are reported and the folding is left to the reader: the
    organization-grain fold is `CurrentStanding` (RFC 0024), and whether a *view*
    holds the node is its category's rule, reported as `drawings`. That is why there
    is no `stands` field beside this list.
    """
    entity_id = await writes.create_entity(api_schema, simple_api_context, "AIS")

    retracted = await api_schema.execute(
        writes.RETRACT_ENTITY,
        variable_values={"input": {"id": entity_id}},
        context_value=simple_api_context,
    )

    assert retracted.errors is None, f"GraphQL errors: {retracted.errors}"
    payload = retracted.data["retractEntity"]

    assert [row["stands"] for row in payload["instance"]["standings"]] == [False], "The retraction is on the record, newest first, with its own assertion"
    assert payload["drawings"] == [], "No view draws it any more"

    read = await api_schema.execute(reads.INSTANCE_STANDINGS, variable_values={"id": entity_id}, context_value=simple_api_context)
    assert read.errors is None, f"GraphQL errors: {read.errors}"
    assert [row["stands"] for row in read.data["instance"]["standings"]] == [False], "and the same answer is readable afterwards, without the write"
    assert read.data["instance"]["term"]["key"] == "AIS", "The claim outlives the drawing it lost"

    # **Then attest it again.** Both positions stay on the record and the newest is
    # first, by `(at, assertion.seq)` — there is no "reinstate" operation, only more
    # evidence, so the order is the whole answer.
    attested = await api_schema.execute(
        writes.ATTEST_ENTITY,
        variable_values={"input": {"id": entity_id}},
        context_value=simple_api_context,
    )
    assert attested.errors is None, f"GraphQL errors: {attested.errors}"
    claim = attested.data["attestEntity"]["instance"]

    assert [row["stands"] for row in claim["standings"]] == [True, False], "Newest first: it holds again, and the retraction is still on the record"
    assert attested.data["attestEntity"]["drawings"], "and the view that admits the word draws it again"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_retract_metric(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
):
    structure_id = await writes.create_structure(api_schema, simple_api_context, identifier="roi_test")

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
async def test_retracting_a_metric_twice_is_one_position(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
):
    structure_id = await writes.create_structure(api_schema, simple_api_context, identifier="roi_test")

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


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_retract_structure(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
):
    category = await claims.ensure_kind(test_graph)
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
    structure_id = create_result.data["assertStructureExists"]["structure"]["id"]

    # `deleteStructure` is gone: it cascaded away every metric describing the
    # structure, destroying the record of what derived values were computed from.
    # Archiving retracts the structure and keeps that record.
    archive_mutation = """
        mutation ArchiveStructure($input: RetractStructureInput!) {
            retractStructure(input: $input) { structure { id } }
        }
    """

    archive_result = await api_schema.execute(
        archive_mutation,
        variable_values={"input": {"id": structure_id}},
        context_value=simple_api_context,
    )

    assert archive_result.errors is None, f"GraphQL errors: {archive_result.errors}"
    assert archive_result.data["retractStructure"]["structure"]["id"] == structure_id

    # Archiving a structure that is not there reports it rather than succeeding
    # silently. Evidence rows have real primary keys, so saying so is possible —
    # the old Cypher `MATCH ... DETACH DELETE` was a no-op on a missing node and
    # a caller could not tell a real delete from a typo in the id.
    missing = await api_schema.execute(
        archive_mutation,
        variable_values={"input": {"id": "00000000-0000-0000-0000-000000000000"}},
        context_value=simple_api_context,
    )

    assert missing.errors is not None, "Archiving a missing structure must report it"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_retracting_an_entity_returns_it_from_the_log(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
):
    """The mutation answers from the evidence, because the vertex is gone.

    `archiveEntity` returns `Entity!`, and by the time it returns there is no
    vertex left to read — so the value is built from the `Node` row. The id and
    the kind still resolve, because both are properties of the evidence rather
    than of the projection.

    History: this used to also assert `graphId is None` and `graph is None`. Both
    fields are gone: `graphId` was a drawn vertex id, reassigned by every
    reproject, and `graph` asked which single graph a node belongs to when a node
    may be drawn by several. Where a claim stands is `drawings`, asserted below.
    """
    entity_category = await test_graph.aget_entity_def("AIS")

    create_mutation = """
        mutation CreateEntity($input: AssertEntityExistsInput!) {
            assertEntityExists(input: $input) { instance { id kind term { key } } }
        }
    """

    create_result = await api_schema.execute(
        create_mutation,
        variable_values={
            "input": {
                "term": entity_category.key,
            }
        },
        context_value=simple_api_context,
    )

    assert create_result.errors is None, f"GraphQL errors: {create_result.errors}"
    assert create_result.data is not None
    entity_id = create_result.data["assertEntityExists"]["instance"]["id"]
    assert entity_id
    assert create_result.data["assertEntityExists"]["instance"]["term"]["key"] == "AIS"

    archive_mutation = """
        mutation RetractEntity($input: RetractEntityInput!) {
            retractEntity(input: $input) {
                assertion { id subject }
                instance { id kind term { key } }
                drawings { graph { id } }
            }
        }
    """

    archive_result = await api_schema.execute(
        archive_mutation,
        variable_values={"input": {"id": entity_id}},
        context_value=simple_api_context,
    )

    assert archive_result.errors is None, f"GraphQL errors: {archive_result.errors}"
    assert archive_result.data is not None
    payload = archive_result.data["retractEntity"]
    archived = payload["instance"]

    assert archived["id"] == entity_id, "The id is the entity's uuid and survives the projection it was removed from"
    assert archived["term"]["key"] == "AIS"

    # What a state flag used to say, said by the shape instead. The
    # field is gone: a node read out of a graph is one the evidence says exists,
    # so a flag beside it could only agree with its own presence, and a node with
    # no vertex was answering from the claims — two questions under one name.
    assert payload["drawings"] == [], "No view draws it any more, which is what retracting it means"
    assert payload["assertion"]["id"], "And the retraction is itself a claim, with an assertion behind it"


TREATMENT = datetime(2026, 6, 1, tzinfo=timezone.utc)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_retraction_may_say_when_it_took_effect(api_schema, simple_api_context) -> None:
    """`at` on a retract input is `Standing.at` — the cell died in June, whenever
    that was recorded."""
    ref = (await writes.execute(api_schema, simple_api_context, writes.ASSERT_ENTITY_OBSERVED, {"input": {"term": "Cell"}}))["assertEntityExists"]["instance"]["id"]
    data = await writes.execute(api_schema, simple_api_context, writes.RETRACT_ENTITY_AT, {"input": {"id": ref, "at": TREATMENT.isoformat()}})
    (standing,) = data["retractEntity"]["instance"]["standings"]
    assert standing["stands"] is False
    assert datetime.fromisoformat(standing["at"]) == TREATMENT
