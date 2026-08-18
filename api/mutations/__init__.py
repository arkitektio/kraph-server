"""
Mutations submodule for the API.

Contains all GraphQL mutation resolvers for the graph engine.
"""

# `pin_node` is gone. It was a registered schema field whose entire body was
# `raise NotImplementedError`, so `pinNode` was advertised and could only error.
from .entity import assert_entity_exists, retract_entity, attest_entity
from .structure import assert_structure_exists, retract_structure, attest_structure, update_structure, ensure_structure, link_structure_to_entity
from .metric import assert_metric_value, assert_metric_value_for_structure, supersede_metric_value, retract_metric, attest_metric
from .relation import assert_relation_exists, update_relation, retract_relation
from .measurement import assert_measurement_exists, retract_measurement
from .structure_relation import (
    assert_structure_relation_exists,
    update_structure_relation,
    retract_structure_relation,
)
from .natural_event import assert_natural_event_exists, retract_natural_event, attest_natural_event
from .protocol_event import assert_protocol_event_exists, retract_protocol_event, attest_protocol_event
from .participation import assert_participation, assert_participations, retract_participation
from .link import classify_nodes, retract_links, attest_link
from .identity import assert_same_instance, retract_same_instance
from .comment import comment_on_structure, retract_comment, attest_comment
from .schema import *
from .schema import create_graph_table_query_through_builder
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
)

__all__ = [
    # Entity mutations
    "assert_entity_exists",
    "retract_entity",
    "attest_entity",
    "attest_structure",
    "attest_metric",
    "attest_link",
    # Node mutations
    # Structure mutations
    "assert_structure_exists",
    "retract_structure",
    "update_structure",
    "link_structure_to_entity",
    "comment_on_structure",
    "retract_comment",
    "attest_comment",
    "ensure_structure",
    # Metric mutations
    "assert_metric_value",
    "assert_metric_value_for_structure",
    "supersede_metric_value",
    "retract_metric",
    # Relation mutations
    "assert_relation_exists",
    "update_relation",
    "retract_relation",
    "assert_measurement_exists",
    "retract_measurement",
    "assert_structure_relation_exists",
    "update_structure_relation",
    "retract_structure_relation",
    # Natural event mutations
    "assert_natural_event_exists",
    "retract_natural_event",
    "attest_natural_event",
    # Protocol event mutations
    "assert_protocol_event_exists",
    "retract_protocol_event",
    "attest_protocol_event",
    "assert_participation",
    "retract_participation",
    "assert_participations",
    "classify_nodes",
    "retract_links",
    "assert_same_instance",
    "retract_same_instance",
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
]
