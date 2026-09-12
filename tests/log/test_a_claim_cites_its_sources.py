"""A claim can cite the claims it came from (RFC 0017, A3).

`Link.Kind.DERIVED_FROM` runs from the new claim to the one it derives from,
and either end may be any claim row. It is written under the **same**
assertion as the claim it annotates, because "this, because of that" is one
act (A1). `supersedeMetricValue` cites the metric it replaces.
"""

import uuid

import pytest
from asgiref.sync import sync_to_async
from authentikate.models import Organization

from evidence import models as evidence_models
from tests.support import claims, writes

ASSERT_METRIC = """
    mutation M($input: AssertMetricValueInput!) {
        assertMetricValue(input: $input) { assertion { id } metric { id } }
    }
"""

ASSERT_ENTITY = """
    mutation E($input: AssertEntityExistsInput!) {
        assertEntityExists(input: $input) {
            assertion { id }
            instance {
                id
                derivedFrom { id kind assertion { id } target { __typename ... on Metric { id } ... on Instance { id } } }
            }
        }
    }
"""

ASSERT_RELATION = """
    mutation R($input: AssertRelationExistsInput!) {
        assertRelationExists(input: $input) {
            link { id derivedFrom { id target { __typename ... on Instance { id } ... on Link { id } ... on Metric { id } } } }
        }
    }
"""

SUPERSEDE = """
    mutation S($input: SupersedeMetricValueInput!) {
        supersedeMetricValue(input: $input) {
            assertion { id }
            metric { id derivedFrom { id assertion { id } target { __typename ... on Metric { id } } } }
        }
    }
"""

METRIC = """
    query M($id: ID!) {
        metric(id: $id) {
            id
            derivedFrom { id }
            derivations { id kind source { __typename ... on Instance { id } ... on Metric { id } ... on Link { id } } }
        }
    }
"""

INSTANCE = """
    query I($id: ID!) {
        instance(id: $id) {
            id
            derivedFrom { id target { __typename ... on Metric { id } } }
            derivations { id source { __typename ... on Link { id } ... on Instance { id } } }
        }
    }
"""

LINK = """
    query L($id: ID!) {
        link(id: $id) {
            id kind
            source { __typename ... on Instance { id } ... on Metric { id } }
            target { __typename ... on Instance { id } ... on Metric { id } }
        }
    }
"""

RETRACT_LINKS = """
    mutation X($input: RetractLinksInput!) {
        retractLinks(input: $input) { links { id kind } }
    }
"""


async def _metric(api_schema, ctx, value: float = 12.0) -> tuple[str, str]:
    data = await writes.execute(
        api_schema,
        ctx,
        ASSERT_METRIC,
        {"input": {"identifier": "@test/roi", "object": f"obj_{uuid.uuid4().hex[:6]}", "key": "area", "value": value, "valueKind": "FLOAT"}},
    )
    return data["assertMetricValue"]["metric"]["id"], data["assertMetricValue"]["assertion"]["id"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_claim_cites_the_claims_it_came_from(api_schema, simple_api_context, test_graph) -> None:
    """The citation is a link, readable from both ends, written under the citing claim's own assertion."""
    metric_id, _ = await _metric(api_schema, simple_api_context)

    asserted = (await writes.execute(api_schema, simple_api_context, ASSERT_ENTITY, {"input": {"term": "Cell", "derivedFrom": [metric_id]}}))["assertEntityExists"]
    instance = asserted["instance"]

    (citation,) = instance["derivedFrom"]
    assert citation["kind"] == "DERIVED_FROM"
    assert citation["target"] == {"__typename": "Metric", "id": metric_id}
    assert citation["assertion"]["id"] == asserted["assertion"]["id"], "one act: the claim and what it cites share an assertion"

    # The other direction, from the cited claim.
    metric = (await writes.execute(api_schema, simple_api_context, METRIC, {"id": metric_id}))["metric"]
    assert metric["derivedFrom"] == []
    (derivation,) = metric["derivations"]
    assert derivation["id"] == citation["id"]
    assert derivation["source"] == {"__typename": "Instance", "id": instance["id"]}

    # And the link itself resolves both ends by kind, never by the shape of a ref.
    link = (await writes.execute(api_schema, simple_api_context, LINK, {"id": citation["id"]}))["link"]
    assert link["source"] == {"__typename": "Instance", "id": instance["id"]}
    assert link["target"] == {"__typename": "Metric", "id": metric_id}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_claim_may_cite_several_claims_of_different_shapes(api_schema, simple_api_context, test_graph) -> None:
    metric_id, _ = await _metric(api_schema, simple_api_context)
    a = (await writes.execute(api_schema, simple_api_context, ASSERT_ENTITY, {"input": {"term": "Cell"}}))["assertEntityExists"]["instance"]
    b = (await writes.execute(api_schema, simple_api_context, ASSERT_ENTITY, {"input": {"term": "Cell"}}))["assertEntityExists"]["instance"]

    relation = (
        await writes.execute(
            api_schema,
            simple_api_context,
            ASSERT_RELATION,
            {"input": {"term": "IS_CONNECTED_TO", "sourceId": a["id"], "targetId": b["id"], "derivedFrom": [metric_id, a["id"]]}},
        )
    )["assertRelationExists"]["link"]

    cited = {(c["target"]["__typename"], c["target"]["id"]) for c in relation["derivedFrom"]}
    assert cited == {("Metric", metric_id), ("Instance", a["id"])}

    # A link can be cited too: an instance derived from the relation.
    c = (await writes.execute(api_schema, simple_api_context, ASSERT_ENTITY, {"input": {"term": "Cell", "derivedFrom": [relation["id"]]}}))["assertEntityExists"]["instance"]
    (citation,) = c["derivedFrom"]
    assert citation["target"]["__typename"] == "Link"

    instance_a = (await writes.execute(api_schema, simple_api_context, INSTANCE, {"id": a["id"]}))["instance"]
    assert [d["source"] for d in instance_a["derivations"]] == [{"__typename": "Link", "id": relation["id"]}]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_superseding_a_metric_cites_the_one_it_replaces(api_schema, simple_api_context, test_graph) -> None:
    """The correction and its original were tied only by sharing an assertion id; now the new value says so."""
    old_id, _ = await _metric(api_schema, simple_api_context, 12.0)

    superseded = (await writes.execute(api_schema, simple_api_context, SUPERSEDE, {"input": {"id": old_id, "key": "area", "value": 99.0, "valueKind": "FLOAT"}}))["supersedeMetricValue"]
    new = superseded["metric"]
    assert new["id"] != old_id

    (citation,) = new["derivedFrom"]
    assert citation["target"] == {"__typename": "Metric", "id": old_id}
    assert citation["assertion"]["id"] == superseded["assertion"]["id"], "cited under the corrective act itself"

    old = (await writes.execute(api_schema, simple_api_context, METRIC, {"id": old_id}))["metric"]
    assert [d["source"]["id"] for d in old["derivations"]] == [new["id"]]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_retracting_a_citation_removes_it_from_both_ends(api_schema, simple_api_context, test_graph) -> None:
    metric_id, _ = await _metric(api_schema, simple_api_context)
    instance = (await writes.execute(api_schema, simple_api_context, ASSERT_ENTITY, {"input": {"term": "Cell", "derivedFrom": [metric_id]}}))["assertEntityExists"]["instance"]
    (citation,) = instance["derivedFrom"]

    retracted = (await writes.execute(api_schema, simple_api_context, RETRACT_LINKS, {"input": {"ids": [citation["id"]]}}))["retractLinks"]
    assert retracted["links"] == [{"id": citation["id"], "kind": "DERIVED_FROM"}]

    assert (await writes.execute(api_schema, simple_api_context, INSTANCE, {"id": instance["id"]}))["instance"]["derivedFrom"] == []
    assert (await writes.execute(api_schema, simple_api_context, METRIC, {"id": metric_id}))["metric"]["derivations"] == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_citing_a_claim_that_does_not_exist_is_refused(api_schema, simple_api_context, test_graph) -> None:
    """Refused before anything is written: no instance, no assertion."""
    before = await evidence_models.Assertion.all_objects.acount()
    result = await api_schema.execute(ASSERT_ENTITY, variable_values={"input": {"term": "Cell", "derivedFrom": [str(uuid.uuid4())]}}, context_value=simple_api_context)
    assert result.errors is not None and "derivedFrom" in str(result.errors[0])
    assert await evidence_models.Assertion.all_objects.acount() == before


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_citing_another_organizations_claim_is_refused(api_schema, simple_api_context, test_graph) -> None:
    """A ref is a bare uuid, so the citation would otherwise cross the tenant boundary silently."""

    @sync_to_async
    def foreign_instance() -> str:
        org, _ = Organization.objects.get_or_create(slug="a_tenant_you_are_not_in")
        return claims.mint(org, "Cell", "stranger")

    foreign = await foreign_instance()
    result = await api_schema.execute(ASSERT_ENTITY, variable_values={"input": {"term": "Cell", "derivedFrom": [foreign]}}, context_value=simple_api_context)
    assert result.errors is not None and "derivedFrom" in str(result.errors[0])
    assert await evidence_models.Link.all_objects.filter(kind=evidence_models.Link.Kind.DERIVED_FROM).acount() == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_lineage_is_not_a_connection(api_schema, simple_api_context, test_graph) -> None:
    """The panel's `connections` enumerates its kinds positively; lineage has fields of its own."""
    metric_id, _ = await _metric(api_schema, simple_api_context)
    instance = (await writes.execute(api_schema, simple_api_context, ASSERT_ENTITY, {"input": {"term": "Cell", "derivedFrom": [metric_id]}}))["assertEntityExists"]["instance"]

    data = await writes.execute(api_schema, simple_api_context, "query C($id: ID!) { instance(id: $id) { connections { kind } derivedFrom { kind } } }", {"id": instance["id"]})
    assert [c["kind"] for c in data["instance"]["connections"]] == []
    assert [c["kind"] for c in data["instance"]["derivedFrom"]] == ["DERIVED_FROM"]
