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


# Regular expressions to extract vertices and edges
vertex_pattern = re.compile(
    r"(\{(?:[^{}]|(?:\{[^{}]*\}))*\})::vertex(?=[,\]])"
)  # Match balanced JSON for vertices
edge_pattern = re.compile(
    r"(\{(?:[^{}]|(?:\{[^{}]*\}))*\})::edge(?=[,\]])"
)  # Match balanced JSON for edges


def parse_age_path(graph_name, raw_path) -> tuple[set[types.Node], set[types.Edge]]:
    nodes = set()
    edges = set()

    # Extract all vertex JSON strings
    for match in vertex_pattern.findall(raw_path):
        print(match)
        vertex_data = json.loads(match)  # Convert JSON string to dict
        nodes.add(
            types.entity_to_node_subtype(
                RetrievedEntity(
                    graph_name=graph_name,
                    id=vertex_data["id"],
                    kind_age_name=vertex_data["label"],
                    properties=vertex_data.get("properties", {}),
                )
            )
        )

    # Extract all edge JSON strings
    for match in edge_pattern.findall(raw_path):
        print(match)
        edge_data = json.loads(match)  # Convert JSON string to dict
        edges.add(
            types.relation_to_edge_subtype(
                RetrievedRelation(
                    graph_name=graph_name,
                    id=edge_data["id"],
                    kind_age_name=edge_data["label"],
                    left_id=edge_data["start_id"],
                    right_id=edge_data["end_id"],
                    properties=edge_data["properties"],
                )
            )
        )

    return nodes, edges
