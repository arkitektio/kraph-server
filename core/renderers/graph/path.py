import json
from core.age import (
    RetrievedEntity,
    graph_cursor,
    RetrievedRelation,
    vertex_ag_to_retrieved_entity,
)
import strawberry
from core import models, types, inputs
import re
import json
import re
import json
from kante.types import Info
from core.renderers.utils import parse_age_path
from .parser import render_cypher_template


def path(graph_query: models.GraphQuery, check_exists: bool = True, filters: inputs.GraphQueryFilters | None = None, pagination: inputs.GraphQueryPagination | None = None, order: inputs.GraphQueryOrder | None = None) -> types.Path:
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

    tgraph = graph_query.graph
    query = graph_query.query

    rendered_query, params = render_cypher_template(graph_query.query, filters=filters, pagination=pagination, order=order)
    print(rendered_query)

    # First set the timeout
    real_query = f"""
    SELECT *
    FROM cypher(%s, $$
        {rendered_query}
    $$) as (path agtype);
    """

    print(real_query)

    with graph_cursor() as cursor:
        cursor.execute(
            real_query,
            [tgraph.age_name],
        )
        all_results = cursor.fetchall()

        print("The result", all_results)

        # Convert AGTYPE (JSON string) to Python dict

        for result in all_results:
            nodes, edges = parse_age_path(tgraph.age_name, result[0])
            all_nodes.extend(nodes)
            all_edges.extend(edges)

        if check_exists:
            if not all_nodes:
                raise ValueError("No nodes found in the path query result")
            if not all_edges:
                raise ValueError("No edges found in the path query result")

    return types.Path(nodes=all_nodes, edges=all_edges)
