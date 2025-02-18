import json
from core.age import RetrievedEntity, graph_cursor, RetrievedRelation, vertex_ag_to_retrieved_entity
import strawberry
from core import models, types
import re
import json
import re
import json
from kante.types import Info




# Regular expressions to extract vertices and edges
vertex_pattern = re.compile(r'(\{(?:[^{}]|(?:\{[^{}]*\}))*\})::vertex(?=[,\]])')  # Match balanced JSON for vertices
edge_pattern = re.compile(r'(\{(?:[^{}]|(?:\{[^{}]*\}))*\})::edge(?=[,\]])')      # Match balanced JSON for edges


def parse_age_path(graph_name, raw_path):
    nodes = set()
    edges = set()


    # Extract all vertex JSON strings
    for match in vertex_pattern.findall(raw_path):
        print(match)
        vertex_data = json.loads(match)  # Convert JSON string to dict
        nodes.add(types.entity_to_node_subtype(
            RetrievedEntity(
                graph_name=graph_name,
                id=vertex_data["id"], 
                kind_age_name=vertex_data["label"], 
                properties=vertex_data.get("properties", {})
            )
        ))

    # Extract all edge JSON strings
    for match in edge_pattern.findall(raw_path):
        print(match)
        edge_data = json.loads(match)  # Convert JSON string to dict
        edges.add(types.relation_to_edge_subtype(
                 RetrievedRelation(
            graph_name=graph_name,
            id=edge_data["id"],
            kind_age_name=edge_data["label"],
            left_id=edge_data["start_id"],
            right_id=edge_data["end_id"],
            properties=edge_data["properties"],
        )))

    return nodes, edges








def path(info: Info, graph: strawberry.ID, query: str) -> types.Path:
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
    
    tgraph = models.Graph.objects.get(id=graph)
    print(tgraph.age_name)
    
    
    # First set the timeout
    real_query = f"""
    SELECT *
    FROM cypher(%s, $$
        {query}
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
            
                

    return types.Path(nodes=all_nodes, edges=all_edges)
