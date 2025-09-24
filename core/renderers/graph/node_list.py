from core import models, types, enums, filters as f, pagination as p, age
import strawberry
from kante.types import Info
from typing import Annotated
from .parser import render_cypher_template


def node_list(graph_query: models.GraphQuery, check_exists: bool = True) -> types.NodeList:
    tgraph = graph_query.graph
    query = graph_query.query

    all_nodes = []
    all_edges = []

    print("Called")

    tgraph = graph_query.graph
    query = graph_query.query

    rendered_query, params = render_cypher_template(graph_query.query)

    # First set the timeout
    real_query = f"""
    SELECT *
    FROM cypher(%s, $$
        {rendered_query}
    $$) as (n agtype);
    """

    print(real_query)

    nodes = []

    with age.graph_cursor() as cursor:
        cursor.execute(
            real_query,
            [tgraph.age_name],
        )
        all_results = cursor.fetchall()

        print("The result", all_results)

        # Convert AGTYPE (JSON string) to Python dict

        for result in all_results:
            nodes.append(types.entity_to_node_subtype(age.vertex_ag_to_retrieved_entity(tgraph.age_name, result[0])))
        if check_exists:
            if not nodes:
                raise ValueError("No nodes found in the query result")

    return types.NodeList(nodes=nodes, graph=tgraph)
