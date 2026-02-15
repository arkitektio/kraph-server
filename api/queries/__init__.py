"""
Queries submodule for the API.

Contains all GraphQL query resolvers for the graph engine.
"""

from .entity import entity, entities_informed_by, entities
from .structure import structure, structure_by_identifier, informing_structures
from .metric import metrics_for_structure, metric
from .assertion import assertion_for_entity
from .insights.graph_nodes import render_graph_nodes
from .insights.graph_path import render_graph_path
from .insights.graph_pairs import render_graph_pairs
from .insights.graph_table import render_graph_table

__all__ = [
    "Query",
    # Entity queries
    "entity",
    "entities",
    "entities_informed_by",
    # Structure queries
    "structure",
    "structure_by_identifier",
    "informing_structures",
    # Metric queries
    "metrics_for_structure",
    "metrics_for_assertion",
    "metric",
    # Assertion queries
    "assertion_for_entity",
    # Insight render queries
    "render_graph_nodes",
    "render_graph_path",
    "render_graph_pairs",
    "render_graph_table",
]
