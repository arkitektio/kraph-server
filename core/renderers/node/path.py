import json
from core.age import (
    RetrievedEntity,
    graph_cursor,
    RetrievedRelation,
    vertex_ag_to_retrieved_entity,
)
import strawberry
from core import models, types, age
import re
import json
import re
import json
from kante.types import Info
from core.renderers.utils import parse_age_path


def path(node_query: models.NodeQuery, node_id: str) -> types.Path:
    """
    Query the knowledge graph for information about a given entity.

    Args:
        query: The entity to search for in the knowledge graph.

    Returns:
        A dictionary containing information about the entity.
    """

    all_nodes = []
    all_edges = []

    print("Called")

    tgraph = node_query.graph
    query = node_query.query
    print(tgraph.age_name)
    node = node_id

    # First set the timeout
    real_query = f"""
    SELECT *
    FROM cypher(%s, $$
        {query}
    $$) as (path agtype);
    """

    print(real_query, age.to_entity_id(node))

    with graph_cursor() as cursor:
        cursor.execute(
            real_query,
            [tgraph.age_name, int(age.to_entity_id(node))],
        )
        all_results = cursor.fetchall()

        print("The result", all_results)

        # Convert AGTYPE (JSON string) to Python dict

        for result in all_results:

            nodes, edges = parse_age_path(tgraph.age_name, result[0])
            all_nodes.extend(nodes)
            all_edges.extend(edges)

    return types.Path(nodes=all_nodes, edges=all_edges)
