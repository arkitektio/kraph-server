"""
Queries submodule for the API.

Contains all GraphQL query resolvers for the graph engine.
"""

from .claim import instance, link, standings
from .comment import comment, comments_for, my_mention_count, my_mentions
from .description import description
from .entity import entities, entity
from .input_participation import input_participation, input_participations
from .insights.graph_pairs import render_graph_pairs
from .insights.graph_table import render_graph_table
from .insights.table_plan import render_table_plan
from .kinds import (
    metric_kind,
    metric_kinds,
    structure_kind,
    structure_kinds,
    term,
    terms,
)
from .log import assertion, assertions, changes
from .measurement import measurement, measurements
from .metric import metric, metrics, metrics_for_assertion, metrics_for_structure
from .natural_event import natural_event, natural_events
from .node import node, nodes
from .output_participation import output_participation, output_participations
from .protocol_event import protocol_event, protocol_events
from .relation import relation, relations
from .structure import (
    informing_structures,
    structure,
    structure_by_identifier,
    structures,
)
from .structure_relation import structure_relation, structure_relations

__all__ = [
    # The claims themselves, read back as claims
    "instance",
    "link",
    "standings",
    # The log itself (RFC 0020)
    "assertions",
    "assertion",
    "changes",
    "comment",
    "comments_for",
    "my_mentions",
    "my_mention_count",
    # Entity queries
    "entity",
    "node",
    "nodes",
    "entities",
    # Structure queries
    "structure",
    "description",
    "structures",
    "structure_by_identifier",
    "informing_structures",
    "terms",
    "term",
    "structure_kinds",
    "structure_kind",
    "metric_kinds",
    "metric_kind",
    # Edge queries
    "measurement",
    "measurements",
    "relation",
    "relations",
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
    # Insight render queries
    "render_graph_table",
    "render_table_plan",
    "render_graph_pairs",
]
