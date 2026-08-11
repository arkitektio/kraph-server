"""
Mutations submodule for the API.

Contains all GraphQL mutation resolvers for the graph engine.
"""

from .node import pin_node
from .entity import create_entity, delete_entity, archive_entity, update_entity
from .structure import create_structure, delete_structure, archive_structure, update_structure, ensure_structure, link_structure_to_entity
from .metric import record_metric, create_metric, update_metric, delete_metric, archive_metric
from .relation import delete_relation, archive_relation
from .measurement import delete_measurement, archive_measurement
from .structure_relation import (
    create_structure_relation,
    update_structure_relation,
    delete_structure_relation,
    archive_structure_relation,
)
from .natural_event import create_natural_event, update_natural_event, delete_natural_event, archive_natural_event
from .protocol_event import create_protocol_event, update_protocol_event, delete_protocol_event, archive_protocol_event
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
    create_scatter_plot,
    update_scatter_plot,
    delete_scatter_plot,
    archive_scatter_plot,
)

__all__ = [
    "Mutation",
    # Entity mutations
    "create_entity",
    "delete_entity",
    "archive_entity",
    "update_entity",
    # Node mutations
    "pin_node",
    # Structure mutations
    "create_structure",
    "delete_structure",
    "archive_structure",
    "update_structure",
    "link_structure_to_entity",
    "ensure_structure",
    # Metric mutations
    "record_metric",
    "create_metric",
    "update_metric",
    "delete_metric",
    "archive_metric",
    # Relation mutations
    "delete_relation",
    "archive_relation",
    "delete_measurement",
    "archive_measurement",
    "create_structure_relation",
    "update_structure_relation",
    "delete_structure_relation",
    "archive_structure_relation",
    # Natural event mutations
    "create_natural_event",
    "update_natural_event",
    "delete_natural_event",
    "archive_natural_event",
    # Protocol event mutations
    "create_protocol_event",
    "update_protocol_event",
    "delete_protocol_event",
    "archive_protocol_event",
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
    "create_scatter_plot",
    "update_scatter_plot",
    "delete_scatter_plot",
    "archive_scatter_plot",
]
