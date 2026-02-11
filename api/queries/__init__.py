"""
Queries submodule for the API.

Contains all GraphQL query resolvers for the graph engine.
"""

from .root import Query
from .entity import entity, entities_informed_by
from .structure import structure, informing_structures
from .metric import metrics_for_structure
from .assertion import assertion_for_entity

__all__ = [
    "Query",
    # Entity queries
    "entity",
    "entities_informed_by",
    # Structure queries
    "structure",
    "informing_structures",
    # Metric queries
    "metrics_for_structure",
    "metrics_for_assertion",
    # Assertion queries
    "assertion_for_entity",
]
