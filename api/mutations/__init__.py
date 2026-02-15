"""
Mutations submodule for the API.

Contains all GraphQL mutation resolvers for the graph engine.
"""

from .node import pin_node
from .entity import create_entity, recalculate_entity, delete_entity, archive_entity, update_entity
from .structure import create_structure, delete_structure, archive_structure, update_structure, link_structure_to_entity
from .metric import record_metric, create_metric, update_metric, delete_metric, archive_metric
from .relation import create_relation
from .schema import *
from .insights import (
    create_graph_table_query,
    update_graph_table_query,
    delete_graph_table_query,
    archive_graph_table_query,
    create_graph_pairs_query,
    update_graph_pairs_query,
    delete_graph_pairs_query,
    archive_graph_pairs_query,
    create_graph_path_query,
    update_graph_path_query,
    delete_graph_path_query,
    archive_graph_path_query,
    create_node_table_query,
    update_node_table_query,
    delete_node_table_query,
    archive_node_table_query,
    create_node_pairs_query,
    update_node_pairs_query,
    delete_node_pairs_query,
    archive_node_pairs_query,
    create_node_path_query,
    update_node_path_query,
    delete_node_path_query,
    archive_node_path_query,
    create_edge_table_query,
    update_edge_table_query,
    delete_edge_table_query,
    archive_edge_table_query,
    create_edge_pairs_query,
    update_edge_pairs_query,
    delete_edge_pairs_query,
    archive_edge_pairs_query,
    create_edge_path_query,
    update_edge_path_query,
    delete_edge_path_query,
    archive_edge_path_query,
)

__all__ = [
    "Mutation",
    # Entity mutations
    "create_entity",
    "delete_entity",
    "archive_entity",
    "update_entity",
    "recalculate_entity",
    # Node mutations
    "pin_node",
    # Structure mutations
    "create_structure",
    "delete_structure",
    "archive_structure",
    "update_structure",
    "link_structure_to_entity",
    # Metric mutations
    "record_metric",
    "create_metric",
    "update_metric",
    "delete_metric",
    "archive_metric",
    # Relation mutations
    "create_relation",
    "create_graph_table_query_through_builder",
    # Insights graph query subtype mutations
    "create_graph_table_query",
    "update_graph_table_query",
    "delete_graph_table_query",
    "archive_graph_table_query",
    "create_graph_pairs_query",
    "update_graph_pairs_query",
    "delete_graph_pairs_query",
    "archive_graph_pairs_query",
    "create_graph_path_query",
    "update_graph_path_query",
    "delete_graph_path_query",
    "archive_graph_path_query",
    # Insights node query mutations
    "create_node_table_query",
    "update_node_table_query",
    "delete_node_table_query",
    "archive_node_table_query",
    "create_node_pairs_query",
    "update_node_pairs_query",
    "delete_node_pairs_query",
    "archive_node_pairs_query",
    "create_node_path_query",
    "update_node_path_query",
    "delete_node_path_query",
    "archive_node_path_query",
    # Insights edge query mutations
    "create_edge_table_query",
    "update_edge_table_query",
    "delete_edge_table_query",
    "archive_edge_table_query",
    "create_edge_pairs_query",
    "update_edge_pairs_query",
    "delete_edge_pairs_query",
    "archive_edge_pairs_query",
    "create_edge_path_query",
    "update_edge_path_query",
    "delete_edge_path_query",
    "archive_edge_path_query",
]
