"""Minting evidence through the GraphQL API, for tests that need some to exist.

A module rather than a fixture file: these are helpers a test calls, not state it
receives, and every one of them used to be a per-file copy that resolved a
graph-scoped `*Category` row to get its id.

**None of them takes a graph**, which is the point of the write surface naming a
term. A claim says "there is a Cell here"; the graph a test happens to have
materialized is what decides whether that claim is drawn, and asking for one here
would put the coupling back in the tests after removing it from the API.
"""

from typing import Any, Iterable

import kante
from kante.context import HttpContext

# The payload sits one level down now: a write returns the assertion it recorded,
# the thing claimed, and every view that draws it. These helpers reach through to
# the id so their eighteen call sites did not have to change.
ASSERT_ENTITY_EXISTS = """
    mutation AssertEntityExists($input: AssertEntityExistsInput!) {
        assertEntityExists(input: $input) { instance { id } }
    }
"""

ASSERT_NATURAL_EVENT_EXISTS = """
    mutation AssertNaturalEventExists($input: AssertNaturalEventExistsInput!) {
        assertNaturalEventExists(input: $input) { instance { id } }
    }
"""

ASSERT_PROTOCOL_EVENT_EXISTS = """
    mutation AssertProtocolEventExists($input: AssertProtocolEventExistsInput!) {
        assertProtocolEventExists(input: $input) { instance { id } }
    }
"""

ASSERT_RELATION_EXISTS = """
    mutation AssertRelationExists($input: AssertRelationExistsInput!) {
        assertRelationExists(input: $input) { link { id } }
    }
"""

CLASSIFY_NODES = """
    mutation ClassifyNodes($input: ClassifyNodesInput!) {
        classifyNodes(input: $input) { instances { id } }
    }
"""

#: The entity write with the act's position, for tests that read the log's order.
ASSERT_ENTITY = """
    mutation AssertEntityExists($input: AssertEntityExistsInput!) {
        assertEntityExists(input: $input) {
            assertion { id seq }
            instance { id }
        }
    }
"""

ASSERT_SAME = """
    mutation AssertSameInstance($input: AssertSameInstanceInput!) {
        assertSameInstance(input: $input) {
            assertion { id }
            links { kind id source { ... on Instance { id } } target { ... on Instance { id } } }
        }
    }
"""

RETRACT_SAME = """
    mutation RetractSameInstance($input: RetractSameInstanceInput!) {
        retractSameInstance(input: $input) { assertion { id } links { id } }
    }
"""

ASSERT_DIFFERENT = """
    mutation AssertDifferentInstance($input: AssertDifferentInstanceInput!) {
        assertDifferentInstance(input: $input) {
            assertion { id }
            links { kind id source { ... on Instance { id } } target { ... on Instance { id } } }
        }
    }
"""

RETRACT_DIFFERENT = """
    mutation RetractDifferentInstance($input: RetractDifferentInstanceInput!) {
        retractDifferentInstance(input: $input) { assertion { id } links { id } }
    }
"""

CREATE_GRAPH = """
    mutation CreateGraph($input: CreateGraphInput!) {
        createGraph(input: $input) { id }
    }
"""


async def execute(api_schema: kante.Schema, ctx: HttpContext, document: str, variables: dict[str, Any] | None = None) -> Any:
    """Run one document and hand back its data; a GraphQL error is a failed test."""
    result = await api_schema.execute(document, variable_values=variables or {}, context_value=ctx)
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    return result.data


async def _mutate(api_schema: kante.Schema, ctx: HttpContext, document: str, field: str, payload: dict[str, Any]) -> Any:
    return (await execute(api_schema, ctx, document, {"input": payload}))[field]


async def assert_entity(api_schema: kante.Schema, ctx: HttpContext, term: str, *, same_as: Iterable[str] | None = None, evidence: Iterable[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Claim that an entity of this word exists, optionally as one thing with others. Returns the whole payload."""
    return await _mutate(api_schema, ctx, ASSERT_ENTITY, "assertEntityExists", {"term": term, "supportingEvidence": list(evidence or []), "sameAs": list(same_as or [])})


async def merge(api_schema: kante.Schema, ctx: HttpContext, refs: Iterable[str]) -> str:
    """Claim that these instances are one thing. Returns the first sameness claim's id."""
    return (await _mutate(api_schema, ctx, ASSERT_SAME, "assertSameInstance", {"instances": list(refs)}))["links"][0]["id"]


async def differ(api_schema: kante.Schema, ctx: HttpContext, refs: Iterable[str]) -> str:
    """Claim that these instances are two things. Returns the difference claim's id."""
    return (await _mutate(api_schema, ctx, ASSERT_DIFFERENT, "assertDifferentInstance", {"instances": list(refs)}))["links"][0]["id"]


async def create_entity(
    api_schema: kante.Schema,
    ctx: HttpContext,
    term: str,
    evidence: Iterable[dict[str, Any]] | None = None,
) -> str:
    """Claim that an entity of this word exists. Returns its id."""
    return (
        await _mutate(
            api_schema,
            ctx,
            ASSERT_ENTITY_EXISTS,
            "assertEntityExists",
            {"term": term, "supportingEvidence": list(evidence or [])},
        )
    )["instance"]["id"]


async def create_event(
    api_schema: kante.Schema,
    ctx: HttpContext,
    term: str,
    *,
    protocol: bool = False,
    inputs: Iterable[dict[str, Any]] | None = None,
    outputs: Iterable[dict[str, Any]] | None = None,
    evidence: Iterable[dict[str, Any]] | None = None,
) -> str:
    """Claim that an event of this word happened. Returns its id."""
    document = ASSERT_PROTOCOL_EVENT_EXISTS if protocol else ASSERT_NATURAL_EVENT_EXISTS
    field = "assertProtocolEventExists" if protocol else "assertNaturalEventExists"
    # Both documents answer with `instance`: a write returns the claim, and an
    # `Instance` carries its own `kind`. It used to be `protocolEvent` /
    # `naturalEvent`, one graph-shaped type per kind.
    payload_key = "instance"
    return (
        await _mutate(
            api_schema,
            ctx,
            document,
            field,
            {
                "term": term,
                "inputs": list(inputs or []),
                "outputs": list(outputs or []),
                "supportingEvidence": list(evidence or []),
            },
        )
    )[payload_key]["id"]


async def create_relation(
    api_schema: kante.Schema,
    ctx: HttpContext,
    term: str,
    source: str,
    target: str,
) -> str:
    """Claim that this word relates these two entities. Returns the claim's id."""
    return (
        await _mutate(
            api_schema,
            ctx,
            ASSERT_RELATION_EXISTS,
            "assertRelationExists",
            {"term": term, "sourceId": source, "targetId": target, "supportingEvidence": []},
        )
    )["link"]["id"]


async def classify(api_schema: kante.Schema, ctx: HttpContext, pairs: Iterable[tuple[str, str]]) -> list[str]:
    """Claim, as one act, that each of these nodes is of the paired word."""
    classified = await _mutate(
        api_schema,
        ctx,
        CLASSIFY_NODES,
        "classifyNodes",
        {"classifications": [{"node": node, "term": term} for node, term in pairs]},
    )
    return [entry["id"] for entry in classified["instances"]]
