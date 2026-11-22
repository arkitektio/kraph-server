"""
Mutations submodule for the API.

Contains all GraphQL mutation resolvers for the graph engine.
"""

# `pin_node` is gone. It was a registered schema field whose entire body was
# `raise NotImplementedError`, so `pinNode` was advertised and could only error.
from .comment import attest_comment, comment_on_structure, retract_comment
from .entity import assert_entity_exists, attest_entity, retract_entity
from .identity import (
    assert_different_instance,
    assert_same_instance,
    retract_different_instance,
    retract_same_instance,
)
from .insights import (
    archive_graph_table_query,
    create_graph_pairs_query,
    create_graph_table_query,
    create_scatter_plot,
    delete_graph_pairs_query,
    delete_graph_table_query,
    delete_scatter_plot,
    update_graph_pairs_query,
    update_graph_table_query,
    update_scatter_plot,
)
from .link import attest_link, classify_nodes, retract_links
from .measurement import assert_measurement_exists, retract_measurement
from .metric import (
    assert_metric_value,
    assert_metric_values,
    attest_metric,
    retract_metric,
    supersede_metric_value,
)
from .natural_event import (
    assert_natural_event_exists,
    attest_natural_event,
    retract_natural_event,
)
from .participation import (
    assert_participation,
    assert_participations,
    retract_participation,
)
from .protocol_event import (
    assert_protocol_event_exists,
    attest_protocol_event,
    retract_protocol_event,
)
from .relation import assert_relation_exists, retract_relation, supersede_relation
from .schema import (
    archive_graph,
    create_entity_category,
    create_graph,
    create_graph_table_query_through_builder,
    create_measurement_category,
    create_natural_event_category,
    create_protocol_event_category,
    create_relation_category,
    create_structure_category,
    create_structure_relation_category,
    create_term,
    delete_entity_category,
    delete_graph,
    delete_measurement_category,
    delete_metric_kind,
    delete_natural_event_category,
    delete_protocol_event_category,
    delete_relation_category,
    delete_structure_category,
    delete_structure_kind,
    delete_structure_relation_category,
    update_entity_category,
    update_graph,
    update_graph_visual,
    update_measurement_category,
    update_metric_kind,
    update_natural_event_category,
    update_protocol_event_category,
    update_relation_category,
    update_structure_category,
    update_structure_kind,
    update_structure_relation_category,
    update_term,
)
from .structure import (
    assert_informs,
    assert_structure_exists,
    attest_structure,
    retract_structure,
)
from .structure_relation import (
    assert_structure_relation_exists,
    retract_structure_relation,
    supersede_structure_relation,
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
    "assert_informs",
    "comment_on_structure",
    "retract_comment",
    "attest_comment",
    # Metric mutations
    "assert_metric_value",
    "assert_metric_values",
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
    "update_structure_kind",
    "delete_structure_kind",
    "delete_graph",
    "archive_graph",
    "update_graph_visual",
    "create_structure_category",
    "update_structure_category",
    "delete_structure_category",
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
    "create_graph_pairs_query",
    "update_graph_pairs_query",
    "delete_graph_pairs_query",
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
