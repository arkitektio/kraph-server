"""
Graph Engine Package

A synchronous, provenance-aware graph engine over Postgres projection tables and Pydantic V2.

Evidence — structures, metrics, assertions — lives in the `evidence` app, not
here. This package owns the *projection*: turning that evidence into each view's drawing
and reading it back.

Imports are deferred inside functions to avoid circular imports during Django app
loading.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from evidence.values import JSONValue

    from .aggregate import StateVector
    from .controller import GraphController
    from .input_models import AggregationFunction
    from .retrieved import RetrievedEdge, RetrievedNode, RetrievedVariable


def get_controller() -> "type[GraphController]":
    """The graph controller class, imported lazily."""
    from .controller import GraphController

    return GraphController


def get_retrieved_types() -> (
    "dict[str, type[RetrievedNode] | type[RetrievedEdge] | type[RetrievedVariable]]"
):
    """The node/edge wrapper types, imported lazily."""
    from .retrieved import RetrievedEdge, RetrievedNode, RetrievedVariable

    return {
        "RetrievedNode": RetrievedNode,
        "RetrievedEdge": RetrievedEdge,
        "RetrievedVariable": RetrievedVariable,
    }


def get_aggregations() -> (
    "dict[str, Callable[[AggregationFunction, StateVector | None], JSONValue] | dict[AggregationFunction, Callable[[StateVector], JSONValue]]]"
):
    """The state-vector aggregation functions, imported lazily."""
    from .aggregate import AGGREGATIONS, apply

    return {"apply": apply, "AGGREGATIONS": AGGREGATIONS}


__all__ = [
    "get_controller",
    "get_retrieved_types",
    "get_aggregations",
]
