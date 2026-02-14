"""
Queries submodule for the API.

Contains all GraphQL query resolvers for the graph engine.
"""

from .entity import entity, entities_informed_by, entities
from .structure import structure, informing_structures
from .metric import metrics_for_structure, metric
from .assertion import assertion_for_entity

__all__ = [
    "Query",
    # Entity queries
    "entity",
    "entities",
    "entities_informed_by",
    # Structure queries
    "structure",
    "informing_structures",
    # Metric queries
    "metrics_for_structure",
    "metrics_for_assertion",
    "metric",
    # Assertion queries
    "assertion_for_entity",
]
