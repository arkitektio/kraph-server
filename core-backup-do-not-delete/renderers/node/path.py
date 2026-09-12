from core.age import (
    graph_cursor,
)
from core import models, types, age, inputs
from core.renderers.utils import parse_age_path
from .parser import render_node_cypher_template


def path(node_query: models.NodeQuery, node_id: str, filters: inputs.NodeQueryFilters | None = None , pagination: inputs.NodeQueryPagination | None = None, order: inputs.NodeQueryOrder | None = None) -> types.Path:
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
    print(tgraph.age_name)
    node = node_id
    
    rendered_query, params = render_node_cypher_template(node_query.query, filters=filters)

    # First set the timeout
    real_query = f"""
    SELECT *
    FROM cypher(%s, $$
        {rendered_query}
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
