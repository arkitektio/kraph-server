"""Reading through the GraphQL API, for tests.

The view surface (`node(id:, graph:)`) and the log surface (`instance(id:)`,
`standings(id:)`) — named for the grain they answer at (RFC 0025).
"""

from typing import Any

from tests.support.writes import execute

NODE_PROPERTIES = """
    query NodeProperties($id: ID!, $graph: ID!) {
        node(id: $id, graph: $graph) { id ... on Entity { properties } ... on NaturalEvent { properties } ... on ProtocolEvent { properties } }
    }
"""

STANDINGS = """
    query Standings($id: ID!) { standings(id: $id) { stands at assertion { id subject } } }
"""


async def node_properties(api_schema: Any, ctx: Any, graph: Any, ref: str) -> dict[str, Any]:
    """The derived properties a view draws for one individual — `{}` when it draws none."""
    data = await execute(api_schema, ctx, NODE_PROPERTIES, {"id": ref, "graph": str(getattr(graph, "pk", graph))})
    return dict(data["node"].get("properties") or {})


async def standings_of(api_schema: Any, ctx: Any, claim_id: str) -> list[dict[str, Any]]:
    """Every position taken on one claim, newest first."""
    return list((await execute(api_schema, ctx, STANDINGS, {"id": claim_id}))["standings"])


RELATION = """
    query Relation($id: ID!) {
        relation(id: $id) { id }
    }
"""

INSTANCE_STANDINGS = """
    query ReadInstance($id: ID!) {
        instance(id: $id) { id kind term { key } standings { stands } }
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

ASSERTIONS = """
    query Assertions($filters: AssertionFilter, $pagination: LogPaginationInput) {
        assertions(filters: $filters, pagination: $pagination) { id seq subject appId }
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

STANDINGS_FILTERED = """
    query Standings($id: ID, $filters: StandingFilter) {
        standings(id: $id, filters: $filters) {
            id
            stands
            target { __typename ... on Instance { id } ... on Link { id } }
        }
    }
"""

ENTITY = """
    query Entity($id: ID!, $graph: ID!) {
        entity(id: $id, graph: $graph) {
            id
            label
            drawnLabels
            categoryIds
            categories { id key }
            richProperties { key value }
        }
    }
"""

NODES_BY_SEQ = """
    query L($graph: ID!) { nodes(graph: $graph, ordering: [{seq: DESC}]) { id } }
"""

TERMS = """
    query Terms($filters: TermFilter) {
        terms(filters: $filters) { id kind key label description purl }
    }
"""

INPUT_PARTICIPATIONS = """
    query P($graph: ID!) {
        inputParticipations(graph: $graph) { id }
    }
"""


def retrieved_node(properties: dict[str, Any]) -> Any:
    """A drawn record with these properties and nothing else — for the read-side filters."""
    from graph_engine.retrieved import RetrievedNode

    return RetrievedNode(controller=None, graph_name="testgraph", vertex_id=1, label="AIS", properties=properties)  # type: ignore[arg-type]


async def property_of(api_schema: Any, ctx: Any, graph: Any, ref: str, key: str) -> Any:
    """One derived property a view draws for an individual — None when it draws none."""
    return (await node_properties(api_schema, ctx, graph, ref)).get(key)
