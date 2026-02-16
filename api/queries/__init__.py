"""
Queries submodule for the API.

Contains all GraphQL query resolvers for the graph engine.
"""

from .entity import entity, entities_informed_by, entities
from .structure import structure, structures, structure_by_identifier, informing_structures
from .metric import metrics_for_structure, metric, metrics
from .measurement import measurement, measurements
from .relation import relation, relations
from .structure_relation import structure_relation, structure_relations
from .describes import describe, describes
from .input_participation import input_participation, input_participations
from .output_participation import output_participation, output_participations
from .natural_event import natural_event, natural_events
from .protocol_event import protocol_event, protocol_events
from .assertion import assertion_for_entity
from .insights.graph_nodes import render_graph_nodes
from .insights.graph_path import render_graph_path
from .insights.graph_pairs import render_graph_pairs
from .insights.graph_table import render_graph_table
from .node import node, nodes

__all__ = [
    "Query",
    # Entity queries
    "entity",
    "node",
    "nodes",
    "entities",
    "entities_informed_by",
    # Structure queries
    "structure",
    "structures",
    "structure_by_identifier",
    "informing_structures",
    # Edge queries
    "measurement",
    "measurements",
    "relation",
    "relations",
    "describe",
    "describes",
    "input_participation",
    "input_participations",
    "output_participation",
    "output_participations",
    # Structure relation queries
    "structure_relation",
    "structure_relations",
    # Event queries
    "natural_event",
    "natural_events",
    "protocol_event",
    "protocol_events",
    # Metric queries
    "metrics_for_structure",
    "metrics_for_assertion",
    "metric",
    "metrics",
    # Assertion queries
    "assertion_for_entity",
    # Insight render queries
    "render_graph_nodes",
    "render_graph_path",
    "render_graph_pairs",
    "render_graph_table",
]
