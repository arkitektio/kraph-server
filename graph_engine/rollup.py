"""
Rollup query generation utilities.

This module provides functions to generate Cypher queries for computing
derived properties from measurements on connected structures.
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any

from graph_engine.base_models import (
    AggregationFunction,
    DerivationType,
    PropertyDefinition,
    DerivationRule,
)
from graph_engine import vocab


# Map aggregation functions to their Cypher equivalents
CYPHER_AGGREGATION_MAP: Dict[AggregationFunction, str] = {
    AggregationFunction.MEAN: "avg",
    AggregationFunction.SUM: "sum",
    AggregationFunction.MIN: "min",
    AggregationFunction.MAX: "max",
    AggregationFunction.COUNT: "count",
}


@dataclass
class RollupQuery:
    """Container for a rollup query and its parameters."""

    query: str
    params: Dict[str, Any]


def build_rollup_aggregation_query(
    entity_label: str,
    rule: DerivationRule,
) -> RollupQuery:
    """
    Build a Cypher query for standard aggregation functions (MEAN, SUM, MIN, MAX, COUNT).

    Pattern: Entity <- INFORMS - Structure <- DESCRIBES - Measurement

    Args:
        entity_label: The label of the entity node (e.g., "AIS", "Cell")
        rule: The derivation rule containing source_node, key, and aggregation

    Returns:
        RollupQuery with the Cypher query and base parameters
    """
    if not rule.aggregation:
        raise ValueError("Aggregation function must be specified for rollup rule")
    agg_func = CYPHER_AGGREGATION_MAP.get(rule.aggregation, None)
    if not agg_func:
        raise ValueError(f"Unsupported aggregation function: {rule.aggregation}")

    # COUNT aggregates the measurement node itself, others aggregate the value
    target_var = "m" if rule.aggregation == AggregationFunction.COUNT else "m.value"

    query = f"""
        MATCH (e:{entity_label}) WHERE id(e) = $eid
        MATCH (s:{rule.source_node})-[:{vocab.INFORMS}]->(e)
        MATCH (m:{vocab.Metric})-[:{vocab.DESCRIBES}]->(s)
        WHERE m.key = $key
        RETURN {agg_func}({target_var}) as val
    """

    params = {"key": rule.key}
    return RollupQuery(query=query, params=params)


def build_rollup_latest_query(
    entity_label: str,
    rule: DerivationRule,
) -> RollupQuery:
    """
    Build a Cypher query for LATEST aggregation (most recent by timestamp).

    Pattern: Entity <- INFORMS - Structure <- DESCRIBES - Measurement (ordered by timestamp)

    Args:
        entity_label: The label of the entity node
        rule: The derivation rule containing source_node and key

    Returns:
        RollupQuery with the Cypher query and base parameters
    """
    query = f"""
        MATCH (e:{entity_label}) WHERE id(e) = $eid
        MATCH (s:{rule.source_node})-[:{vocab.INFORMS}]->(e)
        MATCH (m:{vocab.Metric})-[:{vocab.DESCRIBES}]->(s)
        WHERE m.key = $key
        RETURN m.value as val
        ORDER BY m.timestamp DESC
        LIMIT 1
    """

    params = {"key": rule.key}
    return RollupQuery(query=query, params=params)


def build_rollup_range_query(
    entity_label: str,
    rule: DerivationRule,
) -> RollupQuery:
    """
    Build a Cypher query for RANGE aggregation (max - min).

    Used for computing temporal ranges or numeric spans.

    Args:
        entity_label: The label of the entity node
        rule: The derivation rule containing source_node and key

    Returns:
        RollupQuery with the Cypher query and base parameters
    """
    query = f"""
        MATCH (e:{entity_label}) WHERE id(e) = $eid
        MATCH (s:{rule.source_node})-[:{vocab.INFORMS}]->(e)
        MATCH (m:{vocab.Metric})-[:{vocab.DESCRIBES}]->(s)
        WHERE m.key = $key
        RETURN max(m.value) - min(m.value) as val
    """

    params = {"key": rule.key}
    return RollupQuery(query=query, params=params)


def build_rollup_euclidean_range_query(
    entity_label: str,
    rule: DerivationRule,
) -> RollupQuery:
    """
    Build a Cypher query for EUCLIDEAN_RANGE aggregation.

    Computes the Euclidean distance between the first and last point values.
    Note: This requires point values to be stored as objects with x, y, z properties.

    Args:
        entity_label: The label of the entity node
        rule: The derivation rule containing source_node and key

    Returns:
        RollupQuery with the Cypher query and base parameters
    """
    # This query gets first and last points and computes distance
    # AGE doesn't have native point distance, so we compute manually
    query = f"""
        MATCH (e:{entity_label}) WHERE id(e) = $eid
        MATCH (s:{rule.source_node})-[:{vocab.INFORMS}]->(e)
        MATCH (m:{vocab.Metric})-[:{vocab.DESCRIBES}]->(s)
        WHERE m.key = $key
        WITH m ORDER BY m.timestamp ASC
        WITH collect(m.value) as points
        WITH points[0] as first_pt, points[size(points)-1] as last_pt
        RETURN sqrt(
            (last_pt.x - first_pt.x)^2 + 
            (last_pt.y - first_pt.y)^2 + 
            (last_pt.z - first_pt.z)^2
        ) as val
    """

    params = {"key": rule.key}
    return RollupQuery(query=query, params=params)


def build_derivation_latest_query(
    entity_label: str,
    source_node: str,
    key: str,
) -> RollupQuery:
    """
    Build a Cypher query for LATEST derivation type (not ROLLUP with LATEST aggregation).

    This is for scalar properties that come directly from a single most-recent measurement.
    Pattern: Entity <- INFORMS - Structure <- DESCRIBES - Measurement

    Args:
        entity_label: The label of the entity node
        source_node: The structure type to read from
        key: The measurement key to look for

    Returns:
        RollupQuery with the Cypher query and base parameters
    """
    query = f"""
        MATCH (e:{entity_label}) WHERE id(e) = $eid
        MATCH (s:{source_node})-[:{vocab.INFORMS}]->(e)
        MATCH (m:{vocab.Metric})-[:{vocab.DESCRIBES}]->(s)
        WHERE m.key = $key
        RETURN m.value as val
        ORDER BY m.timestamp DESC
        LIMIT 1
    """

    params = {"key": key}
    return RollupQuery(query=query, params=params)


def build_rollup_query(
    entity_label: str,
    rule: DerivationRule,
) -> RollupQuery:
    """
    Build the appropriate rollup query based on the aggregation function.

    This is the main entry point for generating rollup queries.

    Args:
        entity_label: The label of the entity node
        rule: The derivation rule from the property definition

    Returns:
        RollupQuery with the Cypher query and base parameters

    Raises:
        ValueError: If the aggregation function is not supported
    """
    if rule.aggregation is None:
        raise ValueError("Rollup rule must have an aggregation function")

    if rule.aggregation == AggregationFunction.LATEST:
        return build_rollup_latest_query(entity_label, rule)
    elif rule.aggregation == AggregationFunction.RANGE:
        return build_rollup_range_query(entity_label, rule)
    elif rule.aggregation == AggregationFunction.EUCLIDEAN_RANGE:
        return build_rollup_euclidean_range_query(entity_label, rule)
    elif rule.aggregation in CYPHER_AGGREGATION_MAP:
        return build_rollup_aggregation_query(entity_label, rule)
    else:
        raise ValueError(f"Unsupported aggregation function: {rule.aggregation}")


def build_property_query(
    entity_label: str,
    prop_name: str,
    prop_def: PropertyDefinition,
) -> Optional[RollupQuery]:
    """
    Build the appropriate query for a property based on its derivation type.

    Args:
        entity_label: The label of the entity node
        prop_name: The name of the property (used as default key for LATEST)
        prop_def: The property definition from the schema

    Returns:
        RollupQuery if the property is derived, None if it's a static property

    Raises:
        ValueError: If the derivation configuration is invalid
    """
    if prop_def.derivation == DerivationType.ROLLUP:
        if not prop_def.rule:
            raise ValueError(f"Property '{prop_name}' has ROLLUP derivation but no rule")
        return build_rollup_query(entity_label, prop_def.rule)

    elif prop_def.derivation == DerivationType.LATEST:
        # LATEST derivation gets the most recent measurement value
        source_node = "Structure"  # Default
        key = prop_name  # Default to property name

        if prop_def.rule:
            if prop_def.rule.source_node:
                source_node = prop_def.rule.source_node
            if prop_def.rule.key:
                key = prop_def.rule.key

        return build_derivation_latest_query(entity_label, source_node, key)

    elif prop_def.derivation == DerivationType.PRIORITY_LATEST:
        # Same as LATEST for now, could be extended with priority logic
        source_node = "Structure"
        key = prop_name

        if prop_def.rule:
            if prop_def.rule.source_node:
                source_node = prop_def.rule.source_node
            if prop_def.rule.key:
                key = prop_def.rule.key

        return build_derivation_latest_query(entity_label, source_node, key)

    elif prop_def.derivation == DerivationType.LATEST_ASSERTION_TOOL:
        # This would need special handling for tool-based assertions
        # For now, fall back to LATEST behavior
        source_node = "Structure"
        key = prop_name

        if prop_def.rule:
            if prop_def.rule.source_node:
                source_node = prop_def.rule.source_node
            if prop_def.rule.key:
                key = prop_def.rule.key

        return build_derivation_latest_query(entity_label, source_node, key)

    else:
        raise ValueError(f"Unsupported derivation type: {prop_def.derivation}")
