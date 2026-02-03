"""
Graph Engine Package

A synchronous, atomic, provenance-aware graph engine using Apache AGE and Pydantic V2.

Note: Models (GraphSchemaDefinition) are imported from graph_engine.models directly
to avoid circular import issues during Django app loading.
"""
from .types import (
    GraphOperation,
    NodeChangeModel,
    EdgeChangeModel,
    ProvenanceModel,
    GraphMutationPayload,
    GraphMutationResult,
    NodeResult,
    EdgeResult,
)

# Lazy imports to avoid circular import during Django app loading
def get_controller():
    from .controller import GraphController
    return GraphController

def get_migration_controller():
    from .migration import MigrationController
    return MigrationController

def get_schema_migration():
    from .schema_migration import generate_schema_migration, apply_migration, SchemaMigrationPlan
    return generate_schema_migration, apply_migration, SchemaMigrationPlan

def get_mutations():
    from .mutations import perform_graph_mutation, run_graph_migration
    return perform_graph_mutation, run_graph_migration

__all__ = [
    # Types
    "GraphOperation",
    "NodeChangeModel",
    "EdgeChangeModel",
    "ProvenanceModel",
    "GraphMutationPayload",
    "GraphMutationResult",
    "NodeResult",
    "EdgeResult",
    # Lazy loaders
    "get_controller",
    "get_migration_controller",
    "get_schema_migration",    "get_mutations",
]