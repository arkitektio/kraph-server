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

RETRACT_LINKS = """
    mutation RetractLinks($input: RetractLinksInput!) {
        retractLinks(input: $input) { assertion { id } links { id kind } }
    }
"""

ATTEST_LINK = """
    mutation AttestLink($input: AttestLinkInput!) {
        attestLink(input: $input) { assertion { id } links { id kind } }
    }
"""

UPDATE_GRAPH_SAMENESS_RULE = """
    mutation UpdateSamenessRule($input: UpdateGraphInput!) {
        updateGraph(input: $input) { id samenessRule { rules { when { field operator value } } } }
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

ASSERT_STRUCTURE = """
    mutation CreateStructure($input: AssertStructureExistsInput!) {
        assertStructureExists(input: $input) { structure { id } }
    }
"""

ASSERT_MEASUREMENT = """
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

RETRACT_STRUCTURE_RELATION = """
    mutation ArchiveStructureRelation($input: RetractStructureRelationInput!) {
        retractStructureRelation(input: $input) { link { id } }
    }
"""

ASSERT_STRUCTURE_RELATION = """
    mutation CreateStructureRelation($input: AssertStructureRelationExistsInput!) {
        assertStructureRelationExists(input: $input) {
            link {
                id
                kind
                sourceRef
                targetRef
                source { ... on Structure { id object } }
                target { ... on Structure { id object } }
            }
        }
    }
"""

SUPERSEDE_STRUCTURE_RELATION = """
    mutation UpdateStructureRelation($input: SupersedeStructureRelationInput!) {
        supersedeStructureRelation(input: $input) { link { id } }
    }
"""

CREATE_TERM = """
    mutation CreateTerm($input: CreateTermInput!) {
        createTerm(input: $input) { id kind key label description purl }
    }
"""

UPDATE_TERM = """
    mutation UpdateTerm($input: UpdateTermInput!) {
        updateTerm(input: $input) { id kind key label description }
    }
"""

CREATE_ENTITY_CATEGORY = """
    mutation CreateEntityCategory($input: CreateEntityCategoryInput!) {
        createEntityCategory(input: $input) { id key }
    }
"""

ASSERT_ENTITY_OBSERVED = """
    mutation N($input: AssertEntityExistsInput!) {
        assertEntityExists(input: $input) { instance { id observedAt } }
    }
"""

ASSERT_ENTITY_WITH_CONFIDENCE = """
    mutation N($input: AssertEntityExistsInput!) {
        assertEntityExists(input: $input) { instance { id confidence } }
    }
"""

ASSERT_RELATION_WITH_CONFIDENCE = """
    mutation R($input: AssertRelationExistsInput!) {
        assertRelationExists(input: $input) { link { id confidence drawnIn { edge { confidence } } } }
    }
"""

RETRACT_ENTITY_SCORED = """
    mutation X($input: RetractEntityInput!) {
        retractEntity(input: $input) { instance { id standings { stands confidence } } }
    }
"""

RETRACT_ENTITY_AT = """
    mutation X($input: RetractEntityInput!) {
        retractEntity(input: $input) { instance { id standings { stands at } } }
    }
"""

ATTEST_ENTITY = """
    mutation AttestEntity($input: AttestEntityInput!) {
        attestEntity(input: $input) {
            instance { id standings { stands at } }
            drawings { graph { id } }
        }
    }
"""

RETRACT_ENTITY = """
    mutation RetractEntity($input: RetractEntityInput!) {
        retractEntity(input: $input) {
            assertion { id }
            instance { id standings { stands } }
            drawings { graph { id } }
        }
    }
"""

ARCHIVE_GRAPH = """
    mutation ArchiveGraph($input: ArchiveGraphInput!) {
        archiveGraph(input: $input) { id isArchived }
    }
"""

UPDATE_GRAPH_VISUAL = """
    mutation UpdateGraphVisual($input: UpdateGraphVisualInput!) {
        updateGraphVisual(input: $input) { id }
    }
"""

UPDATE_ENTITY_CATEGORY = """
    mutation U($input: UpdateEntityCategoryInput!) {
        updateEntityCategory(input: $input) { id definition { rules { when { field operator value } } } }
    }
"""

ASSERT_METRIC_VALUE = """
    mutation RecordMetric($input: AssertMetricValueInput!) {
        assertMetricValue(input: $input) { metric { id } }
    }
"""

RETRACT_RELATION = """
    mutation ArchiveRelation($input: RetractRelationInput!) {
        retractRelation(input: $input) { link { id } }
    }
"""

ASSERT_RELATION_WITH_TERM = """
    mutation CreateRelation($input: AssertRelationExistsInput!) {
        assertRelationExists(input: $input) { link { id term { key } } }
    }
"""

RETRACT_PARTICIPATION = """
    mutation ArchiveParticipation($input: RetractParticipationInput!) {
        retractParticipation(input: $input) { link { id } }
    }
"""

ASSERT_PARTICIPATION = """
    mutation AssertParticipation($input: AssertParticipationInput!) {
        assertParticipation(input: $input) {
            link { kind id }
            drawings { graph { id } category { id } edge { __typename id } }
        }
    }
"""

ASSERT_ENTITY_DRAWN = """
    mutation CreateEntity($input: AssertEntityExistsInput!) {
        assertEntityExists(input: $input) {
            instance { id }
            drawings { category { id } node { id drawnLabels } }
        }
    }
"""


def roi(obj: str, length: float | None) -> list[dict[str, Any]]:
    """One ROI as supporting evidence, measured once when `length` is given."""
    metrics = [] if length is None else [{"key": "vector_length", "value": length, "valueKind": "FLOAT"}]
    return [{"identifier": "ROI", "object": obj, "metrics": metrics}]


async def create_structure(api_schema: kante.Schema, ctx: HttpContext, *, identifier: str = "ROI", object: str | None = None, metrics: Iterable[dict[str, Any]] | None = None) -> str:
    """Claim that an external datum exists, with any measurements of it. Returns its id.

    The kind is minted on demand — kinds are the organization's vocabulary and a
    write may name one nobody has used yet (RFC 0023)."""
    import uuid

    payload = {"identifier": identifier, "object": object or f"roi_{uuid.uuid4().hex[:8]}", "metrics": list(metrics or [])}
    return (await _mutate(api_schema, ctx, ASSERT_STRUCTURE, "assertStructureExists", payload))["structure"]["id"]
