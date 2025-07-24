from core import models, types, enums, filters as f, pagination as p, age
import strawberry
from kante.types import Info
from typing import Annotated


def pairs(
    graph_query: models.GraphQuery,
) -> types.Pairs:

    tgraph = graph_query.graph
    query = graph_query.query
    
    all_nodes = []
    all_edges = []

    print("Called")

    tgraph = graph_query.graph
    query = graph_query.query

    # First set the timeout
    real_query = f"""
    SELECT *
    FROM cypher(%s, $$
        {query}
    $$) as (n agtype, r agtype, m agtype);
    """

    print(real_query)
    
    pairs = []
    

    with age.graph_cursor() as cursor:
        cursor.execute(
            real_query,
            [tgraph.age_name],
        )
        all_results = cursor.fetchall()

        print("The result", all_results)

        # Convert AGTYPE (JSON string) to Python dict

        for result in all_results:
            pairs.append(types.Pair(
                source=types.entity_to_node_subtype(age.vertex_ag_to_retrieved_entity(tgraph.age_name, result[0])),
                edge=types.entity_to_node_subtype(age.edge_ag_to_retrieved_relation(tgraph.age_name, result[1])),
                target=types.entity_to_node_subtype(age.vertex_ag_to_retrieved_entity(tgraph.age_name, result[2])),
                
            ))



    return types.Pairs(pairs=pairs, graph=tgraph)
    
    

