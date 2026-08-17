"""Saying "this is AIS 6" through the API.

Four things have to happen, and they have to happen as **one act**: mint the term
if the organization has not used it, mint a *fresh* instance, claim the structure
measures it, and claim the new instance is the same as the one already known as
AIS 6.

The first three already worked. The fourth is what `docs/LOG.md` recorded as a
known gap — *"No merge. Identity is a bare uuid, so one vertex standing for
several nodes is expressible — but nothing implements it."*

The design worth pinning: **every observation mints its own instance.** Nothing
reuses a node id, because an observation cannot be asked to know about a prior
one — so identity between observations is a claim in its own right, contestable
and retractable like any other.
"""

import uuid

import kante
import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext

from core import models as core_models
from evidence import identity, models as evidence_models

ASSERT_ENTITY = """
    mutation AssertEntityExists($input: AssertEntityExistsInput!) {
        assertEntityExists(input: $input) {
            assertion { id seq }
            instance { id }
        }
    }
"""

ASSERT_SAME = """
    mutation AssertSameEntity($input: AssertSameInstanceInput!) {
        assertSameInstance(input: $input) {
            assertion { id }
            links { kind id source { ... on Instance { id } } target { ... on Instance { id } } }
        }
    }
"""

RETRACT_SAME = """
    mutation RetractSameEntity($input: RetractSameInstanceInput!) {
        retractSameInstance(input: $input) { assertion { id } links { id } }
    }
"""


async def _assert_entity(api_schema, ctx, term: str, same_as: list[str] | None = None) -> dict:
    result = await api_schema.execute(
        ASSERT_ENTITY,
        variable_values={"input": {"term": term, "supportingEvidence": [], "sameAs": same_as or []}},
        context_value=ctx,
    )
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    return result.data["assertEntityExists"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_this_is_ais_6_is_one_act(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """One call, one assertion, and the two instances end up one thing.

    The assertion is the unit of authorship — a set of claims made together by one
    actor is one assertion — and `Assertion.action_id`, the field that would tie
    two separate calls back together, is never populated. So if the sameness claim
    were a second call it could never be reassembled with the instance it belongs
    to.
    """
    established = await _assert_entity(api_schema, simple_api_context, "AIS")

    observed = await _assert_entity(api_schema, simple_api_context, "AIS", same_as=[established["instance"]["id"]])

    assert observed["instance"]["id"] != established["instance"]["id"], "The observation mints its own instance rather than reusing one"

    @sync_to_async
    def claims_under(assertion_id: str) -> dict[str, int]:
        links = evidence_models.Link.all_objects.filter(assertion_id=assertion_id)
        counted: dict[str, int] = {}
        for link in links:
            counted[str(link.kind)] = counted.get(str(link.kind), 0) + 1
        return counted

    counted = await claims_under(observed["assertion"]["id"])
    assert counted.get("classifies") == 1, "The instance is classified under the word"
    assert counted.get("same_as") == 1, "and claimed the same as the one already known — under the same assertion"

    @sync_to_async
    def component() -> list[str]:
        organization = test_graph.organization
        return identity.component_refs(organization, [observed["instance"]["id"]])[observed["instance"]["id"]]

    assert sorted(await component()) == sorted([observed["instance"]["id"], established["instance"]["id"]])


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_noticing_later_that_two_instances_are_one(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The standalone claim, for the case that is genuinely its own act."""
    first = await _assert_entity(api_schema, simple_api_context, "AIS")
    second = await _assert_entity(api_schema, simple_api_context, "AIS")

    result = await api_schema.execute(
        ASSERT_SAME,
        variable_values={"input": {"instances": [first["instance"]["id"], second["instance"]["id"]]}},
        context_value=simple_api_context,
    )
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    payload = result.data["assertSameInstance"]

    assert len(payload["links"]) == 1
    claim = payload["links"][0]

    # `kind`, which is the column the claim carries. It used to be `__typename` over
    # a payload of drawing types, where a sameness claim had no type of its own and
    # `cast_edge_to_graphql_type` reported anything it did not recognise as a
    # `Relation` — the exact defect participations had.
    assert claim["kind"] == "SAME_AS"
    assert {claim["source"]["id"], claim["target"]["id"]} == {first["instance"]["id"], second["instance"]["id"]}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_three_instances_claimed_together_are_one_assertion(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """"These are all the same cell" is one statement, so it is one assertion.

    Recorded pairwise rather than star-shaped around the first id, because
    sameness has no primary — making the first argument the hub would let identity
    depend on argument order.
    """
    entities = [(await _assert_entity(api_schema, simple_api_context, "AIS"))["instance"]["id"] for _ in range(3)]

    result = await api_schema.execute(
        ASSERT_SAME,
        variable_values={"input": {"instances": entities}},
        context_value=simple_api_context,
    )
    assert result.errors is None, f"GraphQL errors: {result.errors}"

    assert len({claim["id"] for claim in result.data["assertSameInstance"]["links"]}) == 2, "n instances need n-1 claims to connect"

    @sync_to_async
    def component() -> list[str]:
        return identity.component_refs(test_graph.organization, [entities[0]])[entities[0]]

    assert sorted(await component()) == sorted(entities)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_retracting_sameness_splits_the_component(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Taking it back has to actually take it back.

    Union-find has no un-union, so the component is rebuilt from the claims that
    survive rather than adjusted — and this is the test that says the rebuild
    reaches the API.
    """
    first = await _assert_entity(api_schema, simple_api_context, "AIS")
    second = await _assert_entity(api_schema, simple_api_context, "AIS", same_as=[first["instance"]["id"]])

    @sync_to_async
    def sameness_id() -> str:
        link = evidence_models.Link.all_objects.filter(kind=evidence_models.Link.Kind.SAME_AS).first()
        assert link is not None
        return str(link.pk)

    result = await api_schema.execute(
        RETRACT_SAME,
        variable_values={"input": {"id": await sameness_id()}},
        context_value=simple_api_context,
    )
    assert result.errors is None, f"GraphQL errors: {result.errors}"

    @sync_to_async
    def components() -> tuple[list[str], list[str]]:
        organization = test_graph.organization
        return (
            identity.component_refs(organization, [first["instance"]["id"]])[first["instance"]["id"]],
            identity.component_refs(organization, [second["instance"]["id"]])[second["instance"]["id"]],
        )

    left, right = await components()
    assert left == [first["instance"]["id"]], "Each is its own thing again"
    assert right == [second["instance"]["id"]]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_structure_cannot_be_claimed_the_same_as_anything(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Structures are never "the same".

    A structure is a pointer to an external datum, already idempotent by
    `(identifier, object)` — so two of them are either one row or two different
    data, and a sameness claim about them is really a claim about the entities
    they inform. Refusing is better than folding a claim no reader can act on.
    """
    entity = (await _assert_entity(api_schema, simple_api_context, "AIS"))["instance"]["id"]

    created = await api_schema.execute(
        """
        mutation AssertStructureExists($input: AssertStructureExistsInput!) {
            assertStructureExists(input: $input) { structure { id } }
        }
        """,
        variable_values={"input": {"identifier": "@mikro/roi", "object": f"roi-{uuid.uuid4().hex[:8]}", "metrics": []}},
        context_value=simple_api_context,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    structure = created.data["assertStructureExists"]["structure"]["id"]

    refused = await api_schema.execute(
        ASSERT_SAME,
        variable_values={"input": {"instances": [entity, structure]}},
        context_value=simple_api_context,
    )
    assert refused.errors, "A structure is not an entity and cannot be merged with one"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_node_cannot_be_claimed_the_same_as_itself(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """A node is trivially itself, so the claim carries no information."""
    entity = (await _assert_entity(api_schema, simple_api_context, "AIS"))["instance"]["id"]

    result = await api_schema.execute(
        ASSERT_SAME,
        variable_values={"input": {"instances": [entity, entity]}},
        context_value=simple_api_context,
    )
    assert result.errors, "Claiming a node is the same as itself must be refused"
