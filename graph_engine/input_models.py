from pydantic import BaseModel, Field, field_validator, model_validator
from typing import List, Dict, Optional, Any, Union, Literal
from datetime import datetime, timezone
import uuid
import re

# ==========================================
# INPUT MODELS
# ==========================================

class MeasurementInput(BaseModel):
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

    @field_validator('timestamp', mode='before')
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
                v = v.replace('Z', '+00:00')
                dt = datetime.fromisoformat(v)
                return int(dt.timestamp() * 1000)
            except ValueError:
                raise ValueError(f"Invalid timestamp format: {v}")

        raise ValueError(f"Unsupported timestamp type: {type(v)}")


def create_max_confidence_measurement(key: str, value: Any, unit: Optional[str] = None, timestamp: Any = None) -> MeasurementInput:
    """ Helper to create a measurement with max confidence """
    return MeasurementInput(
        key=key,
        value=value,
        confidence=1.0,
        confidence_type="max",
        unit=unit,
        timestamp=timestamp
    )

class StructureReference(BaseModel):
    identifier: str = Field(..., description="Schema identifier, e.g. '@mikro/roi'")
    object: str = Field(..., description="The unique ID of the object this structure references")
    measurements: List[MeasurementInput] = []

def create_told_you_so(measurements: List[MeasurementInput], object: str) -> StructureReference:
    return StructureReference(identifier="told_you_so", object=object, measurements=measurements)

class ProvenanceContext(BaseModel):
    subject: str = Field(..., description="User ID")
    app_id: str = Field(..., description="Client ID")
    action_id: Optional[str] = None
    action_name: Optional[str] = None
    action_args: Optional[Dict[str, Any]] = None

class EntityCreationPayload(BaseModel):
    ref_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    kind: str
    supporting_evidence: List[StructureReference] = []
    provenance: ProvenanceContext
    
    
    
# ... [Previous imports & models: MeasurementInput, StructureReference, ProvenanceContext] ...

class RelationCreationPayload(BaseModel):
    """
    Payload to create a relationship backed by evidence.
    """
    ref_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    kind: str = Field(..., description="The relationship label (e.g. 'CONNECTED_TO')")
    
    source_id: str = Field(..., description="The ID of the source entity")
    target_id: str = Field(..., description="The ID of the target entity")
    
    # Evidence is used to calculate properties on the edge (e.g. confidence)
    supporting_evidence: List[StructureReference] = []
    provenance: ProvenanceContext
    
    

class EntityCreationResult(BaseModel):
    ref_id: str
    db_id: str
    graph_id: Any
    status: str = "CREATED"


class StructureCreationPayload(BaseModel):
    """Payload for creating a structure."""
    identifier: str = Field(..., description="Schema identifier, e.g. '@mikro/roi'")
    object: str = Field(..., description="The unique ID of the object this structure references")


class StructureCreationResult(BaseModel):
    """Result of structure creation."""
    id: str
    identifier: str
    label: str
    status: str = "CREATED"


class AddMeasurementPayload(BaseModel):
    """Payload for adding a measurement to a structure."""
    structure_identifier: str = Field(..., description="Schema identifier of the structure")
    structure_id: str = Field(..., description="The unique ID of the structure")
    measurement: MeasurementInput
    provenance: ProvenanceContext


# ==========================================
# SCHEMA MANAGEMENT MODELS
# ==========================================

# Semantic version regex: major.minor.patch with optional pre-release and build metadata
# Based on semver.org specification
SEMVER_REGEX = re.compile(
    r'^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)'  # MAJOR.MINOR.PATCH
    r'(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)'  # Pre-release (optional)
    r'(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?'  # ... continued
    r'(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$'  # Build metadata (optional)
)


def validate_semver(version: str) -> str:
    """Validate that a string is a valid semantic version."""
    if not SEMVER_REGEX.match(version):
        raise ValueError(
            f"'{version}' is not a valid semantic version. "
            f"Expected format: MAJOR.MINOR.PATCH (e.g., '1.0.0', '2.1.3-beta.1')"
        )
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


# --- Schema Definition Input Models ---
# These mirror the base_models but are used for input validation

class DerivationRuleInput(BaseModel):
    """Input for a derivation rule configuration."""
    source_node: Optional[str] = Field(None, description="The label of the describing structure to read from")
    key: Optional[str] = Field(None, description="The property key on the source node")
    aggregation: Optional[str] = Field(None, description="Aggregation function (MEAN, SUM, MAX, MIN, COUNT, etc.)")


class PropertyDefinitionInput(BaseModel):
    """Input for a property definition on a node or relation."""
    key: str = Field(..., description="Property key/name")
    type: str = Field(..., description="Property type: string, float, integer, boolean, datetime, point_3d")
    unit: Optional[str] = Field(None, description="Unit of measurement")
    description: Optional[str] = Field(None, description="Description of this property")
    derivation: str = Field("LATEST", description="Derivation type: LATEST, PRIORITY_LATEST, ROLLUP, LATEST_ASSERTION_TOOL")
    rule: Optional[DerivationRuleInput] = Field(None, description="Rule configuration for ROLLUP derivation")
    
    @field_validator('type')
    @classmethod
    def validate_type(cls, v: str) -> str:
        valid_types = {'string', 'float', 'integer', 'boolean', 'datetime', 'point_3d'}
        if v.lower() not in valid_types:
            raise ValueError(f"Invalid property type '{v}'. Must be one of: {', '.join(valid_types)}")
        return v.lower()
    
    @field_validator('derivation')
    @classmethod
    def validate_derivation(cls, v: str) -> str:
        valid_derivations = {'LATEST', 'PRIORITY_LATEST', 'ROLLUP', 'LATEST_ASSERTION_TOOL'}
        if v.upper() not in valid_derivations:
            raise ValueError(f"Invalid derivation type '{v}'. Must be one of: {', '.join(valid_derivations)}")
        return v.upper()


class EntityDefinitionInput(BaseModel):
    """Input for an entity definition."""
    key: str = Field(..., description="Entity type name/key")
    description: Optional[str] = Field(None, description="Description of this entity type")
    properties: List[PropertyDefinitionInput] = Field(default_factory=list, description="Property definitions")


class StructureDefinitionInput(BaseModel):
    """Input for a structure definition."""
    key: str = Field(..., description="Structure type name/key")
    description: Optional[str] = Field(None, description="Description of this structure type")


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


class RelationDefinitionInput(BaseModel):
    """Input for a relation definition."""
    key: str = Field(..., description="Relation type name/key")
    source: List[str] = Field(..., description="Source entity type(s)")
    target: List[str] = Field(..., description="Target entity type(s)")
    cardinality: Literal["1:1", "1:N", "N:N"] = Field("1:N", description="Relation cardinality")
    materialization: Optional[MaterializationConfigInput] = Field(None, description="Materialization config if this relation is derived from evidence")
    
    @field_validator('source', 'target', mode='before')
    @classmethod
    def coerce_to_list(cls, v):
        """Accept either a single string or list of strings, always return list."""
        if isinstance(v, str):
            return [v]
        return v


class EventDefinitionInput(BaseModel):
    """Input for an event definition."""
    key: str = Field(..., description="Event type name/key")
    inputs: List[str] = Field(default_factory=list, description="Input node types")
    outputs: List[str] = Field(default_factory=list, description="Output node types")
    properties: List[PropertyDefinitionInput] = Field(default_factory=list, description="Property definitions")


class GraphExtensionsInput(BaseModel):
    """Input for graph extensions (the main schema content)."""
    structures: List[StructureDefinitionInput] = Field(default_factory=list, description="Structure definitions")
    entities: List[EntityDefinitionInput] = Field(default_factory=list, description="Entity definitions")
    relations: List[RelationDefinitionInput] = Field(default_factory=list, description="Relation definitions")
    events: List[EventDefinitionInput] = Field(default_factory=list, description="Event definitions")
    
    @model_validator(mode='after')
    def validate_relation_references(self):
        """Validate that relations reference existing entity/structure types."""
        all_nodes = {s.key for s in self.structures} | {e.key for e in self.entities}
        
        for rel in self.relations:
            sources = [rel.source] if isinstance(rel.source, str) else rel.source
            targets = [rel.target] if isinstance(rel.target, str) else rel.target
            
            for s in sources:
                if s not in all_nodes:
                    raise ValueError(f"Relation '{rel.key}' source '{s}' is not a defined structure or entity")
            for t in targets:
                if t not in all_nodes:
                    raise ValueError(f"Relation '{rel.key}' target '{t}' is not a defined structure or entity")
        
        return self


class GraphDefinitionInput(BaseModel):
    """
    Input model for a complete graph schema definition.
    
    This is the full schema that defines entities, structures, relations,
    and events for a knowledge graph.
    """
    system_version: str = Field(..., description="Semantic version for this schema definition (e.g., '1.0.0')")
    extensions: GraphExtensionsInput = Field(..., description="The graph extensions containing all type definitions")
    
    @field_validator('system_version')
    @classmethod
    def validate_system_version(cls, v: str) -> str:
        return validate_semver(v)


class SetSchemaPayload(BaseModel):
    """Payload for setting a new schema on a graph."""
    version: str = Field(..., description="Semantic version for this schema (e.g., '1.0.0', '1.1.0')")
    definition: GraphDefinitionInput = Field(..., description="The complete graph schema definition")
    description: Optional[str] = Field(None, description="Description of changes in this schema version")
    activate: bool = Field(True, description="Whether to immediately activate this schema")
    
    @field_validator('version')
    @classmethod
    def validate_version(cls, v: str) -> str:
        return validate_semver(v)


class SetSchemaResult(BaseModel):
    """Result of setting a new schema."""
    schema_id: int = Field(..., description="Database ID of the created schema")
    version: str = Field(..., description="Version string of the schema")
    index: int = Field(..., description="Sequential index of this schema")
    is_active: bool = Field(..., description="Whether this schema is now active")