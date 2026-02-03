"""
Graph Engine Package

A synchronous, atomic, provenance-aware graph engine using Apache AGE and Pydantic V2.

Note: Models (GraphSchemaDefinition) are imported from graph_engine.models directly
to avoid circular import issues during Django app loading.
"""


# Lazy imports to avoid circular import during Django app loading
def get_controller():
    from .controller import GraphController
    return GraphController


def get_rollup_utils():
    from .rollup import (
        build_property_query,
        build_rollup_query,
        build_rollup_aggregation_query,
        build_rollup_latest_query,
        build_rollup_range_query,
        RollupQuery,
    )
    return {
        "build_property_query": build_property_query,
        "build_rollup_query": build_rollup_query,
        "build_rollup_aggregation_query": build_rollup_aggregation_query,
        "build_rollup_latest_query": build_rollup_latest_query,
        "build_rollup_range_query": build_rollup_range_query,
        "RollupQuery": RollupQuery,
    }


def get_retrieved_types():
    from .retrieved import (
        RetrievedNode,
        RetrievedEdge,
        RetrievedVariable,
        node_from_age_result,
        edge_from_age_result,
    )
    return {
        "RetrievedNode": RetrievedNode,
        "RetrievedEdge": RetrievedEdge,
        "RetrievedVariable": RetrievedVariable,
        "node_from_age_result": node_from_age_result,
        "edge_from_age_result": edge_from_age_result,
    }


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
    "get_schema_migration",
    "get_mutations",
    "get_rollup_utils",
    "get_retrieved_types",
]