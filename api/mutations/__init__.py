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
]
