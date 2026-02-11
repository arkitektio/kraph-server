"""
Mutations submodule for the API.

Contains all GraphQL mutation resolvers for the graph engine.
"""

from .root import Mutation
from .entity import create_entity, recalculate_entity
from .structure import create_structure, link_structure_to_entity
from .metric import create_metric, delete_metric, archive_metric
from .relation import create_relation

__all__ = [
    "Mutation",
    # Entity mutations
    "create_entity",
    "recalculate_entity",
    # Structure mutations
    "create_structure",
    "link_structure_to_entity",
    # Metric mutations
    "add_metric",
    # Relation mutations
    "create_relation",
]
