"""
Mutations submodule for the API.

Contains all GraphQL mutation resolvers for the graph engine.
"""
from .root import Mutation
from .entity import create_entity, recalculate_entity
from .structure import create_structure, link_structure_to_entity
from .measurement import add_measurement
from .relation import create_relation
from .schema import validate_schema, set_schema, activate_schema

__all__ = [
    "Mutation",
    # Entity mutations
    "create_entity",
    "recalculate_entity",
    # Structure mutations
    "create_structure",
    "link_structure_to_entity",
    # Measurement mutations
    "add_measurement",
    # Relation mutations
    "create_relation",
    # Schema mutations
    "validate_schema",
    "set_schema",
    "activate_schema",
]
