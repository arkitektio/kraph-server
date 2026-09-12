"""
Mutations submodule for the API.

Contains all GraphQL mutation resolvers for the graph engine.
"""

# `pin_node` is gone. It was a registered schema field whose entire body was
# `raise NotImplementedError`, so `pinNode` was advertised and could only error.
from .entity import assert_entity_exists, retract_entity, attest_entity
from .structure import assert_structure_exists, retract_structure, attest_structure, record_metrics, assert_informs
from .metric import assert_metric_value, assert_metric_value_for_structure, supersede_metric_value, retract_metric, attest_metric
from .relation import assert_relation_exists, supersede_relation, retract_relation
from .measurement import assert_measurement_exists, retract_measurement
from .structure_relation import (
    assert_structure_relation_exists,
    supersede_structure_relation,
    retract_structure_relation,
)
from .natural_event import assert_natural_event_exists, retract_natural_event, attest_natural_event
from .protocol_event import assert_protocol_event_exists, retract_protocol_event, attest_protocol_event
from .participation import assert_participation, assert_participations, retract_participation
from .link import classify_nodes, retract_links, attest_link
from .identity import assert_different_instance, assert_same_instance, retract_different_instance, retract_same_instance
from .comment import comment_on_structure, retract_comment, attest_comment
from .schema import (
    create_graph,
    update_graph,
    create_entity_category,
    update_entity_category,
    delete_entity_category,
    create_term,
    update_term,
    delete_term,
    update_structure_kind,
    delete_structure_kind,
    delete_graph,
    archive_graph,
    update_graph_visual,
    create_graph_table_query_through_builder,
    create_structure_relation_category,
    update_structure_relation_category,
    delete_structure_relation_category,
    update_metric_kind,
    delete_metric_kind,
    create_measurement_category,
    update_measurement_category,
    delete_measurement_category,
    create_relation_category,
    update_relation_category,
    delete_relation_category,
    create_natural_event_category,
    update_natural_event_category,
    delete_natural_event_category,
    create_protocol_event_category,
    update_protocol_event_category,
    delete_protocol_event_category,
)
from .insights import (
    create_graph_table_query,
    update_graph_table_query,
    delete_graph_table_query,
    archive_graph_table_query,
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
    "record_metrics",
    "assert_informs",
    "comment_on_structure",
    "retract_comment",
    "attest_comment",
    # Metric mutations
    "assert_metric_value",
    "assert_metric_value_for_structure",
    "supersede_metric_value",
    "retract_metric",
    # Relation mutations
    "assert_relation_exists",
    "supersede_relation",
    "retract_relation",
    "assert_measurement_exists",
    "retract_measurement",
    "assert_structure_relation_exists",
    "supersede_structure_relation",
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
    "assert_different_instance",
    "retract_different_instance",
    "create_graph_table_query_through_builder",
    # Schema mutations. These reached the package through `from .schema import *`
    # and so were re-exported without ever appearing here: `__all__` did not
    # describe the surface it is supposed to name.
    "create_graph",
    "update_graph",
    "create_entity_category",
    "update_entity_category",
    "delete_entity_category",
    "create_term",
    "update_term",
    "delete_term",
    "update_structure_kind",
    "delete_structure_kind",
    "delete_graph",
    "archive_graph",
    "update_graph_visual",
    "create_structure_relation_category",
    "update_structure_relation_category",
    "delete_structure_relation_category",
    "update_metric_kind",
    "delete_metric_kind",
    "create_measurement_category",
    "update_measurement_category",
    "delete_measurement_category",
    "create_relation_category",
    "update_relation_category",
    "delete_relation_category",
    "create_natural_event_category",
    "update_natural_event_category",
    "delete_natural_event_category",
    "create_protocol_event_category",
    "update_protocol_event_category",
    "delete_protocol_event_category",
    # Insights graph query subtype mutations
    "create_graph_table_query",
    "update_graph_table_query",
    "delete_graph_table_query",
    "archive_graph_table_query",
    # Insights node query mutations
    # Insights edge query mutations
    "create_scatter_plot",
    "update_scatter_plot",
    "delete_scatter_plot",
]
