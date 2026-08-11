"""Reading an aggregation out of a state vector.

Pure functions, no database. Every one of them takes the sufficient statistics
kept in :class:`evidence.models.State` and returns a scalar, which is what makes
changing a property's aggregation a *read-side reinterpretation*: MEAN and MAX
consult the same row and neither is stored, so the swap costs zero writes and
zero backfill. That is the claim ``test_aggregation_reinterpret`` exists to
check.

Replaces the Cypher builders in the old ``rollup.py``, including its
``EUCLIDEAN_RANGE`` query, which used the `^` operator — not valid in Apache AGE,
so that aggregation could never have run at all.
"""

from __future__ import annotations

import math
from typing import Any, Protocol

from graph_engine.input_models import AggregationFunction, DerivationRuleInput


class StateVector(Protocol):
    """The statistics an aggregation reads.

    A protocol rather than the Django model so these functions stay testable
    without a database, and so a future in-memory fold can satisfy them too.
    """

    n: int
    sum: float | None
    min: float | None
    max: float | None
    first_value: Any
    last_value: Any


def _as_point(value: Any) -> list[float]:
    """Coerce a stored value into a point for distance maths."""
    if isinstance(value, dict):
        # Points used to be written as {x, y, z} objects.
        return [float(value[axis]) for axis in ("x", "y", "z") if axis in value]
    if isinstance(value, (list, tuple)):
        return [float(component) for component in value]
    raise TypeError(f"EUCLIDEAN_RANGE needs a point value, got {type(value).__name__}")


def mean(state: StateVector) -> float | None:
    """Arithmetic mean. None when nothing has been measured."""
    if not state.n or state.sum is None:
        return None
    return state.sum / state.n


def euclidean_range(state: StateVector) -> float | None:
    """Straight-line distance between the first and last measured points.

    Dimension-agnostic, unlike the query it replaces, which hardcoded x/y/z and
    would have failed on a 2D or N-dimensional vector.
    """
    if state.first_value is None or state.last_value is None:
        return None

    first, last = _as_point(state.first_value), _as_point(state.last_value)
    if len(first) != len(last):
        raise ValueError(f"Cannot measure distance between {len(first)}D and {len(last)}D points")
    return math.dist(first, last)


def value_range(state: StateVector) -> float | None:
    """Max minus min."""
    if state.min is None or state.max is None:
        return None
    return state.max - state.min


AGGREGATIONS = {
    AggregationFunction.MEAN: mean,
    AggregationFunction.SUM: lambda state: state.sum if state.n else None,
    AggregationFunction.MIN: lambda state: state.min,
    AggregationFunction.MAX: lambda state: state.max,
    AggregationFunction.COUNT: lambda state: state.n,
    AggregationFunction.RANGE: value_range,
    AggregationFunction.EUCLIDEAN_RANGE: euclidean_range,
    AggregationFunction.LATEST: lambda state: state.last_value,
}


def apply(aggregation: AggregationFunction, state: StateVector | None) -> Any:
    """Read one aggregation out of a state vector.

    ``None`` for a missing row means "no evidence", which every aggregation
    reports the same way — including COUNT, where zero would be a claim that
    somebody looked and found nothing.
    """
    if state is None:
        return None

    function = AGGREGATIONS.get(aggregation)
    if function is None:
        raise ValueError(f"Unsupported aggregation function: {aggregation}")
    return function(state)


# Aggregations that cannot be un-merged when a metric is retracted, because the
# statistic they read is order- or extremum-dependent and the contribution being
# removed may be the one that set it. SUM/COUNT/MEAN are group operations and
# subtract cleanly; these need a scoped recompute from the surviving metrics.
ORDER_DEPENDENT = frozenset(
    {
        AggregationFunction.MIN,
        AggregationFunction.MAX,
        AggregationFunction.RANGE,
        AggregationFunction.LATEST,
        AggregationFunction.EUCLIDEAN_RANGE,
    }
)


class UnsupportedRule(ValueError):
    """A derivation rule the state vector's grain cannot express."""


def validate_rule(rule: DerivationRuleInput, forbidden_sources: set[str] | None = None) -> None:
    """Reject rules the state vector cannot compute, at schema-validation time.

    The grain is `(entity, source_category, key)` over *metrics*, reached through
    ``(Metric)-[DESCRIBES]->(Structure)-[INFORMS]->(Entity)``. A rule naming an
    entity or event kind as its source is asking to count related nodes, which is
    a graph cardinality question rather than a fold over measured values: there
    is no sum, no min, no max, and it would have to be maintained when entities
    are created rather than when metrics arrive.

    Such rules used to be accepted and then render as ``WHERE m.key = null``,
    which never matches — so the property silently stayed unset and any test
    asserting on it passed vacuously. Saying no here is the whole point.
    """
    if rule.aggregation is None:
        raise UnsupportedRule("A rollup rule must name an aggregation function")

    if not rule.key:
        raise UnsupportedRule(f"Rollup over '{rule.source_node}' with aggregation {rule.aggregation.value} names no metric key. A rollup folds measurements, so it has to say which measurement.")

    # A positive list of structure kinds cannot be checked here: structures are
    # resolved dynamically at write time and a schema never enumerates them. The
    # caller passes the *entity and event* kinds it does know about, which is the
    # mistake worth catching.
    if rule.source_node and forbidden_sources and rule.source_node in forbidden_sources:
        raise UnsupportedRule(
            f"Rollup source '{rule.source_node}' is an entity or event kind, not a structure kind. "
            f"Derived properties aggregate measurements reaching an entity through a structure; "
            f"counting or summarising *related entities or events* is not expressible, and is "
            f"rejected here rather than silently never computing."
        )
