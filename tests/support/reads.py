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
