from asyncio import Protocol
from enum import Enum
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import List, Dict, Optional, Any, Literal
from datetime import datetime, timezone
import re

import strawberry
from strawberry_django import Ordering

from datalayer.scalars import MediaStore, MediaStoreLike
from graph_engine.scalars import GraphID
from graph_engine import scalars
from core import enums
# --- Enums for Strict Typing ---


class DerivationType(str, Enum):
    # Standard: User/Tool sets it directly
    LATEST = "LATEST"
    PRIORITY_LATEST = "PRIORITY_LATEST"

    # Computed: Calculated from children/neighbors
    ROLLUP = "ROLLUP"
    LATEST_ASSERTION_TOOL = "LATEST_ASSERTION_TOOL"


class AggregationFunction(str, Enum):
    MEAN = "MEAN"
    SUM = "SUM"
    MAX = "MAX"
    MIN = "MIN"
    COUNT = "COUNT"
    RANGE = "RANGE"  # Max - Min (Temporal)
    EUCLIDEAN_RANGE = "EUCLIDEAN_RANGE"  # Distance between First & Last
    LATEST = "LATEST"  # Grab the most recent child value


class PropertyType(str, Enum):
    STRING = "string"
    FLOAT = "float"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    DATETIME = "datetime"
    POINT_3D = "point_3d"


class Action(str, Enum):
    AUTO_ADD_STRUCTURES = "AUTO_ADD_STRUCTURES"
    AUTO_ADD_STRUCTURE_DEFINITIONS = "AUTO_ADD_STRUCTURE_DEFINITIONS"
    AUTO_ADD_METRICS = "AUTO_ADD_METRICS"
    ADD_STRUCTURE_DEFINITIONS = "ADD_STRUCTURE_DEFINITIONS"
    ADD_ENTITY_DEFINITIONS = "ADD_ENTITY_DEFINITIONS"
    ADD_RELATION_DEFINITIONS = "ADD_RELATION_DEFINITIONS"
    CREATE_BUILDER_ARG = "CREATE_BUILDER_ARG"


class WhereOperator(str, Enum):
    EQUALS = "EQUALS"
    NOT_EQUALS = "NOT_EQUALS"
    GREATER_THAN = "GREATER_THAN"
    LESS_THAN = "LESS_THAN"
    GREATER_OR_EQUAL = "GREATER_OR_EQUAL"
    LESS_OR_EQUAL = "LESS_OR_EQUAL"
    IN = "IN"
    NOT_IN = "NOT_IN"
    CONTAINS = "CONTAINS"
    STARTS_WITH = "STARTS_WITH"
    ENDS_WITH = "ENDS_WITH"


# --- Type compatibility mappings for aggregations ---

# Aggregations that require numeric source types
NUMERIC_AGGREGATIONS = {
    AggregationFunction.MEAN,
    AggregationFunction.SUM,
    AggregationFunction.MIN,
    AggregationFunction.MAX,
}

# Aggregations that work with any type
ANY_TYPE_AGGREGATIONS = {
    AggregationFunction.COUNT,
    AggregationFunction.LATEST,
}

# Property types considered numeric
NUMERIC_TYPES = {
    PropertyType.FLOAT,
    PropertyType.INTEGER,
}

# Map aggregation -> required source types (None means any type allowed)
AGGREGATION_SOURCE_TYPES: Dict[AggregationFunction, Optional[set]] = {
    AggregationFunction.MEAN: NUMERIC_TYPES,
    AggregationFunction.SUM: NUMERIC_TYPES,
    AggregationFunction.MIN: NUMERIC_TYPES | {PropertyType.DATETIME},
    AggregationFunction.MAX: NUMERIC_TYPES | {PropertyType.DATETIME},
    AggregationFunction.COUNT: None,  # Any type
    AggregationFunction.LATEST: None,  # Any type
    AggregationFunction.RANGE: NUMERIC_TYPES | {PropertyType.DATETIME},
    AggregationFunction.EUCLIDEAN_RANGE: {PropertyType.POINT_3D},
}

# Map aggregation -> result type (None means same as source)
AGGREGATION_RESULT_TYPES: Dict[AggregationFunction, Optional[PropertyType]] = {
    AggregationFunction.MEAN: PropertyType.FLOAT,  # Mean always produces float
    AggregationFunction.SUM: None,  # Same as source (int->int, float->float)
    AggregationFunction.MIN: None,  # Same as source
    AggregationFunction.MAX: None,  # Same as source
    AggregationFunction.COUNT: PropertyType.INTEGER,  # Count produces integer
    AggregationFunction.LATEST: None,  # Same as source
    AggregationFunction.RANGE: PropertyType.FLOAT,  # Range produces float (for datetime too)
    AggregationFunction.EUCLIDEAN_RANGE: PropertyType.FLOAT,  # Distance is float
}

# --- 1. Property & Derivation Rules ---


class DerivationRule(BaseModel):
    """
    Configuration for how to calculate a value if derivation != LATEST.
    """

    source_node: Optional[str] = Field(..., description="The label of the the describing structure to read from.")
    key: Optional[str] = Field(..., description="The property key on the source node.")
    aggregation: Optional[AggregationFunction] = None


# =======================
# TEXT MODELS
# =======================
class PlateChildInput(BaseModel):
    id: str
    type: str | None = None
    text: str | None = None
    children: list["PlateChildInput"] | None = None
    value: str | None = None
    color: str | None = None
    font_size: str | None = None
    background_color: str | None = None
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None


# ==========================================
# FILTER MODELS FOR NON MODELS
# ==========================================


class RenderGraphNodesFilter(BaseModel):
    key: str
    operator: str
    value: scalars.AnyScalar


class RenderGraphNodesPagination(BaseModel):
    limit: int
    offset: int


class RenderGraphNodesOrder(BaseModel):
    key: str
    direction: str = "asc"


class RenderGraphPathFilter(BaseModel):
    key: str
    operator: str
    value: scalars.AnyScalar


class RenderGraphPathPagination(BaseModel):
    limit: int
    offset: int


class RenderGraphPathOrder(BaseModel):
    key: str
    direction: str = "asc"


class RenderGraphPairsFilter(BaseModel):
    key: str
    operator: str
    value: scalars.AnyScalar


class RenderGraphPairsPagination(BaseModel):
    limit: int
    offset: int


class RenderGraphPairsOrder(BaseModel):
    key: str
    direction: str = "asc"


class RenderGraphTableFilter(BaseModel):
    key: str
    operator: str
    value: scalars.AnyScalar


class RenderGraphTablePagination(BaseModel):
    limit: int
    offset: int


class RenderGraphTableOrder(BaseModel):
    key: str
    direction: str = "asc"


# ==========================================
# SCHEMA INPUT MODELS
# ==========================================


class PropertyMatch(BaseModel):
    """A property match"""

    key: str = Field(description="The property matching")
    operator: WhereOperator = Field(description="The operator to use")
    value: scalars.AnyScalar = Field(description="THe value to filter agains")


class EntityFilters(BaseModel):
    graph: Optional[strawberry.ID] = Field(default=None, description="Filter by graph ID")
    category: Optional[str] = Field(default=None, description="Filter by entity kind/type")
    ids: Optional[List[scalars.GraphID]] = Field(default=None, description="Filter by specific entity IDs")
    has_property: Optional[str] = Field(default=None, description="Filter entities that have a specific property")
    search: Optional[str] = Field(default=None, description="Full-text search over entity properties")
    matches: Optional[List[PropertyMatch]] = Field(default=None, description="Filter entities that match specific property conditions")


class EntityPagination(BaseModel):
    offset: Optional[int] = Field(default=0, description="Number of items to skip")
    limit: Optional[int] = Field(default=100, description="Maximum number of items to return")


class StructureFilters(BaseModel):
    graph: Optional[strawberry.ID] = Field(default=None, description="Filter by graph ID")
    category: Optional[str] = Field(default=None, description="Filter by structure kind/type")
    ids: Optional[List[scalars.GraphID]] = Field(default=None, description="Filter by specific structure IDs")
    has_property: Optional[str] = Field(default=None, description="Filter structures that have a specific property")
    search: Optional[str] = Field(default=None, description="Full-text search over structure properties")
    matches: Optional[List[PropertyMatch]] = Field(default=None, description="Filter structures that match specific property conditions")


class StructurePagination(BaseModel):
    offset: Optional[int] = Field(default=0, description="Number of items to skip")
    limit: Optional[int] = Field(default=100, description="Maximum number of items to return")


class PropertyOrder(BaseModel):
    key: str = Field(description="The property key to order by")
    direction: Ordering = Field(description="The direction to order (ASC or DESC)")


class EntityOrder(BaseModel):
    created_at: Optional[Ordering] = Field(default=None, description="Order by creation timestamp")
    category: Optional[Ordering] = Field(default=None, description="Order by entity kind/type")
    id: Optional[Ordering] = Field(default=None, description="Order by entity ID")
    property: Optional[PropertyOrder] = Field(default=None, description="Order by a specific property value (requires 'has_property' filter)")


class StructureOrder(BaseModel):
    created_at: Optional[Ordering] = Field(default=None, description="Order by creation timestamp")
    category: Optional[Ordering] = Field(default=None, description="Order by structure kind/type")
    id: Optional[Ordering] = Field(default=None, description="Order by structure ID")
    property: Optional[PropertyOrder] = Field(default=None, description="Order by a specific property value (requires 'has_property' filter)")


class MetricFilters(BaseModel):
    graph: Optional[strawberry.ID] = Field(default=None, description="Filter by graph ID")
    category: Optional[str] = Field(default=None, description="Filter by metric category ID")
    ids: Optional[List[scalars.GraphID]] = Field(default=None, description="Filter by specific metric IDs")
    has_property: Optional[str] = Field(default=None, description="Filter metrics that have a specific property")
    search: Optional[str] = Field(default=None, description="Full-text search over metric properties")
    matches: Optional[List[PropertyMatch]] = Field(default=None, description="Filter metrics that match specific property conditions")


class MetricPagination(BaseModel):
    offset: Optional[int] = Field(default=0, description="Number of items to skip")
    limit: Optional[int] = Field(default=100, description="Maximum number of items to return")


class MetricOrder(BaseModel):
    created_at: Optional[Ordering] = Field(default=None, description="Order by creation timestamp")
    category: Optional[Ordering] = Field(default=None, description="Order by metric category")
    id: Optional[Ordering] = Field(default=None, description="Order by metric ID")
    property: Optional[PropertyOrder] = Field(default=None, description="Order by a specific property value")


class NaturalEventFilters(BaseModel):
    graph: Optional[strawberry.ID] = Field(default=None, description="Filter by graph ID")
    category: Optional[str] = Field(default=None, description="Filter by natural event category ID")
    ids: Optional[List[scalars.GraphID]] = Field(default=None, description="Filter by specific natural event IDs")
    has_property: Optional[str] = Field(default=None, description="Filter natural events that have a specific property")
    search: Optional[str] = Field(default=None, description="Full-text search over natural event properties")
    matches: Optional[List[PropertyMatch]] = Field(default=None, description="Filter natural events that match specific property conditions")


class NaturalEventPagination(BaseModel):
    offset: Optional[int] = Field(default=0, description="Number of items to skip")
    limit: Optional[int] = Field(default=100, description="Maximum number of items to return")


class NaturalEventOrder(BaseModel):
    created_at: Optional[Ordering] = Field(default=None, description="Order by creation timestamp")
    category: Optional[Ordering] = Field(default=None, description="Order by natural event category")
    id: Optional[Ordering] = Field(default=None, description="Order by natural event ID")
    property: Optional[PropertyOrder] = Field(default=None, description="Order by a specific property value")


class ProtocolEventFilters(BaseModel):
    graph: Optional[strawberry.ID] = Field(default=None, description="Filter by graph ID")
    category: Optional[str] = Field(default=None, description="Filter by protocol event category ID")
    ids: Optional[List[scalars.GraphID]] = Field(default=None, description="Filter by specific protocol event IDs")
    has_property: Optional[str] = Field(default=None, description="Filter protocol events that have a specific property")
    search: Optional[str] = Field(default=None, description="Full-text search over protocol event properties")
    matches: Optional[List[PropertyMatch]] = Field(default=None, description="Filter protocol events that match specific property conditions")


class ProtocolEventPagination(BaseModel):
    offset: Optional[int] = Field(default=0, description="Number of items to skip")
    limit: Optional[int] = Field(default=100, description="Maximum number of items to return")


class ProtocolEventOrder(BaseModel):
    created_at: Optional[Ordering] = Field(default=None, description="Order by creation timestamp")
    category: Optional[Ordering] = Field(default=None, description="Order by protocol event category")
    id: Optional[Ordering] = Field(default=None, description="Order by protocol event ID")
    property: Optional[PropertyOrder] = Field(default=None, description="Order by a specific property value")


class MeasurementFilters(BaseModel):
    graph: Optional[strawberry.ID] = Field(default=None, description="Filter by graph ID")
    category: Optional[str] = Field(default=None, description="Filter by measurement category ID")
    ids: Optional[List[scalars.GraphID]] = Field(default=None, description="Filter by specific measurement IDs")
    has_property: Optional[str] = Field(default=None, description="Filter measurements that have a specific property")
    search: Optional[str] = Field(default=None, description="Full-text search over measurement properties")
    matches: Optional[List[PropertyMatch]] = Field(default=None, description="Filter measurements that match specific property conditions")


class MeasurementPagination(BaseModel):
    offset: Optional[int] = Field(default=0, description="Number of items to skip")
    limit: Optional[int] = Field(default=100, description="Maximum number of items to return")


class MeasurementOrder(BaseModel):
    created_at: Optional[Ordering] = Field(default=None, description="Order by creation timestamp")
    category: Optional[Ordering] = Field(default=None, description="Order by measurement category")
    id: Optional[Ordering] = Field(default=None, description="Order by measurement ID")
    property: Optional[PropertyOrder] = Field(default=None, description="Order by a specific property value")


class StructureRelationFilters(BaseModel):
    graph: Optional[strawberry.ID] = Field(default=None, description="Filter by graph ID")
    category: Optional[str] = Field(default=None, description="Filter by structure relation category ID")
    ids: Optional[List[scalars.GraphID]] = Field(default=None, description="Filter by specific structure relation IDs")
    has_property: Optional[str] = Field(default=None, description="Filter structure relations that have a specific property")
    search: Optional[str] = Field(default=None, description="Full-text search over structure relation properties")
    matches: Optional[List[PropertyMatch]] = Field(default=None, description="Filter structure relations that match specific property conditions")


class StructureRelationPagination(BaseModel):
    offset: Optional[int] = Field(default=0, description="Number of items to skip")
    limit: Optional[int] = Field(default=100, description="Maximum number of items to return")


class StructureRelationOrder(BaseModel):
    created_at: Optional[Ordering] = Field(default=None, description="Order by creation timestamp")
    category: Optional[Ordering] = Field(default=None, description="Order by structure relation category")
    id: Optional[Ordering] = Field(default=None, description="Order by structure relation ID")
    property: Optional[PropertyOrder] = Field(default=None, description="Order by a specific property value")


class RelationFilters(BaseModel):
    graph: Optional[strawberry.ID] = Field(default=None, description="Filter by graph ID")
    category: Optional[str] = Field(default=None, description="Filter by relation category ID")
    ids: Optional[List[scalars.GraphID]] = Field(default=None, description="Filter by specific relation IDs")
    has_property: Optional[str] = Field(default=None, description="Filter relations that have a specific property")
    search: Optional[str] = Field(default=None, description="Full-text search over relation properties")
    matches: Optional[List[PropertyMatch]] = Field(default=None, description="Filter relations that match specific property conditions")


class RelationPagination(BaseModel):
    offset: Optional[int] = Field(default=0, description="Number of items to skip")
    limit: Optional[int] = Field(default=100, description="Maximum number of items to return")


class RelationOrder(BaseModel):
    created_at: Optional[Ordering] = Field(default=None, description="Order by creation timestamp")
    category: Optional[Ordering] = Field(default=None, description="Order by relation category")
    id: Optional[Ordering] = Field(default=None, description="Order by relation ID")
    property: Optional[PropertyOrder] = Field(default=None, description="Order by a specific property value")


# ==========================================
# INPUT MODELS
# ==========================================


class MetricInput(BaseModel):
    """
    A single measurement entry.
    Timestamps are converted to Unix Epoch Milliseconds (int) for Apache AGE.
    """

    key: str
    value: Any
    confidence: Optional[float] = None
    confidence_type: Optional[str] = None
    unit: Optional[str] = None

    # Internal storage is int (ms), but accepts str/datetime inputs
    timestamp: Optional[int] = Field(None, description="Unix epoch time in milliseconds")

    @field_validator("timestamp", mode="before")
    def parse_timestamp(cls, v: Any) -> Optional[int]:
        """
        Converts ISO strings, datetime objects, or float seconds to Millisecond Epoch Int.
        """
        if v is None:
            return None

        # Case 1: Already an int (assume ms)
        if isinstance(v, int):
            return v

        # Case 2: Datetime object
        if isinstance(v, datetime):
            # Ensure timezone awareness (default to UTC if missing)
            if v.tzinfo is None:
                v = v.replace(tzinfo=timezone.utc)
            return int(v.timestamp() * 1000)

        # Case 3: ISO String
        if isinstance(v, str):
            try:
                # Handle 'Z' manually if python version < 3.11 for isoformat compatibility
                v = v.replace("Z", "+00:00")
                dt = datetime.fromisoformat(v)
                return int(dt.timestamp() * 1000)
            except ValueError:
                raise ValueError(f"Invalid timestamp format: {v}")

        raise ValueError(f"Unsupported timestamp type: {type(v)}")


def create_max_confidence_metric(key: str, value: Any, unit: Optional[str] = None, timestamp: Any = None) -> MetricInput:
    """Helper to create a measurement with max confidence"""
    return MetricInput(key=key, value=value, confidence=1.0, confidence_type="max", unit=unit, timestamp=timestamp)


class StructureReferenceInput(BaseModel):
    identifier: scalars.StructureIdentifier = Field(..., description="Schema identifier, e.g. '@mikro/roi'")
    object: scalars.StructureObject = Field(..., description="The unique ID of the object this structure references")
    metrics: List[MetricInput] = []


def create_told_you_so(metrics: List[MetricInput], object: str) -> StructureReferenceInput:
    return StructureReferenceInput(identifier="told_you_so", object=object, metrics=metrics)


class ProvenanceContext(BaseModel):
    subject: str = Field(..., description="User ID")
    app_id: str = Field(..., description="Client ID")
    action_id: Optional[str] = None
    action_name: Optional[str] = None
    action_args: Optional[Dict[str, Any]] = None

    @classmethod
    def bland(cls) -> "ProvenanceContext":
        """A bland provenance context for testing or when user info is not available."""
        return cls(subject="unknown", app_id="unknown")


# ==========================================
# SCHEMA MANAGEMENT MODELS
# ==========================================

# Semantic version regex: major.minor.patch with optional pre-release and build metadata
# Based on semver.org specification
SEMVER_REGEX = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"  # MAJOR.MINOR.PATCH
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"  # Pre-release (optional)
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"  # ... continued
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"  # Build metadata (optional)
)


def validate_semver(version: str) -> str:
    """Validate that a string is a valid semantic version."""
    if not SEMVER_REGEX.match(version):
        raise ValueError(f"'{version}' is not a valid semantic version. Expected format: MAJOR.MINOR.PATCH (e.g., '1.0.0', '2.1.3-beta.1')")
    return version


class SemanticVersion(str):
    """A semantic version string that validates on assignment."""

    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise TypeError("Semantic version must be a string")
        return validate_semver(v)


class SchemaValidationError(BaseModel):
    """A single validation error from schema validation."""

    location: List[str] = Field(default_factory=list, description="Path to the error location (e.g., ['extensions', 'entities', 'Neuron', 'properties', 'soma_volume'])")
    message: str = Field(..., description="Human-readable error message")
    type: str = Field(default="validation_error", description="Error type (e.g., 'missing_field', 'invalid_type', 'reference_error')")


class SchemaValidationResult(BaseModel):
    """Result of validating a schema."""

    is_valid: bool = Field(..., description="Whether the schema is valid")
    errors: List[SchemaValidationError] = Field(default_factory=list, description="List of validation errors if any")
    warnings: List[SchemaValidationError] = Field(default_factory=list, description="List of validation warnings (non-fatal issues)")


class OntologyReferenceInput(BaseModel):
    """Input for an ontology reference."""

    prefix: str = Field(..., description="The ontology prefix (e.g. 'OBI'). Must be defined in graph prefixes.")
    uri: str = Field(..., description="The full URI for the ontology term")


# --- Schema Definition Input Models ---
# These mirror the base_models but are used for input validation


class DerivationRuleInput(BaseModel):
    """Input for a derivation rule configuration."""

    source_node: Optional[str] = Field(default=None, description="The label of the describing structure to read from")
    key: Optional[str] = Field(default=None, description="The property key on the source node")
    aggregation: Optional[AggregationFunction] = Field(default=None, description="Aggregation function (MEAN, SUM, MAX, MIN, COUNT, etc.)")


class ColumnInput(BaseModel):
    key: str = Field(..., description="The property key for this column (inside the table query result)")
    type: str = Field(..., description="The property type for this column (e.g., STRING, FLOAT)")
    label: Optional[str] = Field(default=None, description="Optional human-readable label for this column (defaults to 'key' if not provided)")
    value_kind: Optional[enums.ValueKind] = Field(default=None, description="Whether this column represents a raw property value, a derived value, or a metric")
    unit: Optional[str] = Field(default=None, description="Unit of measurement if applicable")
    description: str | None = Field(default=None, description="Optional description for this column")
    category_key: Optional[str] = Field(default=None, description="Optional category/key for this column, used for grouping or filtering in the UI")
    searchable: bool = Field(default=False, description="Whether this column should be full-text searchable")
    is_id_for_key: Optional[str] = Field(default=None, description="If this column represents an ID that can be used to link to another table, specify the target table name here")
    prefer_hidden: bool = Field(default=False, description="Whether this column should be hidden by default in the UI, even if it's not an ID or metadata column")


class MatchPathInput(BaseModel):
    nodes: list[str] = Field(..., description="List of node IDs to match")
    relations: list[str] = Field(..., description="List of node IDs representing the path")
    optional: bool = Field(default=False, description="Whether the path match is optional")
    title: str | None = Field(default=None, description="Title for the matched path")
    color: list[float] | None = Field(default=None, description="Color for the matched path as RGB values")
    relation_directions: list[bool] | None = Field(
        default=None,
        description="List of booleans indicating the direction of each relationship in the path (True for outgoing, False for incoming)",
    )


class WhereClauseInput(BaseModel):
    path: str
    node: str | None = None
    property: str = Field(..., description="The property name to filter on")
    operator: WhereOperator = Field(..., description="The operator to use for filtering")
    value: scalars.CypherLiteral = Field(..., description="The value to compare against")


class ReturnStatementInput(BaseModel):
    path: str = Field(..., description="The path ID to return")
    node: str | None = Field(default=None, description="The node ID to return")
    property: str | None = Field(default=None, description="The property name to return")


class BuilderArgsInput(BaseModel):
    where_clauses: Optional[List[WhereClauseInput]] = Field(default=None, description="Optional filtering conditions for the graph query")
    match_paths: Optional[List[MatchPathInput]] = Field(default=None, description="Optional patterns to match in the graph for this query")
    return_statements: Optional[List[ReturnStatementInput]] = Field(default=None, description="The values to return for each matched pattern in the graph query")


class PropertyDefinitionInput(BaseModel):
    """Input for a property definition on a node or relation."""

    key: str = Field(..., description="Property key/name")
    value_kind: enums.ValueKind = strawberry.field(description="What type of value, (taking from the universe) 'QUANTITATIVE', 'QUALITATIVE', 'BOOLEAN'")
    unit: Optional[str] = Field(default=None, description="Unit of measurement")
    description: Optional[str] = Field(default=None, description="Description of this property")
    derivation: DerivationType = Field(default=DerivationType.LATEST, description="Derivation type: LATEST, PRIORITY_LATEST, ROLLUP, LATEST_ASSERTION_TOOL")
    rule: Optional[DerivationRuleInput] = Field(default=None, description="Rule configuration for ROLLUP derivation")
    index: bool = Field(default=False, description="Whether to create an index on this property for faster queries")
    searchable: bool = Field(default=False, description="Whether this property should be full-text searchable")

    @model_validator(mode="before")
    @classmethod
    def populate_value_kind_from_legacy_type(cls, data):
        if not isinstance(data, dict):
            return data

        if data.get("value_kind") is not None:
            return data

        legacy_type = data.get("type")
        if legacy_type is None:
            return data

        type_to_value_kind = {
            PropertyType.FLOAT: enums.ValueKind.FLOAT,
            PropertyType.INTEGER: enums.ValueKind.INT,
            PropertyType.DATETIME: enums.ValueKind.DATETIME,
            PropertyType.STRING: enums.ValueKind.STRING,
            PropertyType.BOOLEAN: enums.ValueKind.BOOLEAN,
            PropertyType.POINT_3D: enums.ValueKind.THREE_D_VECTOR,
        }

        if isinstance(legacy_type, str):
            try:
                legacy_type = PropertyType(legacy_type)
            except ValueError:
                return data

        mapped_value_kind = type_to_value_kind.get(legacy_type)
        if mapped_value_kind is None:
            return data

        normalized = data.copy()
        normalized["value_kind"] = mapped_value_kind
        return normalized

    @field_validator("derivation")
    @classmethod
    def validate_derivation(cls, v: str) -> str:
        valid_derivations = {"LATEST", "PRIORITY_LATEST", "ROLLUP", "LATEST_ASSERTION_TOOL"}
        if v.upper() not in valid_derivations:
            raise ValueError(f"Invalid derivation type '{v}'. Must be one of: {', '.join(valid_derivations)}")
        return v.upper()

    @model_validator(mode="after")
    def validate_rule_presence(self):
        """If using ROLLUP, a rule definition is mandatory."""
        if self.derivation == DerivationType.ROLLUP and not self.rule:
            raise ValueError("Property with derivation 'ROLLUP' must have a 'rule' configuration.")
        return self

    @model_validator(mode="after")
    def validate_aggregation_result_type(self):
        """
        Validate that the property type is compatible with the aggregation result.

        For example:
        - MEAN always produces FLOAT, so property type must be FLOAT
        - COUNT always produces INTEGER, so property type must be INTEGER
        - EUCLIDEAN_RANGE produces FLOAT (distance)
        """
        if self.derivation != DerivationType.ROLLUP or not self.rule or not self.rule.aggregation:
            return self

        aggregation = self.rule.aggregation
        expected_result_type = AGGREGATION_RESULT_TYPES.get(aggregation)

        value_kind_to_property_type = {
            enums.ValueKind.FLOAT: PropertyType.FLOAT,
            enums.ValueKind.INT: PropertyType.INTEGER,
            enums.ValueKind.DATETIME: PropertyType.DATETIME,
            enums.ValueKind.STRING: PropertyType.STRING,
            enums.ValueKind.CATEGORY: PropertyType.STRING,
            enums.ValueKind.BOOLEAN: PropertyType.BOOLEAN,
            enums.ValueKind.THREE_D_VECTOR: PropertyType.POINT_3D,
        }
        property_type = value_kind_to_property_type.get(self.value_kind)

        # If aggregation has a fixed result type, check compatibility
        if expected_result_type is not None and property_type is not None and property_type != expected_result_type:
            raise ValueError(f"Aggregation '{aggregation.value}' produces type '{expected_result_type.value}', but property is defined as '{property_type.value}'. Change property type to '{expected_result_type.value}'.")

        return self


class SequenceMappingInput(BaseModel):
    """Input for a sequence mapping within a structure."""

    sequence: str = Field(..., description="The sequence identifier (e.g., 'IAZ001')")
    property: str = Field(..., description="The property key that will be set with the sequence value")


class DefinitionInput(BaseModel):
    sequences: List[SequenceMappingInput] = Field(default_factory=list, description="Sequence mappings for this node")
    key: str = Field(..., description="The label of the node participating in the event")
    description: Optional[str] = Field(default=None, description="Description of this node role")
    ontology_references: List[OntologyReferenceInput] = Field(default_factory=list, description="Ontology references for this event")
    tags: List[str] = Field(default_factory=list, description="Optional tags for this node role (e.g. 'cell_body', 'dendrite', 'axon')")
    color: Optional[List[int]] = Field(default=None, description="Optional RGBA color for this node role (e.g. [255, 0, 0, 128])")
    image: Optional[MediaStoreLike] = Field(default=None, description="Optional media store ID for an image representing this node role")
    label: Optional[str] = Field(default=None, description="Optional human-readable label for this node role (defaults to 'key' if not provided)")
    pin: Optional[bool] = Field(default=None, description="Whether to pin this node role in the UI")


class UpdateDefinitionInput(BaseModel):
    id: GraphID = Field(..., description="The ID of the definition to update")
    sequences: Optional[List[SequenceMappingInput]] = Field(default=None, description="Sequence mappings for this node")
    key: Optional[str] = Field(default=None, description="The label of the node participating in the event")
    description: Optional[str] = Field(default=None, description="Description of this node role")
    ontology_references: Optional[List[OntologyReferenceInput]] = Field(default=None, description="Ontology references for this event")
    tags: Optional[List[str]] = Field(default=None, description="Optional tags for this node role (e.g. 'cell_body', 'dendrite', 'axon')")
    color: Optional[List[int]] = Field(default=None, description="Optional RGBA color for this node role (e.g. [255, 0, 0, 128])")
    image: Optional[MediaStoreLike] = Field(default=None, description="Optional media store ID for an image representing this node role")
    label: Optional[str] = Field(default=None, description="Optional human-readable label for this node role (defaults to 'key' if not provided)")
    pin: Optional[bool] = Field(default=None, description="Whether to pin this node role in the UI")


class NodeDefinitionInput(DefinitionInput):
    """Input for a node definition within an event."""

    pass


class UpdateNodeDefinitionInput(UpdateDefinitionInput):
    """Input for a node definition within an event."""

    pass


class StructureDefinitionInput(NodeDefinitionInput):
    """Input for a structure definition within an event."""

    identifier: scalars.StructureIdentifier = Field(description="Optional schema identifier for this structure (e.g. '@mikro/roi')")

    pass


class MetricDefinitionInput(NodeDefinitionInput):
    """Input for a structure definition within an event."""

    value_kind: PropertyType = Field(description="Optional schema identifier for this structure (e.g. '@mikro/roi')")
    structure: scalars.StructureIdentifier = Field(description="The label of the describing structure to read from")

    pass


class EntityDefinitionInput(NodeDefinitionInput):
    """Input for an entity definition."""

    instance_kind: Optional[str] = Field(default=None, description="Optional instance kind for this entity category (e.g. 'neuron', 'synapse', 'behavior'). This is used for further categorization and filtering of entities within the graph.")
    properties: List[PropertyDefinitionInput] = Field(default_factory=list, description="Property definitions")

    @field_validator("properties")
    @classmethod
    def validate_properties(cls, v: List[PropertyDefinitionInput]) -> List[PropertyDefinitionInput]:
        """Validate that property keys are unique within this entity definition."""
        keys = set()
        for prop in v:
            if prop.key in keys:
                raise ValueError(f"Duplicate property key '{prop.key}' in entity definition")
            keys.add(prop.key)

        return v


class UpdateEntityDefinitionInput(UpdateDefinitionInput):
    """Input for updating an existing entity definition."""

    instance_kind: Optional[str] = Field(default=None, description="Optional instance kind for this entity category (e.g. 'neuron', 'synapse', 'behavior'). This is used for further categorization and filtering of entities within the graph.")
    properties: Optional[List[PropertyDefinitionInput]] = Field(default=None, description="Property definitions")

    @field_validator("properties")
    @classmethod
    def validate_properties(cls, v: Optional[List[PropertyDefinitionInput]]) -> Optional[List[PropertyDefinitionInput]]:
        """Validate that property keys are unique within this entity definition."""
        if v is None:
            return v
        keys = set()
        for prop in v:
            if prop.key in keys:
                raise ValueError(f"Duplicate property key '{prop.key}' in entity definition")
            keys.add(prop.key)

        return v


class CreateEntityDefinitionInput(EntityDefinitionInput):
    """Input for an entity definition at the graph level (not within an event)."""

    graph: GraphID = Field(..., description="The graph id this entitiy will beong to")


class DeleteEntityDefinitionInput(BaseModel):
    """Input for deleting an existing structure definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the structure category to delete")


class ArchiveStructureDefinitionInput(BaseModel):
    """Input for deleting an existing structure definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the structure category to delete")


class UpdateStructureDefinitionInput(UpdateDefinitionInput):
    """Input for updating an existing structure definition."""

    identifier: Optional[scalars.StructureIdentifier] = Field(default=None, description="Optional schema identifier for this structure (e.g. '@mikro/roi')")


class CreateStructureDefinitionInput(StructureDefinitionInput):
    """Input for a structure definition at the graph level (not within an event)."""

    graph: GraphID = Field(..., description="The graph id this structure will belong to")


class DeleteStructureDefinitionInput(BaseModel):
    """Input for deleting an existing structure definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the entity category to delete")


class UpdateMetricDefinitionInput(UpdateDefinitionInput):
    """Input for updating an existing metric definition."""

    identifier: Optional[str] = Field(default=None, description="Optional schema identifier for this metric (e.g. '@mikro/roi')")


class CreateMetricDefinitionInput(MetricDefinitionInput):
    """Input for a metric definition at the graph level (not within an event)."""

    graph: GraphID = Field(..., description="The graph id this metric will belong to")


class DeleteMetricDefinitionInput(BaseModel):
    """Input for deleting an existing metric definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the entity category to delete")


class ArchiveMetricDefinitionInput(BaseModel):
    """Input for archiving (soft deleting) an existing metric definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the metric definition to archive")


class CreateCategoryTagInput(BaseModel):
    """Input for creating a category tag in a graph."""

    graph: GraphID = Field(..., description="The graph ID this category tag belongs to")
    value: str = Field(..., description="Unique tag value within the graph")
    name: Optional[str] = Field(default=None, description="Optional human-readable name")
    description: Optional[str] = Field(default=None, description="Optional category tag description")


class UpdateCategoryTagInput(BaseModel):
    """Input for updating an existing category tag."""

    id: GraphID = Field(..., description="The category tag ID")
    value: Optional[str] = Field(default=None, description="Updated unique tag value")
    name: Optional[str] = Field(default=None, description="Updated human-readable name")
    description: Optional[str] = Field(default=None, description="Updated category tag description")


class DeleteCategoryTagInput(BaseModel):
    """Input for deleting an existing category tag."""

    id: GraphID = Field(..., description="The category tag ID")


class ArchiveCategoryTagInput(BaseModel):
    """Input for archiving an existing category tag."""

    id: GraphID = Field(..., description="The category tag ID")


class EventKind(str, Enum):
    """Role type for a node in an event."""

    INTRINSIC = "intrinsic"
    EXTRINSIC = "extrinsic"


class EntityCategoryProtocol(Protocol):
    """Protocol for entity categories to provide source definition for event linking."""

    tags: List[str]
    key: str
    ontology_references: List[OntologyReferenceInput]


class StructureCategoryProtocol(Protocol):
    """Protocol for entity categories to provide source definition for event linking."""

    tags: List[str]
    key: str
    identifier: scalars.StructureIdentifier
    ontology_references: List[OntologyReferenceInput]


class EntityDescriptorInput(BaseModel):
    """Input for filtering entities when linking to a structure. This only contains relativ fields
    that can be used for filtering, not absolute references like 'id'."""

    keys: Optional[List[str]] = Field(default=None, description="Filter by entity key/label")
    tags: Optional[List[str]] = Field(default=None, description="Filter by tags on the entity")
    ontotology_terms: Optional[List[str]] = Field(default=None, description="Filter by ontology references on the entity (format: 'PREFIX:TERM_ID')")
    default_category_key: Optional[str] = Field(default=None, description="Default category to link to if no entities match the filters")

    def matches(self, entity: EntityCategoryProtocol) -> bool:
        """Check if a given entity matches this descriptor."""
        if self.keys and entity.key not in self.keys:
            return False
        if self.tags and not set(self.tags).issubset(set(entity.tags)):
            return False
        if self.ontotology_terms and not set(self.ontotology_terms).issubset(set(map(lambda x: x.uri, entity.ontology_references))):
            return False
        return True


class StructureDescriptorInput(BaseModel):
    """Input for filtering entities when linking to a structure. This only contains relativ fields
    that can be used for filtering, not absolute references like 'id'."""

    keys: Optional[List[str]] = Field(default=None, description="Filter by entity key/label")
    tags: Optional[List[str]] = Field(default=None, description="Filter by tags on the entity")
    ontotology_terms: Optional[List[str]] = Field(default=None, description="Filter by ontology references on the entity (format: 'PREFIX:TERM_ID')")
    default_category_key: Optional[str] = Field(default=None, description="Default category to link to if no entities match the filters")
    identifiers: Optional[list[scalars.StructureIdentifier]] = Field(default=None, description="Optional structure identifier to filter by (e.g. '@mikro/roi')")

    def matches(self, entity: StructureCategoryProtocol) -> bool:
        """Check if a given entity matches this descriptor."""
        if self.keys and entity.key not in self.keys:
            return False
        if self.tags and not set(self.tags).issubset(set(entity.tags)):
            return False
        if self.ontotology_terms and not set(self.ontotology_terms).issubset(set(map(lambda x: x.uri, entity.ontology_references))):
            return False
        if self.identifiers and entity.identifier not in self.identifiers:
            return False
        return True


class EventRoleInput(BaseModel):
    """Input for a role of a node in an event (input or output)."""

    key: str = Field(..., description="The label of the node participating in the event")
    role: str = Field(..., description="What type of role does this node play in the event")
    descriptor: EntityDescriptorInput = Field(..., description="Optional filters to apply when linking entities to structures for this role")
    ontology_references: List[OntologyReferenceInput] = Field(default_factory=list, description="Ontology references for this role")


class EventDefinitionInput(NodeDefinitionInput):
    """Input for an event definition."""

    kind: EventKind = Field(..., description="The kind of event")
    inputs: List[EventRoleInput] = Field(default_factory=list, description="Input node roles")
    outputs: List[EventRoleInput] = Field(default_factory=list, description="Output node roles")
    properties: List[PropertyDefinitionInput] = Field(default_factory=list, description="Property definitions")


class NaturalEventDefinitionInput(EventDefinitionInput):
    """Input for an event definition."""

    pass


class ProtocolEventDefinitionInput(EventDefinitionInput):
    protocol: str = Field(..., description="The protocol this event definition belongs to")


class CreateNaturalEventDefinitionInput(NaturalEventDefinitionInput):
    """Input for an event definition at the graph level (not within an event)."""

    graph: GraphID = Field(..., description="The graph id this event will belong to")


class UpdateNaturalEventDefinitionInput(NaturalEventDefinitionInput):
    """Input for updating an existing event definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the event category to update")


class DeleteNaturalEventDefinitionInput(BaseModel):
    """Input for deleting an existing event definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the event category to delete")


class CreateProtocolEventDefinitionInput(ProtocolEventDefinitionInput):
    """Input for an event definition at the graph level (not within an event)."""

    graph: GraphID = Field(..., description="The graph id this event will belong to")


class UpdateProtocolEventDefinitionInput(ProtocolEventDefinitionInput):
    """Input for updating an existing event definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the event category to update")


class DeleteProtocolEventDefinitionInput(BaseModel):
    """Input for deleting an existing event definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the event category to delete")


class EvidenceRequirementInput(BaseModel):
    """Input for evidence requirements on a materialized relation."""

    key: str = Field(..., description="Property key expected on the evidence")
    unit: str = Field(..., description="Unit of measurement")
    description: Optional[str] = Field(None, description="Description")


class MaterializationConfigInput(BaseModel):
    """Input for relation materialization configuration."""

    backing_link_type: str = Field(..., description="Internal label for the evidence node")
    desired_evidence: List[EvidenceRequirementInput] = Field(default_factory=list, description="Expected measurements on the backing link")
    properties: List[PropertyDefinitionInput] = Field(default_factory=list, description="Derived property definitions")


class Cardinality(str, Enum):
    ONE_TO_ONE = "1:1"
    ONE_TO_MANY = "1:N"
    MANY_TO_ONE = "N:1"


class EdgeDefinitionInput(DefinitionInput):
    """Input for a relation definition."""

    ontology_references: List[OntologyReferenceInput] = Field(default_factory=list, description="Ontology references for this event")
    key: str = Field(..., description="Relation type name/key")
    source: EntityDescriptorInput = Field(..., description="Source entity type(s)")
    target: EntityDescriptorInput = Field(..., description="Target entity type(s)")
    cardinality: Cardinality = Field(default=Cardinality.ONE_TO_ONE, description="Relation cardinality")


class RelationDefinitionInput(EdgeDefinitionInput):
    """Input for a relation definition."""

    properties: List[PropertyDefinitionInput] = Field(default_factory=list, description="Derived property definitions")


class GraphQueryInput(BaseModel):
    """Input for a graph query definition."""

    key: str = Field(..., description="Unique key for this graph query, used for referencing in the UI")
    name: Optional[str] = Field(default=None, description="Human-readable name for this graph query (defaults to 'key' if not provided)")
    description: Optional[str] = Field(default=None, description="Description of this graph query")
    query: scalars.CypherLiteral = Field(..., description="The Cypher query string that defines this graph query")
    kind: str = Field(default="TABLE", description="The kind/type of this graph query")


class GraphTableQueryInput(GraphQueryInput):
    """Input for a graph table query definition."""

    key: str = Field(..., description="Unique key for this graph query, used for referencing in the UI")
    name: Optional[str] = Field(default=None, description="Human-readable name for this graph query (defaults to 'key' if not provided)")
    description: Optional[str] = Field(default=None, description="Description of this graph query")


class CreateGraphTableQueryInput(GraphTableQueryInput):
    """Input for creating a graph table query definition."""

    graph: strawberry.ID = Field(..., description="The graph id this table query will belong to")
    column_input: List[ColumnInput] = Field(default_factory=list, description="Definitions for the columns returned by this graph query")
    cypher: scalars.CypherLiteral = Field(..., description="The Cypher query string that defines this graph query. Can include parameter placeholders (e.g. $param) for dynamic filtering")


class CreateGraphTableQueryThroughBuilderInput(GraphTableQueryInput):
    """Input for creating a graph table query definition using the builder interface."""

    graph: strawberry.ID = Field(..., description="The graph id this table query will belong to")
    builder_args: BuilderArgsInput = Field(description="Optional additional arguments for the graph query builder to support advanced features like dynamic filtering or pattern matching")
    column_input: List[ColumnInput] = Field(default_factory=list, description="Definitions for the columns returned by this graph query")


class UpdateGraphTableQueryInput(GraphTableQueryInput):
    """Input for updating an existing graph table query definition."""

    id: strawberry.ID = Field(..., description="The ID of the graph query to update")
    column_input: Optional[List[ColumnInput]] = Field(default=None, description="Definitions for the columns returned by this graph query")
    cypher: Optional[scalars.CypherLiteral] = Field(default=None, description="The Cypher query string that defines this graph query. Can include parameter placeholders (e.g. $param) for dynamic filtering")


class DeleteGraphTableQueryInput(BaseModel):
    """Input for deleting an existing graph table query definition."""

    id: strawberry.ID = Field(..., description="The ID of the graph query to delete")


class ArchiveGraphTableQueryInput(BaseModel):
    """Input for archiving (soft deleting) an existing graph table query definition."""

    id: strawberry.ID = Field(..., description="The ID of the graph query to archive")


class GraphPairsQueryInput(GraphQueryInput):
    """Input for a graph pairs query definition."""

    pass


class CreateGraphPairsQueryInput(GraphPairsQueryInput):
    """Input for creating a graph pairs query definition."""

    graph: strawberry.ID = Field(..., description="The graph id this graph pairs query will belong to")


class UpdateGraphPairsQueryInput(GraphPairsQueryInput):
    """Input for updating an existing graph pairs query definition."""

    id: strawberry.ID = Field(..., description="The ID of the graph pairs query to update")
    query: Optional[scalars.CypherLiteral] = Field(default=None, description="Updated Cypher query string")


class DeleteGraphPairsQueryInput(BaseModel):
    """Input for deleting an existing graph pairs query definition."""

    id: strawberry.ID = Field(..., description="The ID of the graph pairs query to delete")


class ArchiveGraphPairsQueryInput(BaseModel):
    """Input for archiving (soft deleting) an existing graph pairs query definition."""

    id: strawberry.ID = Field(..., description="The ID of the graph pairs query to archive")


class GraphPathQueryInput(GraphQueryInput):
    """Input for a graph path query definition."""

    pass


class CreateGraphPathQueryInput(GraphPathQueryInput):
    """Input for creating a graph path query definition."""

    graph: strawberry.ID = Field(..., description="The graph id this graph path query will belong to")


class UpdateGraphPathQueryInput(GraphPathQueryInput):
    """Input for updating an existing graph path query definition."""

    id: strawberry.ID = Field(..., description="The ID of the graph path query to update")
    query: Optional[scalars.CypherLiteral] = Field(default=None, description="Updated Cypher query string")


class DeleteGraphPathQueryInput(BaseModel):
    """Input for deleting an existing graph path query definition."""

    id: strawberry.ID = Field(..., description="The ID of the graph path query to delete")


class ArchiveGraphPathQueryInput(BaseModel):
    """Input for archiving (soft deleting) an existing graph path query definition."""

    id: strawberry.ID = Field(..., description="The ID of the graph path query to archive")


class BuildGraphTableQueryInput(BaseModel):
    """Input for a table graph query definition."""

    builder_args: Optional[BuilderArgsInput] = Field(default=None, description="Optional additional arguments for the graph query builder to support advanced features like dynamic filtering or pattern matching")


class NodeQueryInput(BaseModel):
    key: str = Field(..., description="Unique key for this node query, used for referencing in the UI")
    name: Optional[str] = Field(default=None, description="Human-readable name for this node query (defaults to 'key' if not provided)")
    description: Optional[str] = Field(default=None, description="Description of this node query")
    query: scalars.CypherLiteral = Field(..., description="The Cypher query string that defines this node query")
    kind: str = Field(default="TABLE", description="The kind/type of the query")


class NodeTableQueryInput(NodeQueryInput):
    column_input: List[ColumnInput] = Field(default_factory=list, description="Definitions for the columns returned by this node table query")


class CreateNodeTableQueryInput(NodeTableQueryInput):
    graph: strawberry.ID = Field(..., description="The graph id this node table query will belong to")


class UpdateNodeTableQueryInput(NodeTableQueryInput):
    id: strawberry.ID = Field(..., description="The ID of the node table query to update")
    column_input: Optional[List[ColumnInput]] = Field(default=None, description="Definitions for the columns returned by this node table query")
    query: Optional[scalars.CypherLiteral] = Field(default=None, description="Updated Cypher query string")


class DeleteNodeTableQueryInput(BaseModel):
    id: strawberry.ID = Field(..., description="The ID of the node table query to delete")


class ArchiveNodeTableQueryInput(BaseModel):
    id: strawberry.ID = Field(..., description="The ID of the node table query to archive")


class NodePairsQueryInput(NodeQueryInput):
    pass


class CreateNodePairsQueryInput(NodePairsQueryInput):
    graph: strawberry.ID = Field(..., description="The graph id this node pairs query will belong to")


class UpdateNodePairsQueryInput(NodePairsQueryInput):
    id: strawberry.ID = Field(..., description="The ID of the node pairs query to update")
    query: Optional[scalars.CypherLiteral] = Field(default=None, description="Updated Cypher query string")


class DeleteNodePairsQueryInput(BaseModel):
    id: strawberry.ID = Field(..., description="The ID of the node pairs query to delete")


class ArchiveNodePairsQueryInput(BaseModel):
    id: strawberry.ID = Field(..., description="The ID of the node pairs query to archive")


class NodePathQueryInput(NodeQueryInput):
    pass


class CreateNodePathQueryInput(NodePathQueryInput):
    graph: strawberry.ID = Field(..., description="The graph id this node path query will belong to")


class UpdateNodePathQueryInput(NodePathQueryInput):
    id: strawberry.ID = Field(..., description="The ID of the node path query to update")
    query: Optional[scalars.CypherLiteral] = Field(default=None, description="Updated Cypher query string")


class DeleteNodePathQueryInput(BaseModel):
    id: strawberry.ID = Field(..., description="The ID of the node path query to delete")


class ArchiveNodePathQueryInput(BaseModel):
    id: strawberry.ID = Field(..., description="The ID of the node path query to archive")


class EdgeQueryInput(BaseModel):
    key: str = Field(..., description="Unique key for this edge query, used for referencing in the UI")
    name: Optional[str] = Field(default=None, description="Human-readable name for this edge query (defaults to 'key' if not provided)")
    description: Optional[str] = Field(default=None, description="Description of this edge query")
    query: scalars.CypherLiteral = Field(..., description="The Cypher query string that defines this edge query")
    kind: str = Field(default="TABLE", description="The kind/type of the query")


class EdgeTableQueryInput(EdgeQueryInput):
    column_input: List[ColumnInput] = Field(default_factory=list, description="Definitions for the columns returned by this edge table query")


class CreateEdgeTableQueryInput(EdgeTableQueryInput):
    graph: strawberry.ID = Field(..., description="The graph id this edge table query will belong to")


class UpdateEdgeTableQueryInput(EdgeTableQueryInput):
    id: strawberry.ID = Field(..., description="The ID of the edge table query to update")
    column_input: Optional[List[ColumnInput]] = Field(default=None, description="Definitions for the columns returned by this edge table query")
    query: Optional[scalars.CypherLiteral] = Field(default=None, description="Updated Cypher query string")


class DeleteEdgeTableQueryInput(BaseModel):
    id: strawberry.ID = Field(..., description="The ID of the edge table query to delete")


class ArchiveEdgeTableQueryInput(BaseModel):
    id: strawberry.ID = Field(..., description="The ID of the edge table query to archive")


class EdgePairsQueryInput(EdgeQueryInput):
    pass


class CreateEdgePairsQueryInput(EdgePairsQueryInput):
    graph: strawberry.ID = Field(..., description="The graph id this edge pairs query will belong to")


class UpdateEdgePairsQueryInput(EdgePairsQueryInput):
    id: strawberry.ID = Field(..., description="The ID of the edge pairs query to update")
    query: Optional[scalars.CypherLiteral] = Field(default=None, description="Updated Cypher query string")


class DeleteEdgePairsQueryInput(BaseModel):
    id: strawberry.ID = Field(..., description="The ID of the edge pairs query to delete")


class ArchiveEdgePairsQueryInput(BaseModel):
    id: strawberry.ID = Field(..., description="The ID of the edge pairs query to archive")


class EdgePathQueryInput(EdgeQueryInput):
    pass


class CreateEdgePathQueryInput(EdgePathQueryInput):
    graph: strawberry.ID = Field(..., description="The graph id this edge path query will belong to")


class UpdateEdgePathQueryInput(EdgePathQueryInput):
    id: strawberry.ID = Field(..., description="The ID of the edge path query to update")
    query: Optional[scalars.CypherLiteral] = Field(default=None, description="Updated Cypher query string")


class DeleteEdgePathQueryInput(BaseModel):
    id: strawberry.ID = Field(..., description="The ID of the edge path query to delete")


class ArchiveEdgePathQueryInput(BaseModel):
    id: strawberry.ID = Field(..., description="The ID of the edge path query to archive")


class PlotInput(BaseModel):
    key: str = Field(..., description="Unique key for this plot definition, used for referencing in the UI")
    label: Optional[str] = Field(default=None, description="Human-readable label for this plot definition (defaults to 'key' if not provided)")
    graph_table_query: str | None = Field(..., description="The key of the graph table query that provides the data for this plot")
    node_table_query: str | None = Field(..., description="The key of the node table query that provides the data for this plot")
    path_table_query: str | None = Field(..., description="The key of the path table query that provides the data for this plot")

    @model_validator(mode="after")
    def validate_query_keys(self):
        """Validate that exactly one of graph_table_query, node_table_query, or path_table_query is provided."""
        query_keys = [self.graph_table_query, self.node_table_query, self.path_table_query]
        provided_keys = [key for key in query_keys if key is not None]
        if len(provided_keys) == 0:
            raise ValueError("At least one of graph_table_query, node_table_query, or path_table_query must be provided")
        if len(provided_keys) > 1:
            raise ValueError("Only one of graph_table_query, node_table_query, or path_table_query can be provided")
        return self


class ScatterPlotInput(PlotInput):
    x_axis: str = Field(..., description="The column key to use for the x-axis")
    y_axis: str = Field(..., description="The column key to use for the y-axis")
    color_by: Optional[str] = Field(default=None, description="Optional column key to use for coloring the points")
    size_by: Optional[str] = Field(default=None, description="Optional column key to use for sizing the points")


class CreateRelationDefinitionInput(EntityDefinitionInput):
    """Input for an entity definition at the graph level (not within an event)."""

    graph: GraphID = Field(..., description="The graph id this entitiy will beong to")


class UpdateRelationDefinitionInput(EntityDefinitionInput):
    """Input for updating an existing entity definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the entity category to update")


class DeleteRelationDefinitionInput(BaseModel):
    """Input for deleting an existing relation definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the relation category to delete")


class ArchiveRelationDefinitionInput(BaseModel):
    """Input for archiving (soft deleting) an existing relation definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the relation category to archive")


class CreateMeasurementDefinitionInput(EntityDefinitionInput):
    """Input for a measurement definition at the graph level."""

    graph: GraphID = Field(..., description="The graph id this measurement category will belong to")


class UpdateMeasurementDefinitionInput(EntityDefinitionInput):
    """Input for updating an existing measurement definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the measurement category to update")


class DeleteMeasurementDefinitionInput(BaseModel):
    """Input for deleting an existing measurement definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the measurement category to delete")


class ArchiveMeasurementDefinitionInput(BaseModel):
    """Input for archiving (soft deleting) an existing measurement definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the measurement category to archive")


class CreateStructureRelationDefinitionInput(EntityDefinitionInput):
    """Input for an entity definition at the graph level (not within an event)."""

    graph: GraphID = Field(..., description="The graph id this entitiy will beong to")


class UpdateStructureRelationDefinitionInput(EntityDefinitionInput):
    """Input for updating an existing structure relation definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the structure relation category to update")


class DeleteStructureRelationDefinitionInput(BaseModel):
    """Input for deleting an existing structure relation definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the structure relation category to delete")


class ArchiveStructureRelationDefinitionInput(BaseModel):
    """Input for archiving (soft deleting) an existing structure relation definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the structure relation category to archive")


class RestoreStructureRelationDefinitionInput(BaseModel):
    """Input for restoring an existing structure relation definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the relation category to restore")


class PrefixInput(BaseModel):
    """Input for a graph prefix definition."""

    prefix: str = Field(..., description="The prefix string (e.g. 'OBI')")
    uri: str = Field(..., description="The URI that the prefix maps to (e.g. 'http://purl.obolibrary.org/obo/OBI_')")
    description: Optional[str] = Field(None, description="Description of this prefix")


class SequenceInput(BaseModel):
    """Input for a graph prefix definition."""

    prefix: str = Field(..., description="The prefix string (e.g. 'IAZ')")


class RoleMappingInput(BaseModel):
    """
    Input for role mappings in an event.
    """

    role: str = Field(..., description="The role name")
    entity_id: GraphID = Field(..., description="The ID of the entity assigned to this role")


class EventInput(BaseModel):
    """Input for creating a new event instance."""

    event_category: GraphID = Field(..., description="The ID of the event category/type to create")
    inputs: List[RoleMappingInput] = Field(default_factory=list, description="List of entity IDs that are inputs to this event")
    outputs: List[RoleMappingInput] = Field(default_factory=list, description="List of entity IDs that are outputs of this event")
    supporting_evidence: List[StructureReferenceInput] = Field(default_factory=list, description="List of evidence structures with measurements")


class NaturalEventInput(EventInput):
    """Input for creating a new natural event instance."""

    pass


class CreateNaturalEventInput(NaturalEventInput):
    """Input for creating a new natural event instance."""

    event_category: GraphID = Field(..., description="The ID of the natural event category/type to create")


class UpdateNaturalEventInput(NaturalEventInput):
    """Input for updating an existing natural event instance. Note: this will not update the event in-place, but rather create a new event and archive the old one to preserve history."""

    id: GraphID = Field(..., description="The ID of the natural event to update")


class ArchiveNaturalEventInput(BaseModel):
    """Input for archiving (soft deleting) an existing natural event instance."""

    id: GraphID = Field(..., description="The ID of the natural event to archive")


class DeleteNaturalEventInput(BaseModel):
    """Input for deleting an existing natural event instance."""

    id: GraphID = Field(..., description="The ID of the natural event to delete")


class ProtocolEventInput(EventInput):
    """Input for creating a new protocol event instance."""

    pass


class CreateProtocolEventInput(ProtocolEventInput):
    """Input for creating a new protocol event instance."""

    event_category: GraphID = Field(..., description="The ID of the protocol event category/type to create")


class UpdateProtocolEventInput(ProtocolEventInput):
    """Input for updating an existing protocol event instance. Note: this will not update the event in-place, but rather create a new event and archive the old one to preserve history."""

    id: GraphID = Field(..., description="The ID of the protocol event to update")


class ArchiveProtocolEventInput(BaseModel):
    """Input for archiving (soft deleting) an existing protocol event instance."""

    id: GraphID = Field(..., description="The ID of the protocol event to archive")


class DeleteProtocolEventInput(BaseModel):
    """Input for deleting an existing protocol event instance."""

    id: GraphID = Field(..., description="The ID of the protocol event to delete")


class EntityInput(BaseModel):
    """Input for creating a new entity instance."""

    supporting_evidence: List[StructureReferenceInput] = Field(default_factory=list, description="List of evidence structures with measurements")


class CreateEntityInput(EntityInput):
    """Input for creating a new entity instance."""

    entity_category: strawberry.ID = Field(..., description="The ID of the entity category/type to create")


class EnsureEntityInput(EntityInput):
    """Input for ensuring a new entity instance."""

    entity_category: strawberry.ID = Field(..., description="The ID of the entity category/type to create")
    universal_id: scalars.GlobalID = Field(..., description="A universal ID to use for this entity. If an existing entity with this universal ID exists, it will be returned instead of creating a new one.")


class UpdateEntityInput(EntityInput):
    """Input for updating an existing entity instance. Note: this will not update the entity in-place, but rather create a new entity and archive the old one to preserve history."""

    id: scalars.GraphID = Field(..., description="The ID of the entity to update")


class ArchiveEntityInput(BaseModel):
    """Input for archiving (soft deleting) an existing entity instance."""

    id: scalars.GraphID = Field(..., description="The ID of the entity to archive")


class DeleteEntityInput(BaseModel):
    """Input for deleting an existing entity instance."""

    id: scalars.GraphID = Field(..., description="The ID of the entity to delete")


class StructureInput(BaseModel):
    """Input for creating a new structure instance."""

    object: str = Field(..., description="The unique ID of the object this structure references")
    metrics: List["MetricInput"] = Field(default_factory=list, description="List of measurements associated with this structure")


class PinNodeInput(BaseModel):
    """Input for pinning a node in the UI."""

    id: GraphID = Field(..., description="The ID of the node to pin")
    pin: bool = Field(..., description="Whether to pin (true) or unpin (false) this node in the UI for the user making the request")
    color: Optional[List[int]] = Field(default=None, description="Optional RGBA color for this node (e.g. [255, 0, 0, 128])")
    user: Optional[str] = Field(default=None, description="The ID of the user for whom to set this pin. If not provided, will default to the user making the request.")


class CreateStructureInput(StructureInput):
    """Input for creating a new structure instance."""

    category: GraphID = Field(..., description="The ID of the structure category/type to create")
    graph: GraphID = Field(..., description="The graph id this structure will belong to")


class UpdateStructureInput(StructureInput):
    """Input for updating an existing structure instance."""

    id: scalars.GraphID = Field(..., description="The ID of the structure to update")


class ArchiveStructureInput(BaseModel):
    """Input for archiving (soft deleting) an existing structure."""

    id: GraphID = Field(..., description="The ID of the structure to archive")


class DeleteStructureInput(BaseModel):
    """Input for hard deleting an existing structure."""

    id: GraphID = Field(..., description="The ID of the structure to delete")


class RecordMetricInput(MetricInput):
    """Input for creating a new metric associated with a structure."""

    graph: GraphID = Field(..., description="The graph id this metric will belong to")
    identifier: scalars.StructureIdentifier = Field(..., description="The schema identifier for this metric (e.g. '@mikro/roi_volume')")
    object: scalars.StructureObject = Field(..., description="The unique ID of the object this metric references")
    value_kind: PropertyType = Field(..., description="The kind of value this metric represents (e.g. 'float', 'integer', 'string', etc.)")


class CreateMetricInput(MetricInput):
    """Input for creating a new metric associated with a structure."""

    structure: GraphID = Field(..., description="The unique ID of the structure this metric is associated with")


class ArchiveMetricInput(BaseModel):
    """Input for archiving (soft deleting) an existing metric."""

    id: GraphID = Field(..., description="The ID of the metric to archive")


class DeleteMetricInput(BaseModel):
    """Input for hard deleting an existing metric."""

    id: GraphID = Field(..., description="The ID of the metric to delete")


class RelationInput(BaseModel):
    """Input for a measurement/metric."""

    source_id: str = Field(..., description="The ID of the source entity/structure")
    target_id: str = Field(..., description="The ID of the target entity/structure")
    supporting_evidence: List[StructureReferenceInput] = Field(default_factory=list, description="List of evidence structures with measurements")


class CreateRelationInput(RelationInput):
    """Input for creating a new relation associated with a structure."""

    category: str = Field(..., description="The unique ID of the structure this metric is associated with")


class UpdateRelationInput(RelationInput):
    """Input for updating an existing relation. Note: this will not update the relation in-place, but rather create a new relation and archive the old one to preserve history."""

    id: GraphID = Field(..., description="The ID of the relation to update")


class ArchiveRelationInput(BaseModel):
    """Input for archiving (soft deleting) an existing relation."""

    id: GraphID = Field(..., description="The ID of the relation to archive")


class DeleteRelationInput(BaseModel):
    """Input for hard deleting an existing metric."""

    id: GraphID = Field(..., description="The ID of the metric to delete")


class CreateStructureRelationInput(RelationInput):
    """Input for creating a new structure relation edge."""

    category: str = Field(..., description="The unique ID of the structure relation category")


class UpdateStructureRelationInput(RelationInput):
    """Input for updating an existing structure relation by replacing it with a new edge revision."""

    id: GraphID = Field(..., description="The ID of the structure relation to update")


class ArchiveStructureRelationInput(BaseModel):
    """Input for archiving (soft deleting) an existing structure relation."""

    id: GraphID = Field(..., description="The ID of the structure relation to archive")


class DeleteStructureRelationInput(BaseModel):
    """Input for hard deleting an existing structure relation."""

    id: GraphID = Field(..., description="The ID of the structure relation to delete")


class CreateMeasurementInput(RelationInput):
    """Input for creating a new measurement edge associated with a structure/entity pair."""

    category: str = Field(..., description="The unique ID of the measurement category")


class UpdateMeasurementInput(RelationInput):
    """Input for updating an existing measurement by replacing it with a new edge revision."""

    id: GraphID = Field(..., description="The ID of the measurement to update")


class ArchiveMeasurementInput(BaseModel):
    """Input for archiving (soft deleting) an existing measurement."""

    id: GraphID = Field(..., description="The ID of the measurement to archive")


class DeleteMeasurementInput(BaseModel):
    """Input for hard deleting an existing measurement."""

    id: GraphID = Field(..., description="The ID of the measurement to delete")


class ScatterPlotMutationInput(BaseModel):
    """Base input for scatter plot mutations."""

    name: str = Field(..., description="The display name of the scatter plot")
    description: Optional[str] = Field(default=None, description="Optional description of the scatter plot")
    graph_query_id: Optional[int] = Field(default=None, description="Optional graph table query ID used by this scatter plot")
    node_query_id: Optional[int] = Field(default=None, description="Optional node table query ID used by this scatter plot")
    path_query_id: Optional[int] = Field(default=None, description="Optional node path query ID used by this scatter plot")
    id_column: str = Field(..., description="Column key used for point identifiers")
    x_column: Optional[str] = Field(default=None, description="Column key used for x-axis values")
    x_id_column: Optional[str] = Field(default=None, description="Column key used for x-axis identifiers")
    y_column: Optional[str] = Field(default=None, description="Column key used for y-axis values")
    y_id_column: Optional[str] = Field(default=None, description="Column key used for y-axis identifiers")
    color_column: Optional[str] = Field(default=None, description="Optional column key used for point color")
    size_column: Optional[str] = Field(default=None, description="Optional column key used for point size")
    shape_column: Optional[str] = Field(default=None, description="Optional column key used for point shape")


class CreateScatterPlotInput(ScatterPlotMutationInput):
    """Input for creating a scatter plot."""


class UpdateScatterPlotInput(ScatterPlotMutationInput):
    """Input for updating a scatter plot."""

    id: int = Field(..., description="The database ID of the scatter plot to update")


class DeleteScatterPlotInput(BaseModel):
    """Input for deleting a scatter plot."""

    id: int = Field(..., description="The database ID of the scatter plot to delete")


class ArchiveScatterPlotInput(BaseModel):
    """Input for archiving a scatter plot."""

    id: int = Field(..., description="The database ID of the scatter plot to archive")


class UpdateMetricInput(MetricInput):
    """Input for updating an existing metric. The metric will not be updated in-place, but a new metric will be created and the old one archived to preserve history."""

    id: GraphID = Field(..., description="The ID of the metric to update")


class GraphExtensionsInput(BaseModel):
    """
    Input for graph extensions (the main schema content).

    Note: Structures are no longer defined in the schema. They are
    dynamically resolved via get_label_for_identifier() from the
    IDENTIFIER_MAP in graph_engine.base_models.
    """

    sequences: List[SequenceInput] = Field(default_factory=list, description="Graph sequences for ordering entities")
    prefixes: List[PrefixInput] = Field(default_factory=list, description="Graph prefixes for namespacing")
    entities: List[EntityDefinitionInput] = Field(default_factory=list, description="Entity definitions")
    relations: List[RelationDefinitionInput] = Field(default_factory=list, description="Relation definitions")
    events: List[EventDefinitionInput] = Field(default_factory=list, description="Event definitions")

    # insights
    graph_table_queries: List[GraphTableQueryInput] = Field(default_factory=list, description="Graph table query definitions")
    scatter_plots: List[ScatterPlotInput] = Field(default_factory=list, description="Scatter plot definitions")


class ActionFilterInput(BaseModel):
    required_roles: List[str] = Field(default_factory=list, description="All roles that must be present on the request")
    required_scopes: List[str] = Field(default_factory=list, description="All scopes that must be present on the request")


class ActionRuleInput(BaseModel):
    action: Action = Field(..., description="Action this rule controls")
    allow: bool = Field(True, description="Whether this rule allows or denies the action")
    filter: ActionFilterInput = Field(default_factory=lambda: ActionFilterInput(), description="Simple boolean filter against request context")


class GraphDefinitionInput(BaseModel):
    """
    Input model for a complete graph schema definition.

    This is the full schema that defines entities, structures, relations,
    and events for a knowledge graph.
    """

    system_version: str = Field(default="0.0.1", description="Semantic version for this schema definition (e.g., '1.0.0')")
    rules: List[ActionRuleInput] = Field(default_factory=list, description="Action-level allow/deny rules evaluated against request context")
    extensions: GraphExtensionsInput = Field(default_factory=lambda: GraphExtensionsInput(), description="The graph extensions containing all type definitions")

    @field_validator("system_version")
    @classmethod
    def validate_system_version(cls, v: str) -> str:
        return validate_semver(v)


class GraphInput(BaseModel):
    """Input for creating or updating a graph."""

    name: str = Field(..., description="Name of the graph")
    description: Optional[str] = Field(None, description="Description of the graph")
    definition: GraphDefinitionInput = Field(default_factory=lambda: GraphDefinitionInput(), description="The complete graph schema definition")


class SetSchemaPayload(BaseModel):
    """Payload for setting a new schema on a graph."""

    version: str = Field(..., description="Semantic version for this schema (e.g., '1.0.0', '1.1.0')")
    definition: GraphDefinitionInput = Field(..., description="The complete graph schema definition")
    description: Optional[str] = Field(None, description="Description of changes in this schema version")
    activate: bool = Field(True, description="Whether to immediately activate this schema")

    @field_validator("version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        return validate_semver(v)


class SetSchemaResult(BaseModel):
    """Result of setting a new schema."""

    schema_id: int = Field(..., description="Database ID of the created schema")
    version: str = Field(..., description="Version string of the schema")
    index: int = Field(..., description="Sequential index of this schema")
    is_active: bool = Field(..., description="Whether this schema is now active")


class CreateGraphFromSchema(BaseModel):
    """Input for creating a new graph from a schema definition."""

    name: str = Field(..., description="Name of the graph")
    description: Optional[str] = Field(None, description="Description of the graph")
    definition: Optional[GraphDefinitionInput] = Field(default_factory=lambda: GraphDefinitionInput(), description="The complete graph schema definition")


class UpdateGraphInput(BaseModel):
    """Input for updating an existing graph."""

    id: strawberry.ID = Field(..., description="The ID of the graph to update")
    name: Optional[str] = Field(default=None, description="New graph name")
    description: Optional[str] = Field(default=None, description="New graph description")
    archived: Optional[bool] = Field(default=None, description="Optional archived flag update")


class DeleteGraphInput(BaseModel):
    """Input for deleting an existing graph."""

    id: strawberry.ID = Field(..., description="The ID of the graph to delete")


class ArchiveGraphInput(BaseModel):
    """Input for archiving (soft deleting) an existing graph."""

    id: strawberry.ID = Field(..., description="The ID of the graph to archive")


class PinGraphInput(BaseModel):
    """Input for pinning a graph in the UI."""

    id: strawberry.ID = Field(..., description="The ID of the graph to pin")
    pin: bool = Field(..., description="Whether to pin (true) or unpin (false) this graph in the UI for the user making the request")
    color: Optional[List[int]] = Field(default=None, description="Optional RGBA color for this graph (e.g. [255, 0, 0, 128])")
    user: Optional[str] = Field(default=None, description="The ID of the user for whom to set this pin. If not provided, will default to the user making the request.")


# Backwards-compatible aliases used by older tests and callsites.
GraphDefinitionModel = GraphDefinitionInput
GraphExtensions = GraphExtensionsInput
EntityDefinition = EntityDefinitionInput
PropertyDefinition = PropertyDefinitionInput
