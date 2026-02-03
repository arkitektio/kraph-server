"""
Graph Engine API Module

A top-level Strawberry GraphQL API for the graph engine,
exposing types, queries, mutations, and subscriptions for interacting with
the provenance-aware graph database.

The API is designed around three core concepts:
1. Entities - Domain objects with derived properties
2. Structures - Evidence sources that inform entities  
3. Measurements - Data points attached to structures

Uses strawberry-pydantic for input validation against Pydantic models.
"""

from .types import (
    # Core Response Types
    Entity,
    Structure,
    Measurement,
    Assertion,
    NaturalEvent,
    # Rich Property Type
    RichProperty,
    # Aggregate Types
    EntityConnection,
    StructureConnection,
    MeasurementConnection,
)

from .inputs import (
    # Pydantic-validated inputs
    MeasurementInputType,
    StructureReferenceInputType,
    ProvenanceInputType,
    EntityCreationInputType,
    StructureCreationInputType,
    AddMeasurementInputType,
    LinkStructureInputType,
)

from .queries import Query
from .mutations import Mutation
from .subscriptions import Subscription
from .schema import schema, create_schema

__all__ = [
    # Types
    "Entity",
    "Structure",
    "Measurement",
    "Assertion",
    "NaturalEvent",
    "RichProperty",
    "EntityConnection",
    "StructureConnection", 
    "MeasurementConnection",
    # Inputs (Pydantic-validated)
    "MeasurementInputType",
    "StructureReferenceInputType",
    "ProvenanceInputType",
    "EntityCreationInputType",
    "StructureCreationInputType",
    "AddMeasurementInputType",
    "LinkStructureInputType",
    # Schema components
    "Mutation",
    "Query",
    "Subscription",
    "schema",
    "create_schema",
]
