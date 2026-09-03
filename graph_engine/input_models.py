from asyncio import Protocol
from enum import Enum
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict
from typing import List, Dict, Optional, Any, Literal, Union
from datetime import datetime, timezone
import re

import strawberry
from strawberry_django import Ordering

from datalayer.scalars import MediaLike
from evidence.comments import DescendantNode
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


# `ConflictPolicy` is gone (RFC 0009). It was read by nothing — the projector
# dispatches on `derivation` alone — and every real way of saying "whose numbers
# count" exists: PRIORITY_LATEST / LATEST_ASSERTION_TOOL rank sources, and
# `DerivationRuleInput.evidence` filters them. A knob nothing reads is the class
# of silence this codebase refuses.


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


# The `Action` enum is gone with `Graph.rules` (RFC 0013): per-action
# allow/deny lists are replaced by plain RBAC — a graph's definition is edited
# by its owner, an organization admin, or a superuser.


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





class RenderGraphTableFilter(StrictModel):
    key: str = Field(..., description="A returned alias of the plan — what `columns[].key` names")
    operator: WhereOperator = Field(default=WhereOperator.EQUALS, description="How to compare")
    value: Any = Field(..., description="The value to compare against; bound as a parameter, never interpolated")


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
    ids: Optional[List[str]] = Field(default=None, description="Filter by specific entity IDs")
    has_property: Optional[str] = Field(default=None, description="Filter entities that have a specific property")
    search: Optional[str] = Field(default=None, description="Substring match on the claim's term key or label. A column of the log, not a derived property")
    matches: Optional[List[PropertyMatch]] = Field(default=None, description="Filter entities that match specific property conditions")


class EntityPagination(StrictModel):
    offset: Optional[int] = Field(default=0, description="Number of items to skip")
    limit: Optional[int] = Field(default=100, description="Maximum number of items to return")


class NodeFilters(StrictModel):
    graph: Optional[strawberry.ID] = Field(default=None, description="Filter by graph ID")
    category: Optional[str] = Field(default=None, description="Filter by node kind/type")
    ids: Optional[List[str]] = Field(default=None, description="Filter by specific node IDs")
    has_property: Optional[str] = Field(default=None, description="Filter nodes that have a specific property")
    search: Optional[str] = Field(default=None, description="Substring match on the claim's term key or label. A column of the log, not a derived property")
    matches: Optional[List[PropertyMatch]] = Field(default=None, description="Filter nodes that match specific property conditions")


class NodePagination(StrictModel):
    offset: Optional[int] = Field(default=0, description="Number of items to skip")
    limit: Optional[int] = Field(default=100, description="Maximum number of items to return")


class StructureFilters(StrictModel):
    # `graph` is read by nothing. A structure belongs to the organization and has
    # no vertex in any projection, so there is no graph to filter it by;
    # `controller._apply_structure_filters` never looks at this field. Kept only
    # because removing a field from a `StrictModel` an internal caller may set is
    # a separate change from correcting the API surface, which exposes neither.
    graph: Optional[strawberry.ID] = Field(default=None, description="Unused. A structure is organization-scoped and belongs to no graph")
    # Named `kind_identifier`, and it was `category`. It addresses a
    # `StructureKind.identifier` — `_apply_structure_filters` turns it into
    # `queryset.filter(identifier=...)` — and `Category` is a different concept
    # entirely: one view's rule for a word. `api/queries/structure.py` sets it
    # from `kind.identifier`.
    kind_identifier: Optional[str] = Field(default=None, description="Filter by a structure kind's identifier, e.g. '@mikro/roi'")
    ids: Optional[List[str]] = Field(default=None, description="Filter by specific structure IDs")
    has_property: Optional[str] = Field(default=None, description="Filter structures that have a metric under this key")
    search: Optional[str] = Field(default=None, description="Substring match on the structure's `object`, not its properties")
    matches: Optional[List[PropertyMatch]] = Field(default=None, description="Filter structures whose metrics match these conditions")


class StructurePagination(StrictModel):
    offset: Optional[int] = Field(default=0, description="Number of items to skip")
    limit: Optional[int] = Field(default=100, description="Maximum number of items to return")


class PropertyOrder(StrictModel):
    key: str = Field(description="The property key to order by")
    direction: Ordering = Field(description="The direction to order (ASC or DESC)")


class EntityOrder(StrictModel):
    # `property` is not on the GraphQL surface (the node lists refuse drawing
    # questions); it is consumed by the drawing-scoped
    # `GraphController.list_entities_for_category`, which no GraphQL field is
    # built on. The other orderings below carry no `property` because nothing
    # consumes one anywhere.
    created_at: Optional[Ordering] = Field(default=None, description="Order by creation timestamp")
    id: Optional[Ordering] = Field(default=None, description="Order by entity ID")
    property: Optional[PropertyOrder] = Field(default=None, description="Order by a specific derived property value — drawing-scoped reads only")


class NodeOrder(StrictModel):
    created_at: Optional[Ordering] = Field(default=None, description="Order by creation timestamp")
    id: Optional[Ordering] = Field(default=None, description="Order by node ID")


class StructureOrder(StrictModel):
    created_at: Optional[Ordering] = Field(default=None, description="Order by creation timestamp")
    id: Optional[Ordering] = Field(default=None, description="Order by structure ID")


# `MetricFilters`, `MetricPagination` and `MetricOrder` used to sit here. No
# resolver accepted any of them — `metrics(metricKindId:)` dropped its filter
# arguments with the note in `api/queries/metric.py` — and their strawberry
# wrappers were equally unreferenced.


class NaturalEventFilters(StrictModel):
    graph: Optional[strawberry.ID] = Field(default=None, description="Filter by graph ID")
    category: Optional[str] = Field(default=None, description="Filter by natural event category ID")
    ids: Optional[List[str]] = Field(default=None, description="Filter by specific natural event IDs")
    has_property: Optional[str] = Field(default=None, description="Filter natural events that have a specific property")
    search: Optional[str] = Field(default=None, description="Substring match on the claim's term key or label. A column of the log, not a derived property")
    matches: Optional[List[PropertyMatch]] = Field(default=None, description="Filter natural events that match specific property conditions")


class NaturalEventPagination(StrictModel):
    offset: Optional[int] = Field(default=0, description="Number of items to skip")
    limit: Optional[int] = Field(default=100, description="Maximum number of items to return")


class NaturalEventOrder(StrictModel):
    created_at: Optional[Ordering] = Field(default=None, description="Order by creation timestamp")
    id: Optional[Ordering] = Field(default=None, description="Order by natural event ID")


class ProtocolEventFilters(StrictModel):
    graph: Optional[strawberry.ID] = Field(default=None, description="Filter by graph ID")
    category: Optional[str] = Field(default=None, description="Filter by protocol event category ID")
    ids: Optional[List[str]] = Field(default=None, description="Filter by specific protocol event IDs")
    has_property: Optional[str] = Field(default=None, description="Filter protocol events that have a specific property")
    search: Optional[str] = Field(default=None, description="Substring match on the claim's term key or label. A column of the log, not a derived property")
    matches: Optional[List[PropertyMatch]] = Field(default=None, description="Filter protocol events that match specific property conditions")


class ProtocolEventPagination(StrictModel):
    offset: Optional[int] = Field(default=0, description="Number of items to skip")
    limit: Optional[int] = Field(default=100, description="Maximum number of items to return")


class ProtocolEventOrder(StrictModel):
    created_at: Optional[Ordering] = Field(default=None, description="Order by creation timestamp")
    id: Optional[Ordering] = Field(default=None, description="Order by protocol event ID")


class MeasurementFilters(StrictModel):
    graph: Optional[strawberry.ID] = Field(default=None, description="Filter by graph ID")
    category: Optional[str] = Field(default=None, description="Filter by measurement category ID")
    ids: Optional[List[str]] = Field(default=None, description="Filter by specific measurement IDs")
    has_property: Optional[str] = Field(default=None, description="Filter measurements that have a specific property")
    search: Optional[str] = Field(default=None, description="Full-text search over measurement properties")
    matches: Optional[List[PropertyMatch]] = Field(default=None, description="Filter measurements that match specific property conditions")


class MeasurementPagination(StrictModel):
    offset: Optional[int] = Field(default=0, description="Number of items to skip")
    limit: Optional[int] = Field(default=100, description="Maximum number of items to return")


class MeasurementOrder(StrictModel):
    created_at: Optional[Ordering] = Field(default=None, description="Order by creation timestamp")
    id: Optional[Ordering] = Field(default=None, description="Order by measurement ID")


class StructureRelationFilters(StrictModel):
    graph: Optional[strawberry.ID] = Field(default=None, description="Filter by graph ID")
    category: Optional[str] = Field(default=None, description="Filter by structure relation category ID")
    ids: Optional[List[str]] = Field(default=None, description="Filter by specific structure relation IDs")
    has_property: Optional[str] = Field(default=None, description="Filter structure relations that have a specific property")
    search: Optional[str] = Field(default=None, description="Full-text search over structure relation properties")
    matches: Optional[List[PropertyMatch]] = Field(default=None, description="Filter structure relations that match specific property conditions")


class StructureRelationPagination(StrictModel):
    offset: Optional[int] = Field(default=0, description="Number of items to skip")
    limit: Optional[int] = Field(default=100, description="Maximum number of items to return")


class StructureRelationOrder(StrictModel):
    created_at: Optional[Ordering] = Field(default=None, description="Order by creation timestamp")
    id: Optional[Ordering] = Field(default=None, description="Order by structure relation ID")


class RelationFilters(StrictModel):
    graph: Optional[strawberry.ID] = Field(default=None, description="Filter by graph ID")
    category: Optional[str] = Field(default=None, description="Filter by relation category ID")
    ids: Optional[List[str]] = Field(default=None, description="Filter by specific relation IDs")
    has_property: Optional[str] = Field(default=None, description="Filter relations that have a specific property")
    search: Optional[str] = Field(default=None, description="Full-text search over relation properties")
    matches: Optional[List[PropertyMatch]] = Field(default=None, description="Filter relations that match specific property conditions")


class RelationPagination(StrictModel):
    offset: Optional[int] = Field(default=0, description="Number of items to skip")
    limit: Optional[int] = Field(default=100, description="Maximum number of items to return")


class RelationOrder(StrictModel):
    created_at: Optional[Ordering] = Field(default=None, description="Order by creation timestamp")
    id: Optional[Ordering] = Field(default=None, description="Order by relation ID")


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


class ClaimField(str, Enum):
    """What a condition looks at on a claim (RFC 0010)."""

    WORD = "WORD"  #: the term key the claim names
    SUBJECT = "SUBJECT"  #: who asserted it
    APP = "APP"  #: through which app
    ACTION = "ACTION"  #: by which action (may be absent on a claim)
    KIND = "KIND"  #: what the claim *says* — which folds this rule covers (RFC 0011)
    KEY = "KEY"  #: the metric key — measurement rules only (RFC 0014)
    ASSERTED_AT = "ASSERTED_AT"  #: belief time
    MEASURED_AT = "MEASURED_AT"  #: observation time — measurement rules only


class ClaimKind(str, Enum):
    """What a claim says about a category's things (RFC 0011) — the values a
    KIND condition takes. A rule covers every kind its KIND conditions do not
    exclude; a rule with no KIND condition covers them all."""

    CLASSIFICATION = "CLASSIFICATION"  #: which claims admit/label — the whole-rule reading, WORD included
    EXISTENCE = "EXISTENCE"  #: whose standings count — retraction/attest of nodes, and of an edge category's links
    SAMENESS = "SAMENESS"  #: whose SAME_AS may merge this category's nodes (within the category, across words)
    EVIDENCE = "EVIDENCE"  #: whose INFORMS may route evidence under this category's nodes
    MEASUREMENT = "MEASUREMENT"  #: the default metric scope, when a property has no `rule.evidence`


_CLAIM_KIND_VALUES = frozenset(kind.value for kind in ClaimKind)


def rule_covers(stored_rule: Any, kind: str) -> bool:
    """Whether one stored rule applies when folding claims of `kind`.

    **The one coverage implementation** — the write-time validator and the
    compiler (`evidence/selector.py`) both call this, so they cannot disagree.
    A rule covers every kind its KIND conditions do not exclude; several KIND
    conditions AND; a rule with none covers everything; malformed conditions
    are skipped (read-side tolerance — the write path refuses them).
    """
    kind = str(kind)
    for condition in (stored_rule.get("when") or []) if isinstance(stored_rule, dict) else []:
        if not isinstance(condition, dict) or str(condition.get("field")) != "KIND":
            continue
        operator = str(condition.get("operator"))
        value = condition.get("value")
        values = [value] if isinstance(value, str) else list(value or [])
        if operator in ("IS", "IN") and kind not in values:
            return False
        if operator == "NOT_IN" and kind in values:
            return False
    return True


class ClaimOperator(str, Enum):
    """How a condition compares (RFC 0010). BEFORE and SINCE are inclusive."""

    IS = "IS"  #: equals one value
    IN = "IN"  #: any of these values
    NOT_IN = "NOT_IN"  #: none of these values
    BEFORE = "BEFORE"  #: time <= value
    SINCE = "SINCE"  #: time >= value


_IDENTITY_FIELDS = frozenset({ClaimField.WORD, ClaimField.SUBJECT, ClaimField.APP, ClaimField.ACTION, ClaimField.KEY})
_TIME_FIELDS = frozenset({ClaimField.ASSERTED_AT, ClaimField.MEASURED_AT})
#: Only a metric row has these: legal in a property's `rule.evidence` and in
#: the `when` of a MEASUREMENT-only definition rule, nowhere else (RFC 0014).
_METRIC_ONLY_FIELDS = frozenset({ClaimField.MEASURED_AT, ClaimField.KEY})
_IDENTITY_OPERATORS = frozenset({ClaimOperator.IS, ClaimOperator.IN, ClaimOperator.NOT_IN})
_TIME_OPERATORS = frozenset({ClaimOperator.BEFORE, ClaimOperator.SINCE})


class ClaimConditionInput(StrictModel):
    """One condition: (field, operator, value) — the whole rule vocabulary.

    The same triple-with-operator language the saved-query plans use
    (`WhereClauseInput`); there is one formal system on this platform, not two.
    """

    field: ClaimField = Field(..., description="What this condition looks at")
    operator: ClaimOperator = Field(..., description="How it compares. BEFORE/SINCE are inclusive")
    value: Any = Field(..., description="One string for IS, a non-empty string list for IN/NOT_IN, a datetime for BEFORE/SINCE. For field KIND: kinds from CLASSIFICATION, EXISTENCE, SAMENESS, EVIDENCE, MEASUREMENT. For field KEY: metric keys")

    @model_validator(mode="after")
    def value_fits_field_and_operator(self) -> "ClaimConditionInput":
        if self.field in _TIME_FIELDS:
            if self.operator not in _TIME_OPERATORS:
                raise ValueError(f"{self.field.value} takes BEFORE or SINCE, not {self.operator.value}.")
            if isinstance(self.value, str):
                try:
                    self.value = datetime.fromisoformat(self.value.replace("Z", "+00:00"))
                except ValueError as error:
                    raise ValueError(f"{self.field.value} {self.operator.value} needs a datetime, got {self.value!r}.") from error
            if not isinstance(self.value, datetime):
                raise ValueError(f"{self.field.value} {self.operator.value} needs a datetime, got {type(self.value).__name__}.")
            return self

        if self.operator not in _IDENTITY_OPERATORS:
            raise ValueError(f"{self.field.value} takes IS, IN or NOT_IN, not {self.operator.value}.")
        if self.field == ClaimField.KIND:
            values = [self.value] if isinstance(self.value, str) else (self.value if isinstance(self.value, list) else [])
            bad = [entry for entry in values if entry not in _CLAIM_KIND_VALUES] or (["(none)"] if not values else [])
            if bad:
                raise ValueError(f"KIND takes {sorted(_CLAIM_KIND_VALUES)}, got {bad}.")
            if self.operator == ClaimOperator.IS and not isinstance(self.value, str):
                raise ValueError("KIND IS takes one kind; use IN for several.")
            if self.operator in (ClaimOperator.IN, ClaimOperator.NOT_IN) and not isinstance(self.value, list):
                raise ValueError(f"KIND {self.operator.value} takes a list of kinds.")
            return self
        if self.field == ClaimField.WORD and self.operator == ClaimOperator.NOT_IN:
            raise ValueError("WORD takes IS or IN: a definition names the words it derives from, it does not exclude them.")
        if self.operator == ClaimOperator.IS:
            if not isinstance(self.value, str) or not self.value:
                raise ValueError(f"{self.field.value} IS needs one non-empty string, got {self.value!r}.")
        else:
            if not isinstance(self.value, list) or not self.value or not all(isinstance(entry, str) and entry for entry in self.value):
                raise ValueError(f"{self.field.value} {self.operator.value} needs a non-empty list of strings, got {self.value!r}.")
        return self

    def to_stored(self) -> Dict[str, Any]:
        value = self.value.isoformat() if isinstance(self.value, datetime) else self.value
        return {"field": self.field.value, "operator": self.operator.value, "value": value}


class ClaimConditionGroupInput(StrictModel):
    """One exception: a conjunction that, when it holds whole, blocks its rule."""

    when: List[ClaimConditionInput] = Field(..., min_length=1, description="All of these must hold for the exception to apply")

    def to_stored(self) -> Dict[str, Any]:
        return {"when": [condition.to_stored() for condition in self.when]}


class ClaimRuleInput(StrictModel):
    """One rule: matches when ALL `when` conditions hold and NO `unless` group does."""

    when: List[ClaimConditionInput] = Field(..., min_length=1, description="All of these must hold")
    unless: Optional[List[ClaimConditionGroupInput]] = Field(default=None, min_length=1, description="Exceptions: the rule does not match when any group holds whole")

    @model_validator(mode="after")
    def unless_carries_no_kind(self) -> "ClaimRuleInput":
        for group in self.unless or []:
            for condition in group.when:
                if condition.field == ClaimField.KIND:
                    raise ValueError("KIND belongs in `when` — to exclude a kind from a rule, use KIND NOT_IN there, not an exception group.")
        return self

    def to_stored(self) -> Dict[str, Any]:
        stored: Dict[str, Any] = {"when": [condition.to_stored() for condition in self.when]}
        if self.unless:
            stored["unless"] = [group.to_stored() for group in self.unless]
        return stored


class MetricEvidenceInput(StrictModel):
    """A property's own metric rule (RFC 0014): the definition's rule list, over
    metric rows. Same logic — any rule admits, all `when` hold, `unless`
    subtracts — minus WORD (a metric names no word) and KIND (a metric row has
    no kind), plus KEY and MEASURED_AT anywhere, `unless` included."""

    rules: List[ClaimRuleInput] = Field(..., min_length=1, description="A metric counts when any rule matches")

    @model_validator(mode="after")
    def rules_are_metric_shaped(self) -> "MetricEvidenceInput":
        for index, rule in enumerate(self.rules):
            groups = [rule.when] + [group.when for group in rule.unless or []]
            for conditions in groups:
                for condition in conditions:
                    if condition.field == ClaimField.WORD:
                        raise ValueError(f"rules[{index}]: a metric names no WORD — evidence conditions take SUBJECT, APP, ACTION, KEY, ASSERTED_AT or MEASURED_AT.")
                    if condition.field == ClaimField.KIND:
                        raise ValueError(f"rules[{index}]: a metric row has no KIND to test — evidence conditions take SUBJECT, APP, ACTION, KEY, ASSERTED_AT or MEASURED_AT.")
        return self

    def to_stored(self) -> Dict[str, Any]:
        return {"rules": [rule.to_stored() for rule in self.rules]}


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

    evidence: Optional[MetricEvidenceInput] = Field(
        default=None,
        description=(
            "This property's own metric rule: a rule list over SUBJECT/APP/ACTION/KEY/"
            "ASSERTED_AT/MEASURED_AT — any rule admits, all its `when` conditions must hold, "
            "`unless` groups subtract. When present it replaces the owning category's rules as the "
            "metric scope (classification annotators and measurement producers are usually "
            "different populations, so intersecting them would routinely produce nothing); when "
            "absent, the category's MEASUREMENT rules apply, and a primitive category folds everything."
        ),
    )
    subject_priority: List[str] = Field(
        default_factory=list,
        description=("Subjects in descending order of trust, for PRIORITY_LATEST. The first subject with any measurement wins; subjects not listed are considered only if none of the listed ones have measured."),
    )
    tool_priority: List[str] = Field(
        default_factory=list,
        description="App ids in descending order of trust, for LATEST_ASSERTION_TOOL.",
    )

    @model_validator(mode="after")
    def evidence_needs_a_source(self) -> "DerivationRuleInput":
        if self.evidence is not None and not self.source_node:
            raise ValueError("An evidence filter needs a `source_node`: a rule that names no source reads no metrics, so the filter would be silently inert.")
        return self


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
    node_categories: list[str | None] | None = Field(default=None, description="Optional category key per node (parallel to `nodes`), constraining that node of the pattern to a category; null leaves it unconstrained")


class WhereClauseInput(StrictModel):
    path: str
    node: str | None = None
    property: str = Field(..., description="The property name to filter on")
    operator: WhereOperator = Field(..., description="The operator to use for filtering")
    value: Any = Field(..., description="The value to compare against. A typed value bound as a parameter, never a Cypher literal")


class ReturnStatementInput(StrictModel):
    path: str = Field(..., description="The path ID to return")
    node: str | None = Field(default=None, description="The node ID to return")
    property: str | None = Field(default=None, description="The property name to return")
    alias: str | None = Field(default=None, description="The column alias this value is returned under — what `columns[].key`, a render filter and a render order name. Generated from path/node/property when omitted")


class BuilderArgsInput(StrictModel):
    """The builder's spelling of a plan. Kept for `createGraphTableQueryThroughBuilder`; `TableQueryPlanInput` is the contract."""

    where_clauses: Optional[List[WhereClauseInput]] = Field(default=None, description="Optional filtering conditions for the graph query")
    match_paths: Optional[List[MatchPathInput]] = Field(default=None, description="Optional patterns to match in the graph for this query")
    return_statements: Optional[List[ReturnStatementInput]] = Field(default=None, description="The values to return for each matched pattern in the graph query")


class TableQueryPlanInput(StrictModel):
    """What a saved table query means — the contract, compiled per projection kind (`graph_engine/query_ir.py`)."""

    matches: List[MatchPathInput] = Field(..., description="The paths to match; the first node of the first path is the default subject")
    wheres: List[WhereClauseInput] = Field(default_factory=list, description="Predicates over matched nodes' properties")
    returns: List[ReturnStatementInput] = Field(default_factory=list, description="What to return, each under an alias a column can name")


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


class DefinitionInput(StrictModel):
    key: str = Field(..., description="The label of the node participating in the event")
    description: Optional[str] = Field(default=None, description="Description of this node role")
    ontology_references: List[OntologyReferenceInput] = Field(default_factory=list, description="Ontology references for this event")
    color: Optional[List[int]] = Field(default=None, description="Optional RGBA color for this node role (e.g. [255, 0, 0, 128])")
    image: Optional[str] = Field(default=None, description="Optional media store ID for an image representing this node role")
    label: Optional[str] = Field(default=None, description="Optional human-readable label for this node role (defaults to 'key' if not provided)")
    pin: Optional[bool] = Field(default=None, description="Whether to pin this node role in the UI")


class UpdateDefinitionInput(StrictModel):
    id: str = Field(..., description="The ID of the definition to update")
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


class CategoryDefinitionInput(StrictModel):
    """A category's complete rule (RFC 0009), as an explicit rule list (RFC 0010).

    Three sentences of semantics, all visible in the structure: a claim counts
    if **any rule** matches; a rule matches when **all** its `when` conditions
    hold and **no** `unless` group does; a group holds when all its conditions
    do. Every rule names the word(s) it derives from — the wordless clause that
    used to mean "every word" is unspellable now. A *primitive* category is
    expressed by omitting the definition, never by an empty one.
    """

    rules: List[ClaimRuleInput] = Field(..., min_length=1, description="A claim counts when any rule matches")

    @model_validator(mode="after")
    def rules_are_definition_shaped(self) -> "CategoryDefinitionInput":
        for index, rule in enumerate(self.rules):
            stored = rule.to_stored()
            covers_classification = rule_covers(stored, ClaimKind.CLASSIFICATION.value)
            measurement_only = rule_covers(stored, ClaimKind.MEASUREMENT.value) and not any(rule_covers(stored, kind.value) for kind in ClaimKind if kind != ClaimKind.MEASUREMENT)

            has_word = any(condition.field == ClaimField.WORD for condition in rule.when)
            if covers_classification and not has_word:
                raise ValueError(f"rules[{index}]: a rule covering CLASSIFICATION must name the word(s) it derives from — add a WORD condition, or scope the rule with KIND.")
            if not covers_classification and has_word:
                raise ValueError(f"rules[{index}]: a WORD condition means nothing on a rule that does not cover CLASSIFICATION — a standing or a SAME_AS claim names no word.")

            for condition in rule.when:
                if condition.field in _METRIC_ONLY_FIELDS and not measurement_only:
                    raise ValueError(f"rules[{index}]: {condition.field.value} is meaningful only on a rule covering MEASUREMENT alone — other claims have no metric key or observation time.")
            for group in rule.unless or []:
                for condition in group.when:
                    if condition.field == ClaimField.WORD:
                        raise ValueError(f"rules[{index}]: an `unless` group may not name a WORD — exceptions are about who and when, not vocabulary.")
                    if condition.field in _METRIC_ONLY_FIELDS:
                        raise ValueError(f"rules[{index}]: a claim has no metric key or observation time — {condition.field.value} belongs in `when` of a MEASUREMENT-only rule, or in a property's `rule.evidence`.")
        return self

    def to_stored(self) -> Dict[str, Any]:
        """The exact JSON `Category.definition` stores."""
        return {"rules": [rule.to_stored() for rule in self.rules]}

    @classmethod
    def from_stored(cls, stored: Any) -> Optional["CategoryDefinitionInput"]:
        """The stored JSON as a model, tolerantly: non-dict garbage and shapes
        this cannot spell read back as None (primitive), never as an error —
        this is the read side. The old clause shape is NOT read: RFC 0010 was a
        clean break, and `core/migrations/0017` cleared what stored it.
        """
        if not stored or not isinstance(stored, dict) or not isinstance(stored.get("rules"), list):
            return None
        try:
            return cls.model_validate({"rules": stored["rules"]})
        except (ValueError, TypeError):
            return None


class EntityDefinitionInput(NodeDefinitionInput):
    """Input for an entity definition."""

    instance_kind: Optional[str] = Field(default=None, description="Optional instance kind for this entity category (e.g. 'neuron', 'synapse', 'behavior'). This is used for further categorization and filtering of entities within the graph.")
    property_definitions: List[PropertyDefinitionInput] = Field(default_factory=list, description="Property definitions")
    definition: Optional[CategoryDefinitionInput] = Field(default=None, description="What this category *means*: a predicate over classification claims (RFC 0007). Omitted means primitive — membership is whatever was asserted under this word")

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


class UpdateEntityCategoryInput(UpdateDefinitionInput):
    """Input for updating an existing entity definition."""

    instance_kind: Optional[str] = Field(default=None, description="Optional instance kind for this entity category (e.g. 'neuron', 'synapse', 'behavior'). This is used for further categorization and filtering of entities within the graph.")
    property_definitions: Optional[List[PropertyDefinitionInput]] = Field(default=None, description="Property definitions")
    definition: Optional[CategoryDefinitionInput] = Field(default=None, description="New meaning for this category (RFC 0007). Omitted means unchanged; to make the category primitive again, use clearDefinition")
    clear_definition: bool = Field(default=False, description="Reset the category to primitive — membership becomes whatever was asserted under its word")

    @model_validator(mode="after")
    def definition_and_clear_are_exclusive(self) -> "UpdateEntityCategoryInput":
        if self.definition is not None and self.clear_definition:
            raise ValueError("Pass a new `definition` or `clearDefinition`, not both.")
        return self

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


class CreateEntityCategoryInput(EntityDefinitionInput):
    """Input for an entity definition at the graph level (not within an event)."""

    graph: str = Field(..., description="The graph id this entity will belong to")
    backfill: bool = Field(
        default=False,
        description=BACKFILL_FIELD_DESCRIPTION,
    )


class DeleteEntityCategoryInput(StrictModel):
    """Input for deleting an existing structure definition at the graph level."""

    id: str = Field(..., description="The ID of the structure category to delete")


class UpdateStructureKindInput(UpdateDefinitionInput):
    """Input for updating one of the organization's structure kinds.

    A `StructureKind` is organization-scoped and belongs to no graph — this input
    was called `UpdateStructureDefinitionInput` and described as operating "at the
    graph level", which named two concepts it has nothing to do with.
    """

    identifier: Optional[scalars.StructureIdentifier] = Field(default=None, description="Read by nothing: `(organization, identifier)` is a structure kind's identity and cannot be reassigned. `update_structure_kind` writes label, description and colour only")


class DeleteStructureKindInput(StrictModel):
    """Input for retiring one of the organization's structure kinds."""

    id: str = Field(..., description="The ID of the structure kind to retire")


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

    id: str = Field(..., description="The ID of the term to update")
    label: Optional[str] = Field(default=None, description="Human-readable name")
    description: Optional[str] = Field(default=None, description="What this word means")
    purl: Optional[str] = Field(default=None, description="Persistent URL, where this corresponds to a published ontology term")
    color: Optional[List[int]] = Field(default=None, description="Optional RGBA colour")
    image: Optional[str] = Field(default=None, description="Optional media store ID for an illustrative image")


class DeleteTermInput(StrictModel):
    """Input for retiring one of the organization's words."""

    id: str = Field(..., description="The ID of the term to delete")


class UpdateMetricKindInput(UpdateDefinitionInput):
    """Input for updating one of the organization's metric kinds. See `UpdateStructureKindInput`."""

    identifier: Optional[str] = Field(default=None, description="Read by nothing: a metric kind is identified by `(organization, structure_kind, key, value_kind)`. `update_metric_kind` writes label, description and colour only")


class DeleteMetricKindInput(StrictModel):
    """Input for retiring one of the organization's metric kinds."""

    id: str = Field(..., description="The ID of the metric kind to retire")


class EventKind(str, Enum):
    """Whether an event arises in the system itself or is applied from outside.

    Not "event" in the event-sourcing sense — the log's unit is `Assertion` —
    and not a role type either, which is what this docstring used to claim while
    the description beside the field said "the kind of event". It is a fact
    about the *defined* event: mitosis happens to the sample (INTRINSIC), a
    protocol step is done to it (EXTRINSIC). Recorded in the definition;
    nothing derives from it yet.
    """

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

    kind: EventKind = Field(..., description="Whether the event arises in the system itself (INTRINSIC, e.g. mitosis) or is applied from outside (EXTRINSIC, e.g. a protocol step)")
    inputs: List[EventRoleInput] = Field(default_factory=list, description="Input node roles")
    outputs: List[EventRoleInput] = Field(default_factory=list, description="Output node roles")
    properties: List[PropertyDefinitionInput] = Field(default_factory=list, description="Property definitions")
    definition: Optional[CategoryDefinitionInput] = Field(default=None, description="This event category's complete rule (RFC 0009): which classification claims admit an event, whose existence standings count, and whose participation claims draw its edges. Omitted means primitive")


class NaturalEventDefinitionInput(EventDefinitionInput):
    """Input for an event definition."""

    pass


class ProtocolEventDefinitionInput(EventDefinitionInput):
    protocol: str = Field(..., description="The protocol this event definition belongs to")


class CreateNaturalEventCategoryInput(NaturalEventDefinitionInput):
    """Input for an event definition at the graph level (not within an event)."""

    graph: str = Field(..., description="The graph id this event will belong to")
    backfill: bool = Field(
        default=False,
        description=BACKFILL_FIELD_DESCRIPTION,
    )


class UpdateNaturalEventCategoryInput(UpdateDefinitionInput):
    """Input for updating a natural event category.

    Extends `UpdateDefinitionInput` — the all-optional patch shape — and used to
    extend `NaturalEventDefinitionInput`, the **create**-shaped input. That made
    `key`, `kind`, `inputs`, `outputs` and `properties` mandatory on an update, and
    `update_natural_event_category` writes none of them: it sets label,
    description, colour, image and pin. A field that is accepted and discarded is
    worse than one that is refused, and these were required as well as discarded.
    """

    definition: Optional[CategoryDefinitionInput] = Field(default=None, description="New rule for this category (RFC 0009). Omitted means unchanged; to make it primitive again, use clearDefinition")
    clear_definition: bool = Field(default=False, description="Reset the category to primitive — any claim naming its word counts, standings organization grain")

    @model_validator(mode="after")
    def definition_and_clear_are_exclusive(self):
        if self.definition is not None and self.clear_definition:
            raise ValueError("Pass a new `definition` or `clearDefinition`, not both.")
        return self

    id: str = Field(..., description="The ID of the natural event category to update")


class DeleteNaturalEventCategoryInput(StrictModel):
    """Input for deleting an existing event definition at the graph level."""

    id: str = Field(..., description="The ID of the event category to delete")


class CreateProtocolEventCategoryInput(ProtocolEventDefinitionInput):
    """Input for an event definition at the graph level (not within an event)."""

    graph: str = Field(..., description="The graph id this event will belong to")
    backfill: bool = Field(
        default=False,
        description=BACKFILL_FIELD_DESCRIPTION,
    )


class UpdateProtocolEventCategoryInput(UpdateDefinitionInput):
    """Input for updating a protocol event category.

    Extends `UpdateDefinitionInput` — the all-optional patch shape — and used to
    extend `ProtocolEventDefinitionInput`, the **create**-shaped input. That made
    `key`, `kind`, `protocol`, `inputs`, `outputs` and `properties` mandatory on an update, and
    `update_protocol_event_category` writes none of them: it sets label,
    description, colour, image and pin. A field that is accepted and discarded is
    worse than one that is refused, and these were required as well as discarded.
    """

    definition: Optional[CategoryDefinitionInput] = Field(default=None, description="New rule for this category (RFC 0012). Omitted means unchanged; to make it primitive again, use clearDefinition")
    clear_definition: bool = Field(default=False, description="Reset the category to primitive — any claim naming its word counts, standings organization grain")

    @model_validator(mode="after")
    def definition_and_clear_are_exclusive(self):
        if self.definition is not None and self.clear_definition:
            raise ValueError("Pass a new `definition` or `clearDefinition`, not both.")
        return self


    id: str = Field(..., description="The ID of the protocol event category to update")


class DeleteProtocolEventCategoryInput(StrictModel):
    """Input for deleting an existing event definition at the graph level."""

    id: str = Field(..., description="The ID of the event category to delete")


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
    definition: Optional[CategoryDefinitionInput] = Field(default=None, description="This relation category's complete rule (RFC 0009): which relation claims draw its edges — by word, annotator, app and window — and whose standings count for them. Omitted means primitive: any claim naming its word draws")


class StructureRelationDefinitionInput(DefinitionInput):
    """Input for a relation definition."""

    properties: List[PropertyDefinitionInput] = Field(default_factory=list, description="Derived property definitions")
    ontology_references: List[OntologyReferenceInput] = Field(default_factory=list, description="Ontology references for this event")
    key: str = Field(..., description="Relation type name/key")
    source: StructureDescriptorInput = Field(..., description="Source entity type(s)")
    target: StructureDescriptorInput = Field(..., description="Target entity type(s)")
    cardinality: Cardinality = Field(default=Cardinality.ONE_TO_ONE, description="Relation cardinality")
    definition: Optional[CategoryDefinitionInput] = Field(default=None, description="This structure-relation category's complete rule (RFC 0012): which structure-relation claims count — by word, annotator, app and window — and whose standings fold. Omitted means primitive")


class MeasurementDefinitionInput(EdgeDefinitionInput):
    """Input for a relation definition."""

    source: StructureDescriptorInput = Field(..., description="Source entity type(s)")
    target: EntityDescriptorInput = Field(..., description="Target entity type(s)")
    properties: List[PropertyDefinitionInput] = Field(default_factory=list, description="Derived property definitions")
    definition: Optional[CategoryDefinitionInput] = Field(default=None, description="This measurement category's complete rule (RFC 0012): which measurement claims count and whose standings fold. Omitted means primitive")


class GraphTableQueryInput(StrictModel):
    """A saved table query declared inside a graph definition's `extensions` — as a plan, like every saved query."""

    key: str = Field(..., description="Unique key for this query within its graph")
    name: Optional[str] = Field(default=None, description="Human-readable name (defaults to `key`)")
    description: Optional[str] = Field(default=None, description="Description of this query")
    plan: TableQueryPlanInput = Field(..., description="What the query means; compiled by each projection kind")
    column_input: List[ColumnInput] = Field(default_factory=list, description="How the returned aliases are presented")


class CreateGraphTableQueryInput(StrictModel):
    """A saved table query, as a plan. There is no raw-Cypher form any more."""

    graph: strawberry.ID = Field(..., description="The graph id this table query will belong to")
    key: str = Field(..., description="Unique key for this query within its graph, used for referencing in the UI")
    name: Optional[str] = Field(default=None, description="Human-readable name (defaults to `key`)")
    description: Optional[str] = Field(default=None, description="Description of this query")
    plan: TableQueryPlanInput = Field(..., description="What the query means; compiled by each projection kind")
    column_input: List[ColumnInput] = Field(default_factory=list, description="How the returned aliases are presented")


class UpdateGraphTableQueryInput(StrictModel):
    id: strawberry.ID = Field(..., description="The ID of the graph table query to update")
    key: Optional[str] = Field(default=None, description="Unique key for this query within its graph")
    name: Optional[str] = Field(default=None, description="Human-readable name")
    description: Optional[str] = Field(default=None, description="Description of this query")
    plan: Optional[TableQueryPlanInput] = Field(default=None, description="A new plan; omitted means unchanged")
    column_input: Optional[List[ColumnInput]] = Field(default=None, description="Definitions for the columns returned by this graph query")


class CreateGraphTableQueryThroughBuilderInput(StrictModel):
    """The builder's spelling of `CreateGraphTableQueryInput` — `builder_args` instead of `plan`. Upserts on `(graph, key)`."""

    graph: strawberry.ID = Field(..., description="The graph id this table query will belong to")
    key: str = Field(..., description="Unique key for this query within its graph")
    name: Optional[str] = Field(default=None, description="Human-readable name (defaults to `key`)")
    description: Optional[str] = Field(default=None, description="Description of this query")
    builder_args: BuilderArgsInput = Field(description="The builder arguments; stored as the query's plan")
    column_input: List[ColumnInput] = Field(default_factory=list, description="How the returned aliases are presented")


class DeleteGraphTableQueryInput(StrictModel):
    id: strawberry.ID = Field(..., description="The ID of the graph query to delete")


class ArchiveGraphTableQueryInput(StrictModel):
    id: strawberry.ID = Field(..., description="The ID of the graph query to archive")


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


class CreateRelationCategoryInput(EntityDefinitionInput):
    """Input for an entity definition at the graph level (not within an event)."""

    graph: str = Field(..., description="The graph id this entity will belong to")
    backfill: bool = Field(
        default=False,
        description=BACKFILL_FIELD_DESCRIPTION,
    )


class UpdateRelationCategoryInput(UpdateDefinitionInput):
    """Input for updating a relation category.

    Extends `UpdateDefinitionInput` — the all-optional patch shape — and used to
    extend `EntityDefinitionInput` — an *entity* shape, on a relation, the **create**-shaped input. That made
    `key` and `propertyDefinitions` mandatory on an update, and
    `update_relation_category` writes none of them: it sets label,
    description, colour, image and pin. A field that is accepted and discarded is
    worse than one that is refused, and these were required as well as discarded.
    """

    definition: Optional[CategoryDefinitionInput] = Field(default=None, description="New rule for this category (RFC 0009). Omitted means unchanged; to make it primitive again, use clearDefinition")
    clear_definition: bool = Field(default=False, description="Reset the category to primitive — any claim naming its word counts, standings organization grain")

    @model_validator(mode="after")
    def definition_and_clear_are_exclusive(self):
        if self.definition is not None and self.clear_definition:
            raise ValueError("Pass a new `definition` or `clearDefinition`, not both.")
        return self

    id: str = Field(..., description="The ID of the relation category to update")


class DeleteRelationCategoryInput(StrictModel):
    """Input for deleting an existing relation definition at the graph level."""

    id: str = Field(..., description="The ID of the relation category to delete")


class CreateMeasurementCategoryInput(MeasurementDefinitionInput):
    """Input for a measurement definition at the graph level."""

    graph: str = Field(..., description="The graph id this measurement category will belong to")


class UpdateMeasurementCategoryInput(UpdateDefinitionInput):
    """Input for updating a measurement category.

    Extends `UpdateDefinitionInput` — the all-optional patch shape — and used to
    extend `MeasurementDefinitionInput`, the **create**-shaped input. That made
    `key`, `source` and `target` mandatory on an update, and
    `update_measurement_category` writes none of them: it sets label,
    description, colour, image and pin. A field that is accepted and discarded is
    worse than one that is refused, and these were required as well as discarded.
    """

    definition: Optional[CategoryDefinitionInput] = Field(default=None, description="New rule for this category (RFC 0012). Omitted means unchanged; to make it primitive again, use clearDefinition")
    clear_definition: bool = Field(default=False, description="Reset the category to primitive — any claim naming its word counts, standings organization grain")

    @model_validator(mode="after")
    def definition_and_clear_are_exclusive(self):
        if self.definition is not None and self.clear_definition:
            raise ValueError("Pass a new `definition` or `clearDefinition`, not both.")
        return self


    id: str = Field(..., description="The ID of the measurement category to update")


class DeleteMeasurementCategoryInput(StrictModel):
    """Input for deleting an existing measurement definition at the graph level."""

    id: str = Field(..., description="The ID of the measurement category to delete")


class CreateStructureRelationCategoryInput(StructureRelationDefinitionInput):
    """Input for an entity definition at the graph level (not within an event)."""

    graph: str = Field(..., description="The graph id this entity will belong to")


class UpdateStructureRelationCategoryInput(UpdateDefinitionInput):
    """Input for updating a structure relation category.

    Extends `UpdateDefinitionInput` — the all-optional patch shape — and used to
    extend `EntityDefinitionInput` — an *entity* shape, which never carried `source`, `target` or `cardinality` at all, the **create**-shaped input. That made
    `key` and `propertyDefinitions` mandatory on an update, and
    `update_structure_relation_category` writes none of them: it sets label,
    description, colour, image and pin. A field that is accepted and discarded is
    worse than one that is refused, and these were required as well as discarded.
    """

    definition: Optional[CategoryDefinitionInput] = Field(default=None, description="New rule for this category (RFC 0012). Omitted means unchanged; to make it primitive again, use clearDefinition")
    clear_definition: bool = Field(default=False, description="Reset the category to primitive — any claim naming its word counts, standings organization grain")

    @model_validator(mode="after")
    def definition_and_clear_are_exclusive(self):
        if self.definition is not None and self.clear_definition:
            raise ValueError("Pass a new `definition` or `clearDefinition`, not both.")
        return self


    id: str = Field(..., description="The ID of the structure relation category to update")


class DeleteStructureRelationCategoryInput(StrictModel):
    """Input for deleting an existing structure relation definition at the graph level."""

    id: str = Field(..., description="The ID of the structure relation category to delete")


class RestoreStructureRelationDefinitionInput(StrictModel):
    """Input for restoring an existing structure relation definition at the graph level."""

    id: str = Field(..., description="The ID of the relation category to restore")


class PrefixInput(StrictModel):
    """Input for a graph prefix definition."""

    prefix: str = Field(..., description="The prefix string (e.g. 'OBI')")
    uri: str = Field(..., description="The URI that the prefix maps to (e.g. 'http://purl.obolibrary.org/obo/OBI_')")
    description: Optional[str] = Field(None, description="Description of this prefix")


class RoleMappingInput(StrictModel):
    """
    Input for role mappings in an event.
    """

    role: str = Field(..., description="The role name")
    entity_id: str = Field(..., description="The ID of the entity assigned to this role")


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

    event: str = Field(..., description="The ID of the event the entity took part in")
    entity: str = Field(..., description="The ID of the entity that took part")
    role: str = Field(..., description="Which role the entity played — the caller's own word; the write names no graph and no category")
    is_input: bool = Field(default=True, description="True if the entity went into the event, False if it came out of it")


class RetractParticipationInput(StrictModel):
    """Input for retracting one claim that an entity took part in an event."""

    id: str = Field(..., description="The evidence ID of the participation claim to retract")


class ParticipantInput(StrictModel):
    """One entity's part in an event, inside a batch."""

    entity: str = Field(..., description="The ID of the entity that took part")
    role: str = Field(..., description="Which role the entity played — the caller's own word; the write names no graph and no category")
    is_input: bool = Field(default=True, description="True if the entity went into the event, False if it came out of it")


class AssertParticipationsInput(StrictModel):
    """Input for claiming that several entities took part in one event.

    One call, one assertion. Asserting them one at a time records the same act as
    N separate claims by N separate assertions, and nothing can put those back
    together afterwards.
    """

    event: str = Field(..., description="The event the entities took part in")
    participants: List[ParticipantInput] = Field(..., description="Everyone who took part, and how")


class ClassificationInput(StrictModel):
    """One claim that a node is of a word, inside a batch."""

    node: str = Field(..., description="The node being classified")
    term: str = Field(..., description=TERM_FIELD_DESCRIPTION)


class ClassifyNodesInput(StrictModel):
    """Input for claiming that several nodes are of a word, as one act.

    Additive: this does not displace anyone else's claim, and the node keeps its
    identity. Which label a graph then shows is decided at projection time by
    whichever of its categories carry a definition.
    """

    classifications: List[ClassificationInput] = Field(..., description="The claims to record")


class RetractLinksInput(StrictModel):
    """Input for retracting several link claims as one act."""

    ids: List[str] = Field(..., description="The `Link` primary keys of the claims to retract")


class CommentOnStructureInput(StrictModel):
    """Input for remarking on an external datum.

    Takes `(identifier, object)` — a structure's identity — and mints the
    structure if this is the first sight of it, as one act, the way
    `assertMetricValue` does. Shape-compatible with lok's `createComment` input
    so a lok client can post the same tree here; there is no `notify` flag
    because kraph has no notification channel to honor it with, and accepting a
    flag that does nothing is the silent no-op this API keeps removing.
    """

    identifier: str = Field(..., description="The structure identifier of the datum, e.g. '@mikro/roi'")
    object: str = Field(..., description="The id of the external object on its service")
    descendants: List[DescendantNode] = Field(..., min_length=1, description="The rich body of the remark — a tree of LEAF/MENTION/PARAGRAPH nodes")
    parent: Optional[str] = Field(default=None, description="The comment this replies to. Must be on the same structure's thread")


class RetractCommentInput(StrictModel):
    """Input for claiming a remark no longer stands — withdrawn or resolved; the assertion records whose position it is."""

    id: str = Field(..., description="The ID of the comment to retract")


class AttestCommentInput(StrictModel):
    """Input for claiming a remark stands again — reopening, as new evidence."""

    id: str = Field(..., description="The ID of the comment to attest")


class RetractNaturalEventInput(StrictModel):
    """Input for retracting a natural event claim — a Standing(stands=False), not a deletion."""

    id: str = Field(..., description="The ID of the natural event to retract")


class ProtocolEventInput(EventInput):
    """Input for creating a new protocol event instance."""

    pass


class AssertProtocolEventExistsInput(ProtocolEventInput):
    """Input for creating a new protocol event instance."""

    pass


class RetractProtocolEventInput(StrictModel):
    """Input for retracting a protocol event claim — a Standing(stands=False), not a deletion."""

    id: str = Field(..., description="The ID of the protocol event to retract")


class EntityInput(StrictModel):
    """Input for creating a new entity instance."""

    term: str = Field(..., description=TERM_FIELD_DESCRIPTION)
    supporting_evidence: List[StructureReferenceInput] = Field(default_factory=list, description="List of evidence structures with measurements")


class AssertEntityExistsInput(EntityInput):
    """Input for claiming that an entity exists."""

    same_as: List[str] = Field(
        default_factory=list,
        description=(
            'Instances this new one is the same as. Saying "this is AIS 6" mints a fresh '
            "instance and claims it is the same as the one already known as AIS 6 — all under "
            "**one assertion**, because it is one act. Sameness is an equivalence with no "
            "primary, so which id you send is immaterial; entities only, never structures."
        ),
    )


class AssertSameInstanceInput(StrictModel):
    """Input for claiming two instances already recorded are one thing."""

    instances: List[str] = Field(
        ...,
        min_length=2,
        description="Two or more instance ids that name the same thing — entities or events alike. Every pair among them is claimed, under one assertion.",
    )


class RetractSameInstanceInput(StrictModel):
    """Input for withdrawing one sameness claim."""

    id: str = Field(..., description="The id of the sameness claim to retract")


class CategoryNodePositionInput(StrictModel):
    """Input for specifying the position of a node in the graph visualization."""

    category: strawberry.ID = Field(..., description="The category of the node")
    position_x: float = Field(..., description="The x-coordinate of the node position")
    position_y: float = Field(..., description="The y-coordinate of the node position")
    width: Optional[float] = Field(default=None, description="Optional width for the node (for visualization purposes)")
    height: Optional[float] = Field(default=None, description="Optional height for the node (for visualization purposes)")


class UpdateGraphVisuals(StrictModel):
    """Input for updating the visual properties of a graph element (node or edge)."""

    id: str = Field(..., description="The ID of the graph element to update")
    node_positions: list[CategoryNodePositionInput] = Field(default_factory=list, description="List of node positions to update")


class RetractEntityInput(StrictModel):
    """Input for retracting an entity claim — a Standing(stands=False), not a deletion."""

    id: str = Field(..., description="The ID of the entity to retract")


class AttestNodeInput(StrictModel):
    """Input for claiming that a node exists.

    Not the reverse of retracting — there is no state to reverse. Somebody is
    saying the thing is there, which is evidence of exactly the same kind as
    somebody saying it is not, and both stay on the record. Which of them a given
    graph believes is decided by its selector.
    """

    id: str = Field(..., description="The uuid of the node being attested. The same id `retract*` returns, so the two round-trip.")


class AttestStructureInput(StrictModel):
    """Input for claiming that a structure still stands.

    Part of closing a gap: `attest_*` covered four claim kinds out of ten, so a
    retraction of a structure, metric, relation, measurement, structure relation,
    participation or sameness had no counterpart and was one-way through the API.
    """

    id: str = Field(..., description="The ID of the structure to attest — a bare uuid, its evidence primary key")


class AttestMetricInput(StrictModel):
    """Input for claiming that a measurement still stands. See `AttestStructureInput`."""

    id: str = Field(..., description="The ID of the metric to attest — a bare uuid, its evidence primary key")


class AttestLinkInput(StrictModel):
    """Input for claiming that a link claim still stands. See `AttestStructureInput`.

    One input for every link kind, as `RetractLinksInput` is: the act does not
    differ by kind, and the row says which kind it is.
    """

    id: str = Field(..., description="The ID of the claim to attest — its `Link` primary key")


class AttestEntityInput(AttestNodeInput):
    """Input for claiming that an entity exists."""


class AttestNaturalEventInput(AttestNodeInput):
    """Input for claiming that a natural event exists."""


class AttestProtocolEventInput(AttestNodeInput):
    """Input for claiming that a protocol event exists."""


class StructureInput(StrictModel):
    """Input for creating a new structure instance.

    Two fields, and there were three. Removing `PinNodeInput` left its `user`
    field behind under the comment that explained the removal — and **a comment
    does not end a block**, so the indented line stayed part of this class. Every
    subclass inherited it, and all three use `all_fields=True`, so
    `assertStructureExists`, `ensureStructure` and `updateStructure` advertised
    `user: String` in the SDL, accepted it, and dropped it: no controller reads
    it. A field that is accepted and discarded is worse than one that is refused,
    which is the whole reason these models are `extra="forbid"`.
    """

    object: str = Field(..., description="The unique ID of the object this structure references")
    metrics: List["MetricInput"] = Field(default_factory=list, description="List of measurements associated with this structure")


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

    id: str = Field(..., description="The ID of the structure to update")


class RetractStructureInput(StrictModel):
    """Input for retracting a structure claim. Not a soft delete: the row and its metrics survive, and the retraction is its own assertion on the record."""

    id: str = Field(..., description="The ID of the structure to retract — a bare uuid, its evidence primary key")


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

    structure: str = Field(..., description="The unique ID of the structure this metric is associated with")


class RetractMetricInput(StrictModel):
    """Input for retracting a measurement. Not a soft delete: it stays readable, because a derived value that dropped it still has to be explainable."""

    id: str = Field(..., description="The ID of the metric to retract — a bare uuid, its evidence primary key")


class RelationInput(StrictModel):
    """Input for a measurement/metric."""

    source_id: str = Field(..., description="The ID of the source entity/structure")
    target_id: str = Field(..., description="The ID of the target entity/structure")
    supporting_evidence: List[StructureReferenceInput] = Field(default_factory=list, description="List of evidence structures with measurements")


class EventBaseInput(StrictModel):
    valid_from: Optional[datetime] = Field(default=None, description="Optional start time for the validity of this event (for temporal reasoning)")
    valid_to: Optional[datetime] = Field(default=None, description="Optional end time for the validity of this event (for temporal reasoning)")


class AssertRelationExistsInput(RelationInput):
    """Input for creating a new relation associated with a structure."""

    term: str = Field(..., description=TERM_FIELD_DESCRIPTION)


class UpdateRelationInput(RelationInput):
    """Input for updating an existing relation. Note: this will not update the relation in-place, but rather create a new relation and archive the old one to preserve history."""

    id: str = Field(..., description="The ID of the relation to update")


class RetractRelationInput(StrictModel):
    """Input for retracting a relation claim. Not a soft delete: the edge survives wherever another live assertion still states the same proposition."""

    id: str = Field(..., description="The ID of the relation claim to retract — its `Link` primary key")


class AssertStructureRelationExistsInput(RelationInput):
    """Input for creating a new structure relation edge."""

    term: str = Field(..., description=TERM_FIELD_DESCRIPTION)


class UpdateStructureRelationInput(RelationInput):
    """Input for updating an existing structure relation by replacing it with a new edge revision."""

    id: str = Field(..., description="The ID of the structure relation to update")


class RetractStructureRelationInput(StrictModel):
    """Input for retracting a structure relation claim. Not a soft delete — see `RetractRelationInput`."""

    id: str = Field(..., description="The ID of the structure relation claim to retract — its `Link` primary key")


class AssertMeasurementExistsInput(RelationInput):
    """Input for creating a new measurement edge associated with a structure/entity pair."""

    term: str = Field(..., description=TERM_FIELD_DESCRIPTION)


class RetractMeasurementInput(StrictModel):
    """Input for retracting a measurement claim. Not a soft delete — see `RetractRelationInput`."""

    id: str = Field(..., description="The ID of the measurement claim to retract — its `Link` primary key")


class ScatterPlotMutationInput(StrictModel):
    """Base input for scatter plot mutations."""

    name: str = Field(..., description="The display name of the scatter plot")
    description: Optional[str] = Field(default=None, description="Optional description of the scatter plot")
    graph_query_id: int = Field(..., description="The graph table query this scatter plot is drawn from")
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


class SupersedeMetricValueInput(MetricInput):
    """Input for updating an existing metric. The metric will not be updated in-place, but a new metric will be created and the old one archived to preserve history."""

    id: str = Field(..., description="The ID of the metric to update")


class GraphExtensionsInput(StrictModel):
    """
    Input for graph extensions (the main schema content).

    Note: Structures are no longer defined in the schema. They are resolved
    dynamically from the structure identifier at write time.
    """

    prefixes: List[PrefixInput] = Field(default_factory=list, description="Graph prefixes for namespacing")
    entities: List[EntityDefinitionInput] = Field(default_factory=list, description="Entity definitions")
    relations: List[RelationDefinitionInput] = Field(default_factory=list, description="Relation definitions")
    structure_relations: List[StructureRelationDefinitionInput] = Field(default_factory=list, description="Structure relation definitions")
    measurements: List[MeasurementDefinitionInput] = Field(default_factory=list, description="Measurement definitions")
    events: List[EventDefinitionInput] = Field(default_factory=list, description="Event definitions")

    # insights
    graph_table_queries: List[GraphTableQueryInput] = Field(default_factory=list, description="Graph table query definitions")
    scatter_plots: List[ScatterPlotInput] = Field(default_factory=list, description="Scatter plot definitions")


class GraphDefinitionInput(StrictModel):
    """
    Input model for a complete graph schema definition.

    This is the full schema that defines entities, structures, relations,
    and events for a knowledge graph.
    """

    system_version: str = Field(default="0.0.1", description="Semantic version for this schema definition (e.g., '1.0.0')")
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


# `SetSchemaPayload` / `SetSchemaResult` are gone: they were wired to no
# mutation, so the fields were decoration.


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


# `PinGraphInput` used to sit here, alongside a `pin_graph` resolver that was
# never mounted on `Mutation` — so neither the input nor the field ever reached
# the schema.


# Backwards-compatible aliases used by older tests and callsites.
GraphDefinitionModel = GraphDefinitionInput
GraphExtensions = GraphExtensionsInput
EntityDefinition = EntityDefinitionInput
PropertyDefinition = PropertyDefinitionInput
