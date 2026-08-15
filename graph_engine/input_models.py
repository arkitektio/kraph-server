from asyncio import Protocol
from enum import Enum
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict
from typing import List, Dict, Optional, Any, Literal, Union
from datetime import datetime, timezone
import re

import strawberry
from strawberry_django import Ordering

from datalayer.scalars import MediaLike
from graph_engine.scalars import GraphID
from graph_engine import scalars
from core import enums

class StrictModel(BaseModel):
    """Base for every input model here: a key that is not a field is an error.

    Pydantic's default is to **ignore** unknown keys, which is the wrong default
    everywhere this module is used, and wrong for two different reasons.

    **On the way in**, an ignored key is a silent no-op. A client sending
    `ontologyTerms` when the field is `ontologyTerms`, or `tags` after tags were
    removed, gets a success and no effect — the class of silence this codebase
    keeps having to hunt down after the fact. GraphQL already rejects an unknown
    *field*; this closes the same hole for every path that builds a model from a
    dict instead, which is what the eight JSON round-trips in `core/models.py`
    do.

    **On the way back out of the database**, an ignored key is worse than a
    no-op: it is an instruction that used to mean something. `source_definition`
    and `target_definition` are stored as JSON and read back through
    `EntityDescriptorInput` / `StructureDescriptorInput`, so a filter written
    under an older schema stays in the row, stops being applied, and *widens* the
    match — quietly, forever. Forbidding makes that row say so.

    The cost is that stored JSON has to keep up with the models.
    `core/migrations/0005_strict_input_models` sweeps what exists today; a field
    removed later needs the same treatment, and this docstring is the reason why.

    Subclasses inherit the config, so only the direct `BaseModel` inheritors in
    this module name it. Deliberately not applied to `kraph_server.configuration`
    (its passthrough classes are `extra="allow"` on purpose), nor to
    `rekuest_core` or `datalayer`, which model payloads another service owns and
    may extend.
    """

    model_config = ConfigDict(extra="forbid")


#: What a write says it is claiming. Spelled out once because getting it wrong is
#: the easiest client-side mistake to make: a term is identified by its **key**,
#: which is the same string a category's `key` carries — `"AIS"`, `"Mitosis"`,
#: `"IS_CONNECTED_TO"` — and not by a category's `label` (human-facing, editable)
#: or its `age_name` (a projection's internal label). The kind of word is implied
#: by the mutation, so it is never stated here.
TERM_FIELD_DESCRIPTION = (
    "The organization's word for what is being claimed — a term's `key`, e.g. 'AIS'. "
    "Not a category id and not a graph: a claim names a word, and every view that "
    "declares that word will hold what you write. The word is created if the "
    "organization has not used it before; a view that declares no category for it "
    "simply will not draw it."
)

#: Why a schema mutation offers to project history. Declaring a word widens a view,
#: and the claims already made under that word are sitting in the evidence base
#: unread. Offered on the kinds that have a projection to fill — nodes and
#: relations. Measurements and structure relations are evidence rows with no
#: projected edge at all, so there would be nothing for the flag to do.
BACKFILL_FIELD_DESCRIPTION = (
    "Draw the evidence this word already admits. Claims made under it before this "
    "category existed are in the organization's evidence base; with this on they are "
    "projected into the graph now, instead of waiting for the next reproject. Off by "
    "default because the work is proportional to the graph's evidence and happens "
    "before this mutation returns."
)

# --- Enums for Strict Typing ---


class DerivationType(str, Enum):
    # Standard: User/Tool sets it directly
    LATEST = "LATEST"
    PRIORITY_LATEST = "PRIORITY_LATEST"

    # Computed: Calculated from children/neighbors
    ROLLUP = "ROLLUP"
    LATEST_ASSERTION_TOOL = "LATEST_ASSERTION_TOOL"


class ConflictPolicy(str, Enum):
    """How to resolve two subjects disagreeing about the same property.

    Aggregation answers "combine these measurements"; conflict policy answers
    "these measurements should not be combined, because they come from sources
    that disagree". A human annotator and a segmentation model both reporting a
    cell's length are not two samples of one quantity — averaging them produces a
    number neither of them claimed.
    """

    #: Fold everything together regardless of who asserted it. The default,
    #: because it is what the aggregation functions already do.
    COMBINE = "COMBINE"
    #: Take the most recent claim from the highest-priority subject.
    SUBJECT_PRIORITY = "SUBJECT_PRIORITY"
    #: Take the most recent claim from the tool that made it, ignoring others.
    LATEST_TOOL = "LATEST_TOOL"
    #: Do not resolve. Surface that the sources disagree and let a human decide.
    FLAG = "FLAG"


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


class ColumnKind(str, Enum):
    NODE = "NODE"
    EDGE = "EDGE"
    VALUE = "VALUE"


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
# What each aggregation produces, in the canonical vocabulary. `None` means "the
# same kind as the values it reads" — SUM of integers is an integer, LATEST of a
# string is a string.
AGGREGATION_RESULT_TYPES: Dict[AggregationFunction, Optional[enums.ValueKind]] = {
    AggregationFunction.MEAN: enums.ValueKind.FLOAT,
    AggregationFunction.SUM: None,
    AggregationFunction.MIN: None,
    AggregationFunction.MAX: None,
    AggregationFunction.COUNT: enums.ValueKind.INT,
    AggregationFunction.LATEST: None,
    AggregationFunction.RANGE: enums.ValueKind.FLOAT,  # true for datetimes too
    AggregationFunction.EUCLIDEAN_RANGE: enums.ValueKind.FLOAT,  # a distance
}

# --- 1. Property & Derivation Rules ---


class DerivationRule(StrictModel):
    """
    Configuration for how to calculate a value if derivation != LATEST.
    """

    source_node: Optional[str] = Field(..., description="The label of the the describing structure to read from.")
    key: Optional[str] = Field(..., description="The property key on the source node.")
    source_value_kind: Optional[enums.ValueKind] = Field(
        default=None,
        description=("Which value kind of the source key to read, when the key has terms in more than one. Distinct from the property's own `value_kind`, which is the aggregation's result type: COUNT yields INT over STRING sources. Leave unset when the key is unambiguous."),
    )
    aggregation: Optional[AggregationFunction] = None


# =======================
# TEXT MODELS
# =======================
class PlateChildInput(StrictModel):
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


class RenderGraphNodesFilter(StrictModel):
    key: str
    operator: str
    value: scalars.AnyScalar


class RenderGraphNodesPagination(StrictModel):
    limit: int
    offset: int


class RenderGraphNodesOrder(StrictModel):
    key: str
    direction: str = "asc"


class RenderGraphPathFilter(StrictModel):
    key: Optional[str] = None
    operator: Optional[str] = None
    value: Optional[scalars.AnyScalar] = None
    search: Optional[str] = None


class RenderGraphPathPagination(StrictModel):
    limit: int
    offset: int


class RenderGraphPathOrder(StrictModel):
    key: str
    direction: str = "asc"


class RenderGraphPairsFilter(StrictModel):
    key: str
    operator: str
    value: scalars.AnyScalar


class RenderGraphPairsPagination(StrictModel):
    limit: int
    offset: int


class RenderGraphPairsOrder(StrictModel):
    key: str
    direction: str = "asc"


class RenderGraphTableFilter(StrictModel):
    key: Optional[str] = None
    operator: Optional[str] = None
    value: scalars.AnyScalar
    search: Optional[str] = None


class RenderGraphTablePagination(StrictModel):
    limit: int
    offset: int


class RenderGraphTableOrder(StrictModel):
    key: str
    direction: str = "asc"


# ==========================================
# SCHEMA INPUT MODELS
# ==========================================


class PropertyMatch(StrictModel):
    """A property match"""

    key: str = Field(description="The property matching")
    operator: WhereOperator = Field(description="The operator to use")
    value: scalars.AnyScalar = Field(description="The value to filter against")


class EntityFilters(StrictModel):
    graph: Optional[strawberry.ID] = Field(default=None, description="Filter by graph ID")
    category: Optional[str] = Field(default=None, description="Filter by entity kind/type")
    ids: Optional[List[scalars.GraphID]] = Field(default=None, description="Filter by specific entity IDs")
    has_property: Optional[str] = Field(default=None, description="Filter entities that have a specific property")
    search: Optional[str] = Field(default=None, description="Full-text search over entity properties")
    matches: Optional[List[PropertyMatch]] = Field(default=None, description="Filter entities that match specific property conditions")


class EntityPagination(StrictModel):
    offset: Optional[int] = Field(default=0, description="Number of items to skip")
    limit: Optional[int] = Field(default=100, description="Maximum number of items to return")


class NodeFilters(StrictModel):
    graph: Optional[strawberry.ID] = Field(default=None, description="Filter by graph ID")
    category: Optional[str] = Field(default=None, description="Filter by node kind/type")
    ids: Optional[List[scalars.GraphID]] = Field(default=None, description="Filter by specific node IDs")
    has_property: Optional[str] = Field(default=None, description="Filter nodes that have a specific property")
    search: Optional[str] = Field(default=None, description="Full-text search over node properties")
    matches: Optional[List[PropertyMatch]] = Field(default=None, description="Filter nodes that match specific property conditions")


class NodePagination(StrictModel):
    offset: Optional[int] = Field(default=0, description="Number of items to skip")
    limit: Optional[int] = Field(default=100, description="Maximum number of items to return")


class StructureFilters(StrictModel):
    graph: Optional[strawberry.ID] = Field(default=None, description="Filter by graph ID")
    category: Optional[str] = Field(default=None, description="Filter by structure kind/type")
    ids: Optional[List[scalars.GraphID]] = Field(default=None, description="Filter by specific structure IDs")
    has_property: Optional[str] = Field(default=None, description="Filter structures that have a specific property")
    search: Optional[str] = Field(default=None, description="Full-text search over structure properties")
    matches: Optional[List[PropertyMatch]] = Field(default=None, description="Filter structures that match specific property conditions")


class StructurePagination(StrictModel):
    offset: Optional[int] = Field(default=0, description="Number of items to skip")
    limit: Optional[int] = Field(default=100, description="Maximum number of items to return")


class PropertyOrder(StrictModel):
    key: str = Field(description="The property key to order by")
    direction: Ordering = Field(description="The direction to order (ASC or DESC)")


class EntityOrder(StrictModel):
    created_at: Optional[Ordering] = Field(default=None, description="Order by creation timestamp")
    category: Optional[Ordering] = Field(default=None, description="Order by entity kind/type")
    id: Optional[Ordering] = Field(default=None, description="Order by entity ID")
    property: Optional[PropertyOrder] = Field(default=None, description="Order by a specific property value (requires 'has_property' filter)")


class NodeOrder(StrictModel):
    created_at: Optional[Ordering] = Field(default=None, description="Order by creation timestamp")
    category: Optional[Ordering] = Field(default=None, description="Order by entity kind/type")
    id: Optional[Ordering] = Field(default=None, description="Order by entity ID")
    property: Optional[PropertyOrder] = Field(default=None, description="Order by a specific property value (requires 'has_property' filter)")


class StructureOrder(StrictModel):
    created_at: Optional[Ordering] = Field(default=None, description="Order by creation timestamp")
    category: Optional[Ordering] = Field(default=None, description="Order by structure kind/type")
    id: Optional[Ordering] = Field(default=None, description="Order by structure ID")
    property: Optional[PropertyOrder] = Field(default=None, description="Order by a specific property value (requires 'has_property' filter)")


class MetricFilters(StrictModel):
    graph: Optional[strawberry.ID] = Field(default=None, description="Filter by graph ID")
    category: Optional[str] = Field(default=None, description="Filter by metric category ID")
    ids: Optional[List[scalars.GraphID]] = Field(default=None, description="Filter by specific metric IDs")
    has_property: Optional[str] = Field(default=None, description="Filter metrics that have a specific property")
    search: Optional[str] = Field(default=None, description="Full-text search over metric properties")
    matches: Optional[List[PropertyMatch]] = Field(default=None, description="Filter metrics that match specific property conditions")


class MetricPagination(StrictModel):
    offset: Optional[int] = Field(default=0, description="Number of items to skip")
    limit: Optional[int] = Field(default=100, description="Maximum number of items to return")


class MetricOrder(StrictModel):
    created_at: Optional[Ordering] = Field(default=None, description="Order by creation timestamp")
    category: Optional[Ordering] = Field(default=None, description="Order by metric category")
    id: Optional[Ordering] = Field(default=None, description="Order by metric ID")
    property: Optional[PropertyOrder] = Field(default=None, description="Order by a specific property value")


class NaturalEventFilters(StrictModel):
    graph: Optional[strawberry.ID] = Field(default=None, description="Filter by graph ID")
    category: Optional[str] = Field(default=None, description="Filter by natural event category ID")
    ids: Optional[List[scalars.GraphID]] = Field(default=None, description="Filter by specific natural event IDs")
    has_property: Optional[str] = Field(default=None, description="Filter natural events that have a specific property")
    search: Optional[str] = Field(default=None, description="Full-text search over natural event properties")
    matches: Optional[List[PropertyMatch]] = Field(default=None, description="Filter natural events that match specific property conditions")


class NaturalEventPagination(StrictModel):
    offset: Optional[int] = Field(default=0, description="Number of items to skip")
    limit: Optional[int] = Field(default=100, description="Maximum number of items to return")


class NaturalEventOrder(StrictModel):
    created_at: Optional[Ordering] = Field(default=None, description="Order by creation timestamp")
    category: Optional[Ordering] = Field(default=None, description="Order by natural event category")
    id: Optional[Ordering] = Field(default=None, description="Order by natural event ID")
    property: Optional[PropertyOrder] = Field(default=None, description="Order by a specific property value")


class ProtocolEventFilters(StrictModel):
    graph: Optional[strawberry.ID] = Field(default=None, description="Filter by graph ID")
    category: Optional[str] = Field(default=None, description="Filter by protocol event category ID")
    ids: Optional[List[scalars.GraphID]] = Field(default=None, description="Filter by specific protocol event IDs")
    has_property: Optional[str] = Field(default=None, description="Filter protocol events that have a specific property")
    search: Optional[str] = Field(default=None, description="Full-text search over protocol event properties")
    matches: Optional[List[PropertyMatch]] = Field(default=None, description="Filter protocol events that match specific property conditions")


class ProtocolEventPagination(StrictModel):
    offset: Optional[int] = Field(default=0, description="Number of items to skip")
    limit: Optional[int] = Field(default=100, description="Maximum number of items to return")


class ProtocolEventOrder(StrictModel):
    created_at: Optional[Ordering] = Field(default=None, description="Order by creation timestamp")
    category: Optional[Ordering] = Field(default=None, description="Order by protocol event category")
    id: Optional[Ordering] = Field(default=None, description="Order by protocol event ID")
    property: Optional[PropertyOrder] = Field(default=None, description="Order by a specific property value")


class MeasurementFilters(StrictModel):
    graph: Optional[strawberry.ID] = Field(default=None, description="Filter by graph ID")
    category: Optional[str] = Field(default=None, description="Filter by measurement category ID")
    ids: Optional[List[scalars.GraphID]] = Field(default=None, description="Filter by specific measurement IDs")
    has_property: Optional[str] = Field(default=None, description="Filter measurements that have a specific property")
    search: Optional[str] = Field(default=None, description="Full-text search over measurement properties")
    matches: Optional[List[PropertyMatch]] = Field(default=None, description="Filter measurements that match specific property conditions")


class MeasurementPagination(StrictModel):
    offset: Optional[int] = Field(default=0, description="Number of items to skip")
    limit: Optional[int] = Field(default=100, description="Maximum number of items to return")


class MeasurementOrder(StrictModel):
    created_at: Optional[Ordering] = Field(default=None, description="Order by creation timestamp")
    category: Optional[Ordering] = Field(default=None, description="Order by measurement category")
    id: Optional[Ordering] = Field(default=None, description="Order by measurement ID")
    property: Optional[PropertyOrder] = Field(default=None, description="Order by a specific property value")


class StructureRelationFilters(StrictModel):
    graph: Optional[strawberry.ID] = Field(default=None, description="Filter by graph ID")
    category: Optional[str] = Field(default=None, description="Filter by structure relation category ID")
    ids: Optional[List[scalars.GraphID]] = Field(default=None, description="Filter by specific structure relation IDs")
    has_property: Optional[str] = Field(default=None, description="Filter structure relations that have a specific property")
    search: Optional[str] = Field(default=None, description="Full-text search over structure relation properties")
    matches: Optional[List[PropertyMatch]] = Field(default=None, description="Filter structure relations that match specific property conditions")


class StructureRelationPagination(StrictModel):
    offset: Optional[int] = Field(default=0, description="Number of items to skip")
    limit: Optional[int] = Field(default=100, description="Maximum number of items to return")


class StructureRelationOrder(StrictModel):
    created_at: Optional[Ordering] = Field(default=None, description="Order by creation timestamp")
    category: Optional[Ordering] = Field(default=None, description="Order by structure relation category")
    id: Optional[Ordering] = Field(default=None, description="Order by structure relation ID")
    property: Optional[PropertyOrder] = Field(default=None, description="Order by a specific property value")


class RelationFilters(StrictModel):
    graph: Optional[strawberry.ID] = Field(default=None, description="Filter by graph ID")
    category: Optional[str] = Field(default=None, description="Filter by relation category ID")
    ids: Optional[List[scalars.GraphID]] = Field(default=None, description="Filter by specific relation IDs")
    has_property: Optional[str] = Field(default=None, description="Filter relations that have a specific property")
    search: Optional[str] = Field(default=None, description="Full-text search over relation properties")
    matches: Optional[List[PropertyMatch]] = Field(default=None, description="Filter relations that match specific property conditions")


class RelationPagination(StrictModel):
    offset: Optional[int] = Field(default=0, description="Number of items to skip")
    limit: Optional[int] = Field(default=100, description="Maximum number of items to return")


class RelationOrder(StrictModel):
    created_at: Optional[Ordering] = Field(default=None, description="Order by creation timestamp")
    category: Optional[Ordering] = Field(default=None, description="Order by relation category")
    id: Optional[Ordering] = Field(default=None, description="Order by relation ID")
    property: Optional[PropertyOrder] = Field(default=None, description="Order by a specific property value")


# ==========================================
# INPUT MODELS
# ==========================================


class MetricInput(StrictModel):
    """
    A single measurement entry.
    Timestamps are converted to Unix Epoch Milliseconds (int) for Apache AGE.
    """

    key: str
    value: Any
    value_kind: PropertyType = Field(
        ...,
        description=(
            "What type of value this is. Required: it decides which column the value is stored in and which measurement term it is recorded under, and nothing infers it. Two callers may declare the same key differently — a float `confidence` and a category-label `confidence` are two terms, and both are recorded."
        ),
    )
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


class StructureReferenceInput(StrictModel):
    identifier: scalars.StructureIdentifier = Field(..., description="Schema identifier, e.g. '@mikro/roi'")
    object: scalars.StructureObject = Field(..., description="The unique ID of the object this structure references")
    metrics: List[MetricInput] = []


def create_told_you_so(metrics: List[MetricInput], object: str) -> StructureReferenceInput:
    return StructureReferenceInput(identifier="told_you_so", object=object, metrics=metrics)


class ProvenanceContext(StrictModel):
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


class SchemaValidationError(StrictModel):
    """A single validation error from schema validation."""

    location: List[str] = Field(default_factory=list, description="Path to the error location (e.g., ['extensions', 'entities', 'Neuron', 'properties', 'soma_volume'])")
    message: str = Field(..., description="Human-readable error message")
    type: str = Field(default="validation_error", description="Error type (e.g., 'missing_field', 'invalid_type', 'reference_error')")


class SchemaValidationResult(StrictModel):
    """Result of validating a schema."""

    is_valid: bool = Field(..., description="Whether the schema is valid")
    errors: List[SchemaValidationError] = Field(default_factory=list, description="List of validation errors if any")
    warnings: List[SchemaValidationError] = Field(default_factory=list, description="List of validation warnings (non-fatal issues)")


class OntologyReferenceInput(StrictModel):
    """Input for an ontology reference."""

    prefix: str = Field(..., description="The ontology prefix (e.g. 'OBI'). Must be defined in graph prefixes.")
    uri: str = Field(..., description="The full URI for the ontology term")


# --- Schema Definition Input Models ---
# These mirror the base_models but are used for input validation


class DerivationRuleInput(StrictModel):
    """Input for a derivation rule configuration."""

    source_node: Optional[str] = Field(default=None, description="The label of the describing structure to read from")
    key: Optional[str] = Field(default=None, description="The property key on the source node")
    source_value_kind: Optional[enums.ValueKind] = Field(
        default=None,
        description=(
            "Which value kind of the source key to read, when the key has terms in more than one. Distinct from the property's own `value_kind`, which is the aggregation's result type: COUNT yields INT over STRING sources. Leave unset when the key is unambiguous. INT and FLOAT are read together either way."
        ),
    )
    aggregation: Optional[AggregationFunction] = Field(default=None, description="Aggregation function (MEAN, SUM, MAX, MIN, COUNT, etc.)")

    conflict_policy: ConflictPolicy = Field(
        default=ConflictPolicy.COMBINE,
        description="How to resolve disagreement between subjects. COMBINE folds everything together.",
    )
    subject_priority: List[str] = Field(
        default_factory=list,
        description=("Subjects in descending order of trust, for PRIORITY_LATEST. The first subject with any measurement wins; subjects not listed are considered only if none of the listed ones have measured."),
    )
    tool_priority: List[str] = Field(
        default_factory=list,
        description="App ids in descending order of trust, for LATEST_ASSERTION_TOOL.",
    )


class ColumnInput(StrictModel):
    kind: ColumnKind = Field(..., description="The kind of column (e.g., 'property', 'id', 'metadata', 'derived')")
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


class MatchPathInput(StrictModel):
    nodes: list[str] = Field(..., description="List of node IDs to match")
    relations: list[str] = Field(..., description="List of node IDs representing the path")
    optional: bool = Field(default=False, description="Whether the path match is optional")
    title: str | None = Field(default=None, description="Title for the matched path")
    color: list[float] | None = Field(default=None, description="Color for the matched path as RGB values")
    relation_directions: list[bool] | None = Field(
        default=None,
        description="List of booleans indicating the direction of each relationship in the path (True for outgoing, False for incoming)",
    )


class WhereClauseInput(StrictModel):
    path: str
    node: str | None = None
    property: str = Field(..., description="The property name to filter on")
    operator: WhereOperator = Field(..., description="The operator to use for filtering")
    value: scalars.CypherLiteral = Field(..., description="The value to compare against")


class ReturnStatementInput(StrictModel):
    path: str = Field(..., description="The path ID to return")
    node: str | None = Field(default=None, description="The node ID to return")
    property: str | None = Field(default=None, description="The property name to return")


class BuilderArgsInput(StrictModel):
    where_clauses: Optional[List[WhereClauseInput]] = Field(default=None, description="Optional filtering conditions for the graph query")
    match_paths: Optional[List[MatchPathInput]] = Field(default=None, description="Optional patterns to match in the graph for this query")
    return_statements: Optional[List[ReturnStatementInput]] = Field(default=None, description="The values to return for each matched pattern in the graph query")


class PropertyDefinitionInput(StrictModel):
    """Input for a property definition on a node or relation."""

    label: Optional[str] = Field(default=None, description="Optional human-readable label for this property (defaults to 'key' if not provided)")
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
        """Accept the old `type` spelling and translate it to `value_kind`.

        The key is **consumed**, not merely read. `StrictModel` forbids unknown
        keys, and `type` is not a field — so leaving it in place after translating
        it would turn every legacy caller into a `ValidationError` at the very
        moment this validator had just successfully understood them. Popping is
        what makes translation and strictness compatible: the shim's whole job is
        to make the old key disappear into the new one.

        `core/migrations/0005_strict_input_models` calls this before sweeping
        stored JSON, for the same reason — otherwise the sweep would delete a
        `type` that is carrying the row's only value kind.
        """
        if not isinstance(data, dict):
            return data

        if "type" not in data:
            return data

        data = data.copy()
        legacy_type = data.pop("type")

        if data.get("value_kind") is not None or legacy_type is None:
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

        # Compared directly in ValueKind. This used to convert both sides into
        # PropertyType first, which is a lossier vocabulary — CATEGORY and STRING
        # collapse together there, and every vector kind but 3D has no
        # representation at all — so the check was weaker than it looked.
        if expected_result_type is not None and self.value_kind is not None and self.value_kind != expected_result_type:
            raise ValueError(f"Aggregation '{aggregation.value}' produces {expected_result_type.value}, but the property is declared as {self.value_kind.value}. Declare it as {expected_result_type.value}.")

        return self


class SequenceMappingInput(StrictModel):
    """Input for a sequence mapping within a structure."""

    sequence: str = Field(..., description="The sequence identifier (e.g., 'IAZ001')")
    property: str = Field(..., description="The property key that will be set with the sequence value")


class DefinitionInput(StrictModel):
    sequences: List[SequenceMappingInput] = Field(default_factory=list, description="Sequence mappings for this node")
    key: str = Field(..., description="The label of the node participating in the event")
    description: Optional[str] = Field(default=None, description="Description of this node role")
    ontology_references: List[OntologyReferenceInput] = Field(default_factory=list, description="Ontology references for this event")
    color: Optional[List[int]] = Field(default=None, description="Optional RGBA color for this node role (e.g. [255, 0, 0, 128])")
    image: Optional[str] = Field(default=None, description="Optional media store ID for an image representing this node role")
    label: Optional[str] = Field(default=None, description="Optional human-readable label for this node role (defaults to 'key' if not provided)")
    pin: Optional[bool] = Field(default=None, description="Whether to pin this node role in the UI")


class UpdateDefinitionInput(StrictModel):
    id: GraphID = Field(..., description="The ID of the definition to update")
    sequences: Optional[List[SequenceMappingInput]] = Field(default=None, description="Sequence mappings for this node")
    key: Optional[str] = Field(default=None, description="The label of the node participating in the event")
    description: Optional[str] = Field(default=None, description="Description of this node role")
    ontology_references: Optional[List[OntologyReferenceInput]] = Field(default=None, description="Ontology references for this event")
    color: Optional[List[int]] = Field(default=None, description="Optional RGBA color for this node role (e.g. [255, 0, 0, 128])")
    image: Optional[str] = Field(default=None, description="Optional media store ID for an image representing this node role")
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
    property_definitions: List[PropertyDefinitionInput] = Field(default_factory=list, description="Property definitions")

    @field_validator("property_definitions")
    @classmethod
    def validate_property_definitions(cls, v: List[PropertyDefinitionInput]) -> List[PropertyDefinitionInput]:
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
    property_definitions: Optional[List[PropertyDefinitionInput]] = Field(default=None, description="Property definitions")

    @field_validator("property_definitions")
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


class SetEntityPropertyInput(StrictModel):
    """Input for setting a property value on an entity."""

    entity_id: GraphID = Field(..., description="The ID of the entity to update")
    key: str = Field(..., description="The property key to set")
    value: Any = Field(..., description="The value to set for this property")


class CreateEntityDefinitionInput(EntityDefinitionInput):
    """Input for an entity definition at the graph level (not within an event)."""

    graph: GraphID = Field(..., description="The graph id this entity will belong to")
    backfill: bool = Field(
        default=False,
        description=BACKFILL_FIELD_DESCRIPTION,
    )


class DeleteEntityDefinitionInput(StrictModel):
    """Input for deleting an existing structure definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the structure category to delete")


class ArchiveStructureDefinitionInput(StrictModel):
    """Input for deleting an existing structure definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the structure category to delete")


class UpdateStructureDefinitionInput(UpdateDefinitionInput):
    """Input for updating an existing structure definition."""

    identifier: Optional[scalars.StructureIdentifier] = Field(default=None, description="Optional schema identifier for this structure (e.g. '@mikro/roi')")


class CreateStructureDefinitionInput(StructureDefinitionInput):
    """Input for a structure definition at the graph level (not within an event)."""

    graph: GraphID = Field(..., description="The graph id this structure will belong to")


class DeleteStructureDefinitionInput(StrictModel):
    """Input for deleting an existing structure definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the entity category to delete")


class CreateTermInput(StrictModel):
    """Input for declaring one of the organization's words up front.

    Terms are minted lazily whenever a graph declares a category for a word or a
    claim names one, so this is never *required*. It exists because a term is an
    ontology entry a curator may want to describe — a label, a definition, a PURL
    — before any graph uses it, and `ensure_term` will then find that entry
    instead of minting a bare one.

    That is the difference from `structureKind`, which has no create: `@mikro/roi`
    is owned by the service that produces the datum, so there is nothing for a
    curator to declare in advance.
    """

    kind: enums.TermKind = Field(..., description="What sort of thing this word names. Part of its identity.")
    key: str = Field(..., description="The word itself, e.g. 'AIS'")
    label: Optional[str] = Field(default=None, description="Human-readable name")
    description: Optional[str] = Field(default=None, description="What this word means")
    purl: Optional[str] = Field(default=None, description="Persistent URL, where this corresponds to a published ontology term")
    color: Optional[List[int]] = Field(default=None, description="Optional RGBA colour")
    image: Optional[str] = Field(default=None, description="Optional media store ID for an illustrative image")


class UpdateTermInput(StrictModel):
    """Input for editing how one of the organization's words presents itself.

    Descriptive fields only. `kind` and `key` are the term's identity, and
    renaming one would silently re-point every claim recorded under it at a
    different word.
    """

    id: GraphID = Field(..., description="The ID of the term to update")
    label: Optional[str] = Field(default=None, description="Human-readable name")
    description: Optional[str] = Field(default=None, description="What this word means")
    purl: Optional[str] = Field(default=None, description="Persistent URL, where this corresponds to a published ontology term")
    color: Optional[List[int]] = Field(default=None, description="Optional RGBA colour")
    image: Optional[str] = Field(default=None, description="Optional media store ID for an illustrative image")


class DeleteTermInput(StrictModel):
    """Input for retiring one of the organization's words."""

    id: GraphID = Field(..., description="The ID of the term to delete")


class UpdateMetricDefinitionInput(UpdateDefinitionInput):
    """Input for updating an existing metric definition."""

    identifier: Optional[str] = Field(default=None, description="Optional schema identifier for this metric (e.g. '@mikro/roi')")


class CreateMetricDefinitionInput(MetricDefinitionInput):
    """Input for a metric definition at the graph level (not within an event)."""

    graph: GraphID = Field(..., description="The graph id this metric will belong to")


class DeleteMetricDefinitionInput(StrictModel):
    """Input for deleting an existing metric definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the entity category to delete")


class ArchiveMetricDefinitionInput(StrictModel):
    """Input for archiving (soft deleting) an existing metric definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the metric definition to archive")


class EventKind(str, Enum):
    """Role type for a node in an event."""

    INTRINSIC = "intrinsic"
    EXTRINSIC = "extrinsic"


class EntityCategoryProtocol(Protocol):
    """Protocol for entity categories to provide source definition for event linking."""

    key: str
    ontology_references: List[OntologyReferenceInput]


class StructureCategoryProtocol(Protocol):
    """Protocol for entity categories to provide source definition for event linking."""

    key: str
    identifier: scalars.StructureIdentifier
    ontology_references: List[OntologyReferenceInput]


class EntityDescriptorInput(StrictModel):
    """Input for filtering entities when linking to a structure. This only contains relativ fields
    that can be used for filtering, not absolute references like 'id'."""

    # No `tags`, and deliberately no `REMOVED` placeholder for it either. The
    # concept is gone, not renamed — `CategoryTag` and `Category.tags` were
    # deleted in `core/migrations/0004_category_tags_die`, so there is nothing
    # left for the field to mean. A client still sending one gets GraphQL's own
    # `Unknown field "tags"`, which is the loud failure that matters; carrying a
    # placeholder that raises would keep the word in the schema it just left.
    # (`StructureDescriptorInput` below does carry such placeholders. Those
    # predate this and record a *different* removal — structures becoming
    # organization vocabulary — so they are left where they are.)
    keys: Optional[List[str]] = Field(default=None, description="Filter by entity key/label")
    ontology_terms: Optional[List[str]] = Field(default=None, description="Filter by ontology references on the entity (format: 'PREFIX:TERM_ID')")
    default_category_key: Optional[str] = Field(default=None, description="Default category to link to if no entities match the filters")

    def matches(self, entity: EntityCategoryProtocol) -> bool:
        """Check if a given entity matches this descriptor."""
        if self.keys and entity.key not in self.keys:
            return False
        if self.ontology_terms and not set(self.ontology_terms).issubset(set(map(lambda x: x.uri, entity.ontology_references))):
            return False
        return True


class StructureDescriptorInput(StrictModel):
    """Input for filtering entities when linking to a structure. This only contains relativ fields
    that can be used for filtering, not absolute references like 'id'."""

    keys: Optional[List[str]] = Field(default=None, description="REMOVED — structure kinds have no key. Use `identifiers`.")
    tags: Optional[List[str]] = Field(default=None, description="REMOVED — tags are gone, and a structure kind never had them. Use `identifiers`.")
    ontology_terms: Optional[List[str]] = Field(default=None, description="REMOVED — structure kinds carry no ontology references. Use `identifiers`.")
    default_category_key: Optional[str] = Field(default=None, description="Default category to link to if no entities match the filters")
    identifiers: Optional[list[scalars.StructureIdentifier]] = Field(default=None, description="Structure identifiers to filter by (e.g. '@mikro/roi')")

    @model_validator(mode="after")
    def reject_unmatchable_filters(self) -> "StructureDescriptorInput":
        """Refuse filters a structure kind cannot answer.

        Structures became organization vocabulary, so a `StructureKind` has an
        identifier and nothing else to match on — no key, no tags, no ontology
        references. Accepting these fields and matching nothing would be the
        silent-zero-result failure this codebase keeps having to remove, so say
        so instead.
        """
        unusable = [name for name in ("keys", "tags", "ontology_terms") if getattr(self, name)]
        if unusable:
            raise ValueError(f"Structure descriptors can only filter by `identifiers`; {', '.join(unusable)} {'is' if len(unusable) == 1 else 'are'} not expressible against a structure kind, which has no key, tags or ontology references.")
        return self

    def matches(self, entity: StructureCategoryProtocol) -> bool:
        """Whether a structure kind matches this descriptor."""
        if self.identifiers and entity.identifier not in self.identifiers:
            return False
        return True


class EventRoleInput(StrictModel):
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
    backfill: bool = Field(
        default=False,
        description=BACKFILL_FIELD_DESCRIPTION,
    )


class UpdateNaturalEventDefinitionInput(NaturalEventDefinitionInput):
    """Input for updating an existing event definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the event category to update")


class DeleteNaturalEventDefinitionInput(StrictModel):
    """Input for deleting an existing event definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the event category to delete")


class CreateProtocolEventDefinitionInput(ProtocolEventDefinitionInput):
    """Input for an event definition at the graph level (not within an event)."""

    graph: GraphID = Field(..., description="The graph id this event will belong to")
    backfill: bool = Field(
        default=False,
        description=BACKFILL_FIELD_DESCRIPTION,
    )


class UpdateProtocolEventDefinitionInput(ProtocolEventDefinitionInput):
    """Input for updating an existing event definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the event category to update")


class DeleteProtocolEventDefinitionInput(StrictModel):
    """Input for deleting an existing event definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the event category to delete")


class EvidenceRequirementInput(StrictModel):
    """Input for evidence requirements on a materialized relation."""

    key: str = Field(..., description="Property key expected on the evidence")
    unit: str = Field(..., description="Unit of measurement")
    description: Optional[str] = Field(None, description="Description")


class MaterializationConfigInput(StrictModel):
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


class StructureRelationDefinitionInput(DefinitionInput):
    """Input for a relation definition."""

    properties: List[PropertyDefinitionInput] = Field(default_factory=list, description="Derived property definitions")
    ontology_references: List[OntologyReferenceInput] = Field(default_factory=list, description="Ontology references for this event")
    key: str = Field(..., description="Relation type name/key")
    source: StructureDescriptorInput = Field(..., description="Source entity type(s)")
    target: StructureDescriptorInput = Field(..., description="Target entity type(s)")
    cardinality: Cardinality = Field(default=Cardinality.ONE_TO_ONE, description="Relation cardinality")


class MeasurementDefinitionInput(EdgeDefinitionInput):
    """Input for a relation definition."""

    source: StructureDescriptorInput = Field(..., description="Source entity type(s)")
    target: EntityDescriptorInput = Field(..., description="Target entity type(s)")
    properties: List[PropertyDefinitionInput] = Field(default_factory=list, description="Derived property definitions")


class GraphQueryInput(StrictModel):
    """Input for a graph query definition."""

    key: str = Field(..., description="Unique key for this graph query, used for referencing in the UI")
    name: Optional[str] = Field(default=None, description="Human-readable name for this graph query (defaults to 'key' if not provided)")
    description: Optional[str] = Field(default=None, description="Description of this graph query")
    query: scalars.CypherLiteral = Field(..., description="The Cypher query string that defines this graph query")


class UpdateGraphQueryInput(StrictModel):
    """Input for updating an existing graph query definition."""

    id: strawberry.ID = Field(..., description="The ID of the graph query to update")
    key: Optional[str] = Field(default=None, description="Unique key for this graph query, used for referencing in the UI")
    name: Optional[str] = Field(default=None, description="Human-readable name for this graph query (defaults to 'key' if not provided)")
    description: Optional[str] = Field(default=None, description="Description of this graph query")
    query: Optional[scalars.CypherLiteral] = Field(default=None, description="The Cypher query string that defines this graph query")


class GraphTableQueryInput(GraphQueryInput):
    """Input for a graph table query definition."""

    name: Optional[str] = Field(default=None, description="Human-readable name for this graph query (defaults to 'key' if not provided)")
    description: Optional[str] = Field(default=None, description="Description of this graph query")


class CreateGraphTableQueryInput(GraphTableQueryInput):
    """Input for creating a graph table query definition."""

    graph: strawberry.ID = Field(..., description="The graph id this table query will belong to")
    column_input: List[ColumnInput] = Field(default_factory=list, description="Definitions for the columns returned by this graph query")
    # No `cypher`, and no second `key`. Both were declared here *and* inherited
    # from `GraphQueryInput`, so a client had to send the Cypher twice — under two
    # required names — with nothing saying which one won. `query` is the name the
    # node and edge families use, so it is the one that survives.


class CreateGraphTableQueryThroughBuilderInput(GraphTableQueryInput):
    """Input for creating a graph table query definition using the builder interface."""

    # The Cypher query is generated from ``builder_args`` by the resolver, so it
    # must not be required as input here (unlike the base GraphQueryInput).
    query: Optional[scalars.CypherLiteral] = Field(default=None, description="Ignored; the query is generated from the builder arguments")
    graph: strawberry.ID = Field(..., description="The graph id this table query will belong to")
    builder_args: BuilderArgsInput = Field(description="Optional additional arguments for the graph query builder to support advanced features like dynamic filtering or pattern matching")
    column_input: List[ColumnInput] = Field(default_factory=list, description="Definitions for the columns returned by this graph query")


class UpdateGraphTableQueryInput(UpdateGraphQueryInput):
    """Input for updating an existing graph table query definition."""

    column_input: Optional[List[ColumnInput]] = Field(default=None, description="Definitions for the columns returned by this graph query")
    # `key`, `name`, `description`, `id` and the Cypher all come from
    # `UpdateGraphQueryInput`; they were re-declared here identically. See
    # `CreateGraphTableQueryInput` for why `cypher` is gone.


class DeleteGraphTableQueryInput(StrictModel):
    """Input for deleting an existing graph table query definition."""

    id: strawberry.ID = Field(..., description="The ID of the graph query to delete")


class ArchiveGraphTableQueryInput(StrictModel):
    """Input for archiving (soft deleting) an existing graph table query definition."""

    id: strawberry.ID = Field(..., description="The ID of the graph query to archive")


class GraphPairsQueryInput(GraphQueryInput):
    """Input for a graph pairs query definition."""

    pass


class CreateGraphPairsQueryInput(GraphPairsQueryInput):
    """Input for creating a graph pairs query definition."""

    graph: strawberry.ID = Field(..., description="The graph id this graph pairs query will belong to")


class UpdateGraphPairsQueryInput(UpdateGraphQueryInput):
    """Input for updating an existing graph pairs query definition."""

    pass


class DeleteGraphPairsQueryInput(StrictModel):
    """Input for deleting an existing graph pairs query definition."""

    id: strawberry.ID = Field(..., description="The ID of the graph pairs query to delete")


class ArchiveGraphPairsQueryInput(StrictModel):
    """Input for archiving (soft deleting) an existing graph pairs query definition."""

    id: strawberry.ID = Field(..., description="The ID of the graph pairs query to archive")


class GraphPathQueryInput(GraphQueryInput):
    """Input for a graph path query definition."""

    pass


class CreateGraphPathQueryInput(GraphPathQueryInput):
    """Input for creating a graph path query definition."""

    graph: strawberry.ID = Field(..., description="The graph id this graph path query will belong to")


class UpdateGraphPathQueryInput(UpdateGraphQueryInput):
    """Input for updating an existing graph path query definition."""

    pass


class DeleteGraphPathQueryInput(StrictModel):
    """Input for deleting an existing graph path query definition."""

    id: strawberry.ID = Field(..., description="The ID of the graph path query to delete")


class ArchiveGraphPathQueryInput(StrictModel):
    """Input for archiving (soft deleting) an existing graph path query definition."""

    id: strawberry.ID = Field(..., description="The ID of the graph path query to archive")


class BuildGraphTableQueryInput(StrictModel):
    """Input for a table graph query definition."""

    builder_args: Optional[BuilderArgsInput] = Field(default=None, description="Optional additional arguments for the graph query builder to support advanced features like dynamic filtering or pattern matching")


class NodeQueryInput(StrictModel):
    key: str = Field(..., description="Unique key for this node query, used for referencing in the UI")
    name: Optional[str] = Field(default=None, description="Human-readable name for this node query (defaults to 'key' if not provided)")
    description: Optional[str] = Field(default=None, description="Description of this node query")
    query: scalars.CypherLiteral = Field(..., description="The Cypher query string that defines this node query")
    # No `kind`. It is decided by the mutation you called — `createNodeTableQuery`
    # makes a TABLE query — and `managers.KindedManager` stamps it from the proxy.
    # As an input it was worse than redundant: the manager uses `setdefault`, so a
    # client-supplied kind overrode the proxy's, writing a row the matching
    # manager then filtered out of every read.


class UpdateNodeQueryInput(StrictModel):
    """Input for updating an existing node query definition.

    Everything but the id is optional, which the node and edge update inputs did
    not manage: they derived from the *create*-shaped base, so `key` and `query`
    stayed required and changing a description meant resending the Cypher. The
    graph family already had this shape; now all three do.
    """

    id: strawberry.ID = Field(..., description="The ID of the node query to update")
    key: Optional[str] = Field(default=None, description="Unique key for this node query, used for referencing in the UI")
    name: Optional[str] = Field(default=None, description="Human-readable name for this node query")
    description: Optional[str] = Field(default=None, description="Description of this node query")
    query: Optional[scalars.CypherLiteral] = Field(default=None, description="The Cypher query string that defines this node query")


class NodeTableQueryInput(NodeQueryInput):
    column_input: List[ColumnInput] = Field(default_factory=list, description="Definitions for the columns returned by this node table query")


class CreateNodeTableQueryInput(NodeTableQueryInput):
    graph: strawberry.ID = Field(..., description="The graph id this node table query will belong to")


class UpdateNodeTableQueryInput(UpdateNodeQueryInput):
    column_input: Optional[List[ColumnInput]] = Field(default=None, description="Definitions for the columns returned by this node table query")


class DeleteNodeTableQueryInput(StrictModel):
    id: strawberry.ID = Field(..., description="The ID of the node table query to delete")


class ArchiveNodeTableQueryInput(StrictModel):
    id: strawberry.ID = Field(..., description="The ID of the node table query to archive")


class NodePairsQueryInput(NodeQueryInput):
    pass


class CreateNodePairsQueryInput(NodePairsQueryInput):
    graph: strawberry.ID = Field(..., description="The graph id this node pairs query will belong to")


class UpdateNodePairsQueryInput(UpdateNodeQueryInput):
    pass


class DeleteNodePairsQueryInput(StrictModel):
    id: strawberry.ID = Field(..., description="The ID of the node pairs query to delete")


class ArchiveNodePairsQueryInput(StrictModel):
    id: strawberry.ID = Field(..., description="The ID of the node pairs query to archive")


class NodePathQueryInput(NodeQueryInput):
    pass


class CreateNodePathQueryInput(NodePathQueryInput):
    graph: strawberry.ID = Field(..., description="The graph id this node path query will belong to")


class UpdateNodePathQueryInput(UpdateNodeQueryInput):
    pass


class DeleteNodePathQueryInput(StrictModel):
    id: strawberry.ID = Field(..., description="The ID of the node path query to delete")


class ArchiveNodePathQueryInput(StrictModel):
    id: strawberry.ID = Field(..., description="The ID of the node path query to archive")


class EdgeQueryInput(StrictModel):
    key: str = Field(..., description="Unique key for this edge query, used for referencing in the UI")
    name: Optional[str] = Field(default=None, description="Human-readable name for this edge query (defaults to 'key' if not provided)")
    description: Optional[str] = Field(default=None, description="Description of this edge query")
    query: scalars.CypherLiteral = Field(..., description="The Cypher query string that defines this edge query")
    # No `kind` — see `NodeQueryInput`.


class UpdateEdgeQueryInput(StrictModel):
    """Input for updating an existing edge query definition.

    Everything but the id is optional, which the node and edge update inputs did
    not manage: they derived from the *create*-shaped base, so `key` and `query`
    stayed required and changing a description meant resending the Cypher. The
    graph family already had this shape; now all three do.
    """

    id: strawberry.ID = Field(..., description="The ID of the edge query to update")
    key: Optional[str] = Field(default=None, description="Unique key for this edge query, used for referencing in the UI")
    name: Optional[str] = Field(default=None, description="Human-readable name for this edge query")
    description: Optional[str] = Field(default=None, description="Description of this edge query")
    query: Optional[scalars.CypherLiteral] = Field(default=None, description="The Cypher query string that defines this edge query")


class EdgeTableQueryInput(EdgeQueryInput):
    column_input: List[ColumnInput] = Field(default_factory=list, description="Definitions for the columns returned by this edge table query")


class CreateEdgeTableQueryInput(EdgeTableQueryInput):
    graph: strawberry.ID = Field(..., description="The graph id this edge table query will belong to")


class UpdateEdgeTableQueryInput(UpdateEdgeQueryInput):
    column_input: Optional[List[ColumnInput]] = Field(default=None, description="Definitions for the columns returned by this edge table query")


class DeleteEdgeTableQueryInput(StrictModel):
    id: strawberry.ID = Field(..., description="The ID of the edge table query to delete")


class ArchiveEdgeTableQueryInput(StrictModel):
    id: strawberry.ID = Field(..., description="The ID of the edge table query to archive")


class EdgePairsQueryInput(EdgeQueryInput):
    pass


class CreateEdgePairsQueryInput(EdgePairsQueryInput):
    graph: strawberry.ID = Field(..., description="The graph id this edge pairs query will belong to")


class UpdateEdgePairsQueryInput(UpdateEdgeQueryInput):
    pass


class DeleteEdgePairsQueryInput(StrictModel):
    id: strawberry.ID = Field(..., description="The ID of the edge pairs query to delete")


class ArchiveEdgePairsQueryInput(StrictModel):
    id: strawberry.ID = Field(..., description="The ID of the edge pairs query to archive")


class EdgePathQueryInput(EdgeQueryInput):
    pass


class CreateEdgePathQueryInput(EdgePathQueryInput):
    graph: strawberry.ID = Field(..., description="The graph id this edge path query will belong to")


class UpdateEdgePathQueryInput(UpdateEdgeQueryInput):
    pass


class DeleteEdgePathQueryInput(StrictModel):
    id: strawberry.ID = Field(..., description="The ID of the edge path query to delete")


class ArchiveEdgePathQueryInput(StrictModel):
    id: strawberry.ID = Field(..., description="The ID of the edge path query to archive")


class PlotInput(StrictModel):
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

    graph: GraphID = Field(..., description="The graph id this entity will belong to")
    backfill: bool = Field(
        default=False,
        description=BACKFILL_FIELD_DESCRIPTION,
    )


class UpdateRelationDefinitionInput(EntityDefinitionInput):
    """Input for updating an existing entity definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the entity category to update")


class DeleteRelationDefinitionInput(StrictModel):
    """Input for deleting an existing relation definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the relation category to delete")


class ArchiveRelationDefinitionInput(StrictModel):
    """Input for archiving (soft deleting) an existing relation definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the relation category to archive")


class CreateMeasurementDefinitionInput(MeasurementDefinitionInput):
    """Input for a measurement definition at the graph level."""

    graph: GraphID = Field(..., description="The graph id this measurement category will belong to")


class UpdateMeasurementDefinitionInput(MeasurementDefinitionInput):
    """Input for updating an existing measurement definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the measurement category to update")


class DeleteMeasurementDefinitionInput(StrictModel):
    """Input for deleting an existing measurement definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the measurement category to delete")


class ArchiveMeasurementDefinitionInput(StrictModel):
    """Input for archiving (soft deleting) an existing measurement definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the measurement category to archive")


class CreateStructureRelationDefinitionInput(StructureRelationDefinitionInput):
    """Input for an entity definition at the graph level (not within an event)."""

    graph: GraphID = Field(..., description="The graph id this entity will belong to")


class UpdateStructureRelationDefinitionInput(EntityDefinitionInput):
    """Input for updating an existing structure relation definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the structure relation category to update")


class DeleteStructureRelationDefinitionInput(StrictModel):
    """Input for deleting an existing structure relation definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the structure relation category to delete")


class ArchiveStructureRelationDefinitionInput(StrictModel):
    """Input for archiving (soft deleting) an existing structure relation definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the structure relation category to archive")


class RestoreStructureRelationDefinitionInput(StrictModel):
    """Input for restoring an existing structure relation definition at the graph level."""

    id: GraphID = Field(..., description="The ID of the relation category to restore")


class PrefixInput(StrictModel):
    """Input for a graph prefix definition."""

    prefix: str = Field(..., description="The prefix string (e.g. 'OBI')")
    uri: str = Field(..., description="The URI that the prefix maps to (e.g. 'http://purl.obolibrary.org/obo/OBI_')")
    description: Optional[str] = Field(None, description="Description of this prefix")


class SequenceInput(StrictModel):
    """Input for a graph prefix definition."""

    prefix: str = Field(..., description="The prefix string (e.g. 'IAZ')")


class RoleMappingInput(StrictModel):
    """
    Input for role mappings in an event.
    """

    role: str = Field(..., description="The role name")
    entity_id: GraphID = Field(..., description="The ID of the entity assigned to this role")


class EventInput(StrictModel):
    """Input for creating a new event instance."""

    term: str = Field(..., description=TERM_FIELD_DESCRIPTION)
    inputs: List[RoleMappingInput] = Field(default_factory=list, description="List of entity IDs that are inputs to this event")
    outputs: List[RoleMappingInput] = Field(default_factory=list, description="List of entity IDs that are outputs of this event")
    supporting_evidence: List[StructureReferenceInput] = Field(default_factory=list, description="List of evidence structures with measurements")


class NaturalEventInput(EventInput):
    """Input for creating a new natural event instance."""

    pass


class AssertNaturalEventExistsInput(NaturalEventInput):
    """Input for creating a new natural event instance."""

    pass


class AssertParticipationInput(StrictModel):
    """Input for claiming that an entity took part in an event.

    Additive: a second observer who reads the same experiment differently asserts
    their own participation rather than replacing anyone else's, and the edge
    records how many live claims stand behind it.
    """

    event: GraphID = Field(..., description="The ID of the event the entity took part in")
    entity: GraphID = Field(..., description="The ID of the entity that took part")
    role: str = Field(..., description="Which role the entity played, as the event's category names it")
    is_input: bool = Field(default=True, description="True if the entity went into the event, False if it came out of it")


class RetractParticipationInput(StrictModel):
    """Input for retracting one claim that an entity took part in an event."""

    id: str = Field(..., description="The evidence ID of the participation claim to retract")


class ParticipantInput(StrictModel):
    """One entity's part in an event, inside a batch."""

    entity: GraphID = Field(..., description="The ID of the entity that took part")
    role: str = Field(..., description="Which role the entity played, as the event's category names it")
    is_input: bool = Field(default=True, description="True if the entity went into the event, False if it came out of it")


class AssertParticipationsInput(StrictModel):
    """Input for claiming that several entities took part in one event.

    One call, one assertion. Asserting them one at a time records the same act as
    N separate claims by N separate assertions, and nothing can put those back
    together afterwards.
    """

    event: GraphID = Field(..., description="The event the entities took part in")
    participants: List[ParticipantInput] = Field(..., description="Everyone who took part, and how")


class ClassificationInput(StrictModel):
    """One claim that a node is of a category, inside a batch."""

    node: GraphID = Field(..., description="The node being classified")
    term: str = Field(..., description=TERM_FIELD_DESCRIPTION)


class ClassifyNodesInput(StrictModel):
    """Input for claiming that several nodes are of a category, as one act.

    Additive: this does not displace anyone else's claim, and the node keeps its
    identity. Which label a graph then shows is decided at projection time by
    whichever of its categories carry a definition.
    """

    classifications: List[ClassificationInput] = Field(..., description="The claims to record")


class RetractClaimsInput(StrictModel):
    """Input for retracting several claims as one act."""

    ids: List[str] = Field(..., description="The evidence IDs of the claims to retract")


class RetractNaturalEventInput(StrictModel):
    """Input for archiving (soft deleting) an existing natural event instance."""

    id: GraphID = Field(..., description="The ID of the natural event to archive")


class DeleteNaturalEventInput(StrictModel):
    """Input for deleting an existing natural event instance."""

    id: GraphID = Field(..., description="The ID of the natural event to delete")


class ProtocolEventInput(EventInput):
    """Input for creating a new protocol event instance."""

    pass


class AssertProtocolEventExistsInput(ProtocolEventInput):
    """Input for creating a new protocol event instance."""

    pass


class RetractProtocolEventInput(StrictModel):
    """Input for archiving (soft deleting) an existing protocol event instance."""

    id: GraphID = Field(..., description="The ID of the protocol event to archive")


class DeleteProtocolEventInput(StrictModel):
    """Input for deleting an existing protocol event instance."""

    id: GraphID = Field(..., description="The ID of the protocol event to delete")


class PropertySet(StrictModel):
    """Input for a set of properties to associate with an entity or structure."""

    key: str = Field(..., description="The property key/label")
    value: str | int | float | bool = Field(..., description="The property value")
    model_config = ConfigDict(arbitrary_types_allowed=True)


class EntityInput(StrictModel):
    """Input for creating a new entity instance."""

    term: str = Field(..., description=TERM_FIELD_DESCRIPTION)
    supporting_evidence: List[StructureReferenceInput] = Field(default_factory=list, description="List of evidence structures with measurements")


class AssertEntityExistsInput(EntityInput):
    """Input for claiming that an entity exists."""

    same_as: List[scalars.GraphID] = Field(
        default_factory=list,
        description=(
            "Instances this new one is the same as. Saying \"this is AIS 6\" mints a fresh "
            "instance and claims it is the same as the one already known as AIS 6 — all under "
            "**one assertion**, because it is one act. Sameness is an equivalence with no "
            "primary, so which id you send is immaterial; entities only, never structures."
        ),
    )


class AssertSameEntityInput(StrictModel):
    """Input for claiming two instances already recorded are one thing."""

    entities: List[scalars.GraphID] = Field(
        ...,
        min_length=2,
        description="Two or more entity ids that name the same thing. Every pair among them is claimed, under one assertion.",
    )


class RetractSameEntityInput(StrictModel):
    """Input for withdrawing one sameness claim."""

    id: scalars.GraphID = Field(..., description="The id of the sameness claim to retract")


class CategoryNodePositionInput(StrictModel):
    """Input for specifying the position of a node in the graph visualization."""

    category: strawberry.ID = Field(..., description="The category of the node")
    position_x: float = Field(..., description="The x-coordinate of the node position")
    position_y: float = Field(..., description="The y-coordinate of the node position")
    width: Optional[float] = Field(default=None, description="Optional width for the node (for visualization purposes)")
    height: Optional[float] = Field(default=None, description="Optional height for the node (for visualization purposes)")


class UpdateGraphVisuals(StrictModel):
    """Input for updating the visual properties of a graph element (node or edge)."""

    id: GraphID = Field(..., description="The ID of the graph element to update")
    node_positions: list[CategoryNodePositionInput] = Field(default_factory=list, description="List of node positions to update")
class RetractEntityInput(StrictModel):
    """Input for archiving (soft deleting) an existing entity instance."""

    id: scalars.GraphID = Field(..., description="The ID of the entity to archive")


class AttestNodeInput(StrictModel):
    """Input for claiming that a node exists.

    Not the reverse of archiving — there is no state to reverse. Somebody is
    saying the thing is there, which is evidence of exactly the same kind as
    somebody saying it is not, and both stay on the record. Which of them a given
    graph believes is decided by its selector.
    """

    id: scalars.GraphID = Field(..., description="The uuid of the node being attested. The same id `archive*` returns, so the two round-trip.")


class AttestEntityInput(AttestNodeInput):
    """Input for claiming that an entity exists."""


class AttestNaturalEventInput(AttestNodeInput):
    """Input for claiming that a natural event exists."""


class AttestProtocolEventInput(AttestNodeInput):
    """Input for claiming that a protocol event exists."""


class DeleteEntityInput(StrictModel):
    """Input for deleting an existing entity instance."""

    id: scalars.GraphID = Field(..., description="The ID of the entity to delete")


class StructureInput(StrictModel):
    """Input for creating a new structure instance."""

    object: str = Field(..., description="The unique ID of the object this structure references")
    metrics: List["MetricInput"] = Field(default_factory=list, description="List of measurements associated with this structure")


# `PinNodeInput` is gone with `pinNode`, whose resolver was `raise
# NotImplementedError`. The strawberry input for it was declared against
# `CreateStructureInput` anyway, so the schema advertised a pin mutation taking
# structure fields.
    user: Optional[str] = Field(default=None, description="The ID of the user for whom to set this pin. If not provided, will default to the user making the request.")


class AssertStructureExistsInput(StructureInput):
    """Input for creating a new structure instance.

    No graph. A structure points at an external datum owned by another service,
    so it belongs to the organization, and naming a projection to record one was
    always incidental.
    """

    identifier: scalars.StructureIdentifier = Field(..., description="The structure identifier, e.g. '@mikro/roi'")


class EnsureStructureInput(StructureInput):
    """Input for creating a new structure instance, or returning the existing one."""

    identifier: scalars.StructureIdentifier = Field(..., description="The structure identifier, e.g. '@mikro/roi'")


class UpdateStructureInput(StructureInput):
    """Input for updating an existing structure instance."""

    id: scalars.GraphID = Field(..., description="The ID of the structure to update")


class RetractStructureInput(StrictModel):
    """Input for archiving (soft deleting) an existing structure."""

    id: GraphID = Field(..., description="The ID of the structure to archive")


class DeleteStructureInput(StrictModel):
    """Input for hard deleting an existing structure."""

    id: GraphID = Field(..., description="The ID of the structure to delete")


class AssertMetricValueInput(MetricInput):
    """Input for recording a measurement.

    Takes no graph. A measurement is a fact about an external datum, scoped to
    the organization; which projections read it is decided by their selectors,
    not by the writer.
    """

    identifier: scalars.StructureIdentifier = Field(..., description="The schema identifier for this metric (e.g. '@mikro/roi_volume')")
    object: scalars.StructureObject = Field(..., description="The unique ID of the object this metric references")


class AssertMetricValueForStructureInput(MetricInput):
    """Input for creating a new metric associated with a structure."""

    structure: GraphID = Field(..., description="The unique ID of the structure this metric is associated with")


class RetractMetricInput(StrictModel):
    """Input for archiving (soft deleting) an existing metric."""

    id: GraphID = Field(..., description="The ID of the metric to archive")


class DeleteMetricInput(StrictModel):
    """Input for hard deleting an existing metric."""

    id: GraphID = Field(..., description="The ID of the metric to delete")


class RelationInput(StrictModel):
    """Input for a measurement/metric."""

    source_id: str = Field(..., description="The ID of the source entity/structure")
    target_id: str = Field(..., description="The ID of the target entity/structure")
    supporting_evidence: List[StructureReferenceInput] = Field(default_factory=list, description="List of evidence structures with measurements")


class EventBaseInput(StrictModel):
    valid_from: Optional[datetime] = Field(default=None, description="Optional start time for the validity of this event (for temporal reasoning)")
    valid_to: Optional[datetime] = Field(default=None, description="Optional end time for the validity of this event (for temporal reasoning)")


class ValidateMeasurementInput(EventBaseInput):
    """Input for supporting evidence that a measurement exists between a source structure and a target entity."""

    source_structure_id: str = Field(description="The ID of the source structure (if different from source_id)")
    source_structure_identifier: scalars.StructureIdentifier = Field(description="The schema identifier for the source structure (e.g. '@mikro/roi_volume')")
    target_entity_id: str = Field(description="The ID of the target entity")
    supporting_evidence: List[StructureReferenceInput] = Field(
        default_factory=list,
        description="Are you basing this measurmenet exists based on evidence other evidence? i.e. did you look at another sample to make this claim that this sample actually measures the entity? If so, include them here to have them automatically linked to the measurement edge",
    )
    confidence: Optional[float] = Field(default=None, description="Optional confidence score for this measurement (between 0 and 1)")


class AssertRelationExistsInput(RelationInput):
    """Input for creating a new relation associated with a structure."""

    term: str = Field(..., description=TERM_FIELD_DESCRIPTION)


class UpdateRelationInput(RelationInput):
    """Input for updating an existing relation. Note: this will not update the relation in-place, but rather create a new relation and archive the old one to preserve history."""

    id: GraphID = Field(..., description="The ID of the relation to update")


class RetractRelationInput(StrictModel):
    """Input for archiving (soft deleting) an existing relation."""

    id: GraphID = Field(..., description="The ID of the relation to archive")


class DeleteRelationInput(StrictModel):
    """Input for hard deleting an existing metric."""

    id: GraphID = Field(..., description="The ID of the metric to delete")


class AssertStructureRelationExistsInput(RelationInput):
    """Input for creating a new structure relation edge."""

    term: str = Field(..., description=TERM_FIELD_DESCRIPTION)


class UpdateStructureRelationInput(RelationInput):
    """Input for updating an existing structure relation by replacing it with a new edge revision."""

    id: GraphID = Field(..., description="The ID of the structure relation to update")


class RetractStructureRelationInput(StrictModel):
    """Input for archiving (soft deleting) an existing structure relation."""

    id: GraphID = Field(..., description="The ID of the structure relation to archive")


class DeleteStructureRelationInput(StrictModel):
    """Input for hard deleting an existing structure relation."""

    id: GraphID = Field(..., description="The ID of the structure relation to delete")


class AssertMeasurementExistsInput(RelationInput):
    """Input for creating a new measurement edge associated with a structure/entity pair."""

    term: str = Field(..., description=TERM_FIELD_DESCRIPTION)


class UpdateMeasurementInput(RelationInput):
    """Input for updating an existing measurement by replacing it with a new edge revision."""

    id: GraphID = Field(..., description="The ID of the measurement to update")


class RetractMeasurementInput(StrictModel):
    """Input for archiving (soft deleting) an existing measurement."""

    id: GraphID = Field(..., description="The ID of the measurement to archive")


class DeleteMeasurementInput(StrictModel):
    """Input for hard deleting an existing measurement."""

    id: GraphID = Field(..., description="The ID of the measurement to delete")


class ScatterPlotMutationInput(StrictModel):
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


class DeleteScatterPlotInput(StrictModel):
    """Input for deleting a scatter plot."""

    id: int = Field(..., description="The database ID of the scatter plot to delete")


class ArchiveScatterPlotInput(StrictModel):
    """Input for archiving a scatter plot."""

    id: int = Field(..., description="The database ID of the scatter plot to archive")


class SupersedeMetricValueInput(MetricInput):
    """Input for updating an existing metric. The metric will not be updated in-place, but a new metric will be created and the old one archived to preserve history."""

    id: GraphID = Field(..., description="The ID of the metric to update")


class GraphExtensionsInput(StrictModel):
    """
    Input for graph extensions (the main schema content).

    Note: Structures are no longer defined in the schema. They are resolved
    dynamically from the structure identifier at write time.
    """

    sequences: List[SequenceInput] = Field(default_factory=list, description="Graph sequences for ordering entities")
    prefixes: List[PrefixInput] = Field(default_factory=list, description="Graph prefixes for namespacing")
    entities: List[EntityDefinitionInput] = Field(default_factory=list, description="Entity definitions")
    relations: List[RelationDefinitionInput] = Field(default_factory=list, description="Relation definitions")
    structure_relations: List[StructureRelationDefinitionInput] = Field(default_factory=list, description="Structure relation definitions")
    measurements: List[MeasurementDefinitionInput] = Field(default_factory=list, description="Measurement definitions")
    events: List[EventDefinitionInput] = Field(default_factory=list, description="Event definitions")

    # insights
    graph_table_queries: List[GraphTableQueryInput] = Field(default_factory=list, description="Graph table query definitions")
    scatter_plots: List[ScatterPlotInput] = Field(default_factory=list, description="Scatter plot definitions")


class ActionFilterInput(StrictModel):
    required_roles: List[str] = Field(default_factory=list, description="All roles that must be present on the request")
    required_scopes: List[str] = Field(default_factory=list, description="All scopes that must be present on the request")


class ActionRuleInput(StrictModel):
    action: Action = Field(..., description="Action this rule controls")
    allow: bool = Field(True, description="Whether this rule allows or denies the action")
    filter: ActionFilterInput = Field(default_factory=lambda: ActionFilterInput(), description="Simple boolean filter against request context")


class GraphDefinitionInput(StrictModel):
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


class GraphInput(StrictModel):
    """Input for creating or updating a graph."""

    name: str = Field(..., description="Name of the graph")
    description: Optional[str] = Field(None, description="Description of the graph")
    definition: GraphDefinitionInput = Field(default_factory=lambda: GraphDefinitionInput(), description="The complete graph schema definition")


class SetSchemaPayload(StrictModel):
    """Payload for setting a new schema on a graph."""

    version: str = Field(..., description="Semantic version for this schema (e.g., '1.0.0', '1.1.0')")
    definition: GraphDefinitionInput = Field(..., description="The complete graph schema definition")
    description: Optional[str] = Field(None, description="Description of changes in this schema version")
    activate: bool = Field(True, description="Whether to immediately activate this schema")

    @field_validator("version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        return validate_semver(v)


class SetSchemaResult(StrictModel):
    """Result of setting a new schema."""

    schema_id: int = Field(..., description="Database ID of the created schema")
    version: str = Field(..., description="Version string of the schema")
    index: int = Field(..., description="Sequential index of this schema")
    is_active: bool = Field(..., description="Whether this schema is now active")


class CreateGraphFromSchema(StrictModel):
    """Input for creating a new graph from a schema definition."""

    name: str = Field(..., description="Name of the graph")
    description: Optional[str] = Field(None, description="Description of the graph")
    definition: Optional[GraphDefinitionInput] = Field(default_factory=lambda: GraphDefinitionInput(), description="The complete graph schema definition")
    backfill: bool = Field(
        default=False,
        description=(
            "Draw the evidence this graph's words already admit. A graph is a view over "
            "the organization's evidence, so a new one can be a view over history: with "
            "this on, every node and edge already claimed under a word this schema "
            "declares is projected as the graph is created. Off by default because the "
            "work is proportional to the organization's evidence and happens before this "
            "mutation returns."
        ),
    )


class UpdateGraphInput(StrictModel):
    """Input for updating an existing graph."""

    id: strawberry.ID = Field(..., description="The ID of the graph to update")
    name: Optional[str] = Field(default=None, description="New graph name")
    description: Optional[str] = Field(default=None, description="New graph description")
    archived: Optional[bool] = Field(default=None, description="Optional archived flag update")
    pin: Optional[bool] = Field(default=None, description="Optional pin flag update for the user making the request")


class DeleteGraphInput(StrictModel):
    """Input for deleting an existing graph."""

    id: strawberry.ID = Field(..., description="The ID of the graph to delete")


class ArchiveGraphInput(StrictModel):
    """Input for archiving (soft deleting) an existing graph."""

    id: strawberry.ID = Field(..., description="The ID of the graph to archive")


class PinGraphInput(StrictModel):
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
