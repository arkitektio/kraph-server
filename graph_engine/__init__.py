"""
Graph Engine Package

A synchronous, provenance-aware graph engine over Apache AGE and Pydantic V2.

Evidence — structures, metrics, assertions — lives in the `evidence` app, not
here. This package owns the *projection*: turning that evidence into an AGE graph
and reading it back.

Imports are deferred inside functions to avoid circular imports during Django app
loading.
"""


def get_controller():
    """The graph controller class, imported lazily."""
    from .controller import GraphController

    return GraphController


def get_retrieved_types():
    """The node/edge wrapper types, imported lazily."""
    from .retrieved import RetrievedEdge, RetrievedNode, RetrievedVariable

    return {
        "RetrievedNode": RetrievedNode,
        "RetrievedEdge": RetrievedEdge,
        "RetrievedVariable": RetrievedVariable,
    }


def get_aggregations():
    """The state-vector aggregation functions, imported lazily."""
    from .aggregate import AGGREGATIONS, apply

    return {"apply": apply, "AGGREGATIONS": AGGREGATIONS}


__all__ = [
    "get_controller",
    "get_retrieved_types",
    "get_aggregations",
]
