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
    Metric,
    Reagent,
    ProtocolEvent,
    Relation,
    StructureRelation,
    # Rich Property Type
    RichProperty,
    Property,
    # Aggregate Types
    EntityConnection,
    StructureConnection,
    MeasurementConnection,
    NodeConnection,
    EdgeConnection,
    # Base Interfaces
    Node,
    VersionedNode,
    Edge,
    # Type Matching Functions
    node_to_subtype,
    edge_to_subtype,
    NodeSubtype,
    EdgeSubtype,
)

from .inputs import (
    # Pydantic-validated inputs
    MeasurementInput,
    StructureReferenceInput,
    ProvenanceInput,
    EntityCreationInput,
    StructureCreationInput,
    RelationCreationInput,
    AddMeasurementInput,
    LinkStructureInput,
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
    "Metric",
    "Reagent",
    "ProtocolEvent",
    "Relation",
    "StructureRelation",
    "RichProperty",
    "Property",
    # Connections
    "EntityConnection",
    "StructureConnection", 
    "MeasurementConnection",
    "NodeConnection",
    "EdgeConnection",
    # Base Interfaces
    "Node",
    "VersionedNode",
    "Edge",
    # Type Matching
    "node_to_subtype",
    "edge_to_subtype",
    "NodeSubtype",
    "EdgeSubtype",
    # Inputs (Pydantic-validated)
    "MeasurementInput",
    "StructureReferenceInput",
    "ProvenanceInput",
    "EntityCreationInput",
    "StructureCreationInput",
    "RelationCreationInput",
    "AddMeasurementInput",
    "LinkStructureInput",
    # Schema components
    "Mutation",
    "Query",
    "Subscription",
    "schema",
    "create_schema",
]
