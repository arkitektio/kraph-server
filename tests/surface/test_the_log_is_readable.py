"""The log is readable as a log (RFC 0020).

`Assertion` has been served as a row since the Cypher-backed `assertion(id:)` and
`assertions(graph:)` were deleted — reachable only from the payload of the write
that made it. These tests pin the three ways in: `assertions(filters:, pagination:)`
newest first, `assertion(id:)` with every claim the act recorded, and
`changes(afterSeq:, limit:)` — the forward feed, gated on the **committed horizon**
so a row whose transaction is still open cannot be skipped by a cursor that has
already moved past its `seq`.
"""

import uuid
from datetime import timedelta
import psycopg
import pytest
from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils import timezone
from evidence import writer


ASSERT_ENTITY = """
    mutation AssertEntityExists($input: AssertEntityExistsInput!) {
        assertEntityExists(input: $input) {
            assertion { id seq }
            instance { id }
        }
    }
"""
RETRACT_ENTITY = """
    mutation RetractEntity($input: RetractEntityInput!) {
        retractEntity(input: $input) { assertion { id seq } }
    }
"""
ASSERTIONS = """
    query Assertions($filters: AssertionFilter, $pagination: LogPaginationInput) {
        assertions(filters: $filters, pagination: $pagination) { id seq subject appId }
    }
"""
ASSERTION = """
    query Assertion($id: ID!) {
        assertion(id: $id) {
            id
            seq
            actionArgs
            instances { id term { key } }
            links { id kind }
            metrics { id }
            structures { id }
            standings { id stands target { __typename ... on Instance { id } ... on Link { id } } }
            comments { id }
        }
    }
"""
CHANGES = """
    query Changes($afterSeq: Int!, $limit: Int) {
        changes(afterSeq: $afterSeq, limit: $limit) {
            assertions { id seq }
            nextSeq
            horizon
        }
    }
"""
STANDINGS = """
    query Standings($id: ID, $filters: StandingFilter) {
        standings(id: $id, filters: $filters) {
            id
            stands
            target { __typename ... on Instance { id } ... on Link { id } }
        }
    }
"""
async def _execute(api_schema, ctx, document: str, variables: dict | None = None) -> dict:
    result = await api_schema.execute(document, variable_values=variables or {}, context_value=ctx)
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    return result.data
async def _assert_entity(api_schema, ctx, term: str = "AIS", evidence: list | None = None) -> dict:
    data = await _execute(api_schema, ctx, ASSERT_ENTITY, {"input": {"term": term, "supportingEvidence": evidence or []}})
    return data["assertEntityExists"]
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_assertions_lists_newest_first(api_schema, simple_api_context, test_graph) -> None:
    written = [await _assert_entity(api_schema, simple_api_context) for _ in range(3)]
    seqs = [entry["assertion"]["seq"] for entry in written]

    data = await _execute(api_schema, simple_api_context, ASSERTIONS)
    listed = [row["seq"] for row in data["assertions"]]

    assert listed[:3] == sorted(seqs, reverse=True), "the log reads newest first by default"
    assert listed == sorted(listed, reverse=True)
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_assertions_filters_by_who_and_when(api_schema, simple_api_context, test_graph) -> None:
    """Every filter narrows by a column of the act — nothing about what was claimed."""
    organization = simple_api_context.request._organization
    long_ago = timezone.now() - timedelta(days=400)
    old = await sync_to_async(writer.create_assertion)(organization, subject="pipeline-7", app_id="segmenter", action_id="run-42", asserted_at=long_ago)
    fresh = await _assert_entity(api_schema, simple_api_context)
    fresh_id = fresh["assertion"]["id"]

    by_subject = await _execute(api_schema, simple_api_context, ASSERTIONS, {"filters": {"subjects": ["pipeline-7"]}})
    assert [row["id"] for row in by_subject["assertions"]] == [str(old.pk)]

    by_app = await _execute(api_schema, simple_api_context, ASSERTIONS, {"filters": {"appIds": ["segmenter"]}})
    assert [row["id"] for row in by_app["assertions"]] == [str(old.pk)]

    by_action = await _execute(api_schema, simple_api_context, ASSERTIONS, {"filters": {"actionIds": ["run-42"]}})
    assert [row["id"] for row in by_action["assertions"]] == [str(old.pk)]

    since = await _execute(api_schema, simple_api_context, ASSERTIONS, {"filters": {"assertedSince": (timezone.now() - timedelta(days=1)).isoformat()}})
    since_ids = [row["id"] for row in since["assertions"]]
    assert fresh_id in since_ids and str(old.pk) not in since_ids

    before = await _execute(api_schema, simple_api_context, ASSERTIONS, {"filters": {"assertedBefore": (timezone.now() - timedelta(days=1)).isoformat()}})
    assert [row["id"] for row in before["assertions"]] == [str(old.pk)]

    after_seq = await _execute(api_schema, simple_api_context, ASSERTIONS, {"filters": {"seqAfter": old.seq}})
    after_ids = [row["id"] for row in after_seq["assertions"]]
    assert fresh_id in after_ids and str(old.pk) not in after_ids

    by_id = await _execute(api_schema, simple_api_context, ASSERTIONS, {"filters": {"ids": [fresh_id]}})
    assert [row["id"] for row in by_id["assertions"]] == [fresh_id]
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_assertions_pages(api_schema, simple_api_context, test_graph) -> None:
    for _ in range(4):
        await _assert_entity(api_schema, simple_api_context)

    everything = await _execute(api_schema, simple_api_context, ASSERTIONS)
    first = await _execute(api_schema, simple_api_context, ASSERTIONS, {"pagination": {"limit": 2}})
    second = await _execute(api_schema, simple_api_context, ASSERTIONS, {"pagination": {"limit": 2, "offset": 2}})

    assert [row["seq"] for row in first["assertions"]] == [row["seq"] for row in everything["assertions"]][:2]
    assert [row["seq"] for row in second["assertions"]] == [row["seq"] for row in everything["assertions"]][2:4]
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_assertion_lists_every_claim_the_act_recorded(api_schema, simple_api_context, test_graph) -> None:
    """One `assertEntityExists` with evidence is one act that writes four kinds of claim."""
    evidence = [{"identifier": "ROI", "object": f"roi_{uuid.uuid4().hex[:8]}", "metrics": [{"key": "vector_length", "value": 40.0, "valueKind": "FLOAT"}]}]
    written = await _assert_entity(api_schema, simple_api_context, evidence=evidence)
    assertion_id = written["assertion"]["id"]
    instance_id = written["instance"]["id"]

    data = await _execute(api_schema, simple_api_context, ASSERTION, {"id": assertion_id})
    act = data["assertion"]

    assert act["id"] == assertion_id
    assert [row["id"] for row in act["instances"]] == [instance_id]
    assert [row["term"]["key"] for row in act["instances"]] == ["AIS"]
    assert sorted(row["kind"] for row in act["links"]) == ["CLASSIFIES", "INFORMS"], "the word is a classification claim and the evidence informs the instance, both under the same assertion"
    assert len(act["metrics"]) == 1
    assert len(act["structures"]) == 1, "the structure was first introduced by this act"
    assert act["standings"] == []
    assert act["comments"] == []
    assert act["actionArgs"] == {}

    retracted = await _execute(api_schema, simple_api_context, RETRACT_ENTITY, {"input": {"id": instance_id}})
    retraction = await _execute(api_schema, simple_api_context, ASSERTION, {"id": retracted["retractEntity"]["assertion"]["id"]})

    assert retraction["assertion"]["instances"] == [], "a retraction claims nothing new — it takes a position"
    standings = retraction["assertion"]["standings"]
    assert len(standings) == 1
    assert standings[0]["stands"] is False
    assert standings[0]["target"] == {"__typename": "Instance", "id": instance_id}, "the position's target dispatches on `target_type`"
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_assertion_reports_the_arguments_the_action_ran_with(api_schema, simple_api_context, test_graph) -> None:
    organization = simple_api_context.request._organization
    row = await sync_to_async(writer.create_assertion)(organization, subject="1", app_id="test", action_args={"threshold": 0.5, "channels": [1, 2]})

    data = await _execute(api_schema, simple_api_context, ASSERTION, {"id": str(row.pk)})

    assert data["assertion"]["actionArgs"] == {"threshold": 0.5, "channels": [1, 2]}
def _raw_connection() -> psycopg.Connection:
    """A second session, outside Django's connection — the other writer."""
    db = settings.DATABASES["default"]
    return psycopg.connect(host=db["HOST"], port=db["PORT"], dbname=db["NAME"], user=db["USER"], password=db["PASSWORD"], autocommit=False)
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_standings_lists_positions_by_who_took_them(api_schema, simple_api_context, test_graph) -> None:
    written = await _assert_entity(api_schema, simple_api_context)
    instance_id = written["instance"]["id"]
    await _execute(api_schema, simple_api_context, RETRACT_ENTITY, {"input": {"id": instance_id}})

    organization = simple_api_context.request._organization
    stranger = await sync_to_async(writer.create_assertion)(organization, subject="stranger", app_id="test")
    await sync_to_async(writer.record_standing_for_ref)(organization, target_type="node", target_id=instance_id, stands=True, assertion=stranger)

    by_target = (await _execute(api_schema, simple_api_context, STANDINGS, {"id": instance_id}))["standings"]
    assert [row["stands"] for row in by_target] == [True, False], "newest first, both positions on the one claim"
    assert all(row["target"] == {"__typename": "Instance", "id": instance_id} for row in by_target)

    by_subject = (await _execute(api_schema, simple_api_context, STANDINGS, {"filters": {"subjects": ["stranger"]}}))["standings"]
    assert [row["stands"] for row in by_subject] == [True]

    retractions = (await _execute(api_schema, simple_api_context, STANDINGS, {"filters": {"stands": False}}))["standings"]
    assert [row["target"]["id"] for row in retractions] == [instance_id]

    on_links = (await _execute(api_schema, simple_api_context, STANDINGS, {"filters": {"targetType": "LINK"}}))["standings"]
    assert on_links == []
