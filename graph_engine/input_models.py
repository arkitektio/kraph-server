from asyncio import Protocol
from enum import Enum
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import List, Dict, Optional, Any, Literal
from datetime import datetime, timezone
import uuid
import re

from graph_engine.base_models import AGGREGATION_RESULT_TYPES, AggregationFunction, DerivationType



# ==========================================
# SCHEMA INPUT MODELS
# ==========================================


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
    metrics: List[MetricInput] = []

def create_told_you_so(metrics: List[MetricInput], object: str) -> StructureReference:
    return StructureReference(identifier="told_you_so", object=object, metrics=metrics)

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
    graph_id: Optional[Any] = None  # This will be filled in by the controller after creation
    
    
    
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


class AddMetricPayload(BaseModel):
    """Payload for adding a metric to a structure."""
    structure_identifier: str = Field(..., description="Schema identifier of the structure")
    structure_id: str = Field(..., description="The unique ID of the structure")
    metric: MetricInput
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


    
    
class OntologyReferenceInput(BaseModel):
    """Input for an ontology reference."""
    prefix: str = Field(..., description="The ontology prefix (e.g. 'OBI'). Must be defined in graph prefixes.")
    uri: str = Field(..., description="The full URI for the ontology term")


# --- Schema Definition Input Models ---
# These mirror the base_models but are used for input validation

class DerivationRuleInput(BaseModel):
    """Input for a derivation rule configuration."""
    source_node: Optional[str] = Field(None, description="The label of the describing structure to read from")
    key: Optional[str] = Field(None, description="The property key on the source node")
    aggregation: Optional[AggregationFunction] = Field(None, description="Aggregation function (MEAN, SUM, MAX, MIN, COUNT, etc.)")


class PropertyDefinitionInput(BaseModel):
    """Input for a property definition on a node or relation."""
    key: str = Field(..., description="Property key/name")
    type: str = Field(..., description="Property type: string, float, integer, boolean, datetime, point_3d")
    unit: Optional[str] = Field(None, description="Unit of measurement")
    description: Optional[str] = Field(None, description="Description of this property")
    derivation: DerivationType = Field(DerivationType.LATEST, description="Derivation type: LATEST, PRIORITY_LATEST, ROLLUP, LATEST_ASSERTION_TOOL")
    rule: Optional[DerivationRuleInput] = Field(None, description="Rule configuration for ROLLUP derivation")
    index: bool = Field(False, description="Whether to create an index on this property for faster queries")
    searchable: bool = Field(False, description="Whether this property should be full-text searchable")
    
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
    
    @model_validator(mode='after')
    def validate_rule_presence(self):
        """If using ROLLUP, a rule definition is mandatory."""
        if self.derivation == DerivationType.ROLLUP and not self.rule:
            raise ValueError("Property with derivation 'ROLLUP' must have a 'rule' configuration.")
        return self
    
    @model_validator(mode='after')
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
        
        # If aggregation has a fixed result type, check compatibility
        if expected_result_type is not None and self.type != expected_result_type:
            raise ValueError(
                f"Aggregation '{aggregation.value}' produces type '{expected_result_type.value}', "
                f"but property is defined as '{self.type.value}'. "
                f"Change property type to '{expected_result_type.value}'."
            )
        
        return self


class SequenceMapping(BaseModel):
    """Input for a sequence mapping within a structure."""
    sequence: str = Field(..., description="The sequence identifier (e.g., 'IAZ001')")
    property: str = Field(..., description="The property key that will be set with the sequence value")


class NodeDefinitionInput(BaseModel):
    """Input for a node definition within an event."""
    sequences: List[SequenceMapping] = Field(default_factory=list, description="Sequence mappings for this node")
    key: str = Field(..., description="The label of the node participating in the event")
    description: Optional[str] = Field(None, description="Description of this node role")
    ontology_references: List[OntologyReferenceInput] = Field(default_factory=list, description="Ontology references for this event")
    tags: List[str] = Field(default_factory=list, description="Optional tags for this node role (e.g. 'cell_body', 'dendrite', 'axon')")
    color: Optional[List[int]] = Field(None, description="Optional RGBA color for this node role (e.g. [255, 0, 0, 128])")
    image: Optional[str] = Field(None, description="Optional media store ID for an image representing this node role")
    label: Optional[str] = Field(None, description="Optional human-readable label for this node role (defaults to 'key' if not provided)")
    pin: Optional[bool] = Field(None, description="Whether to pin this node role in the UI")


class EntityDefinitionInput(NodeDefinitionInput):
    """Input for an entity definition."""
    properties: List[PropertyDefinitionInput] = Field(default_factory=list, description="Property definitions")

    @field_validator('properties')
    @classmethod
    def validate_properties(cls, v: List[PropertyDefinitionInput]) -> List[PropertyDefinitionInput]:
        """Validate that property keys are unique within this entity definition."""
        keys = set()
        for prop in v:
            if prop.key in keys:
                raise ValueError(f"Duplicate property key '{prop.key}' in entity definition")
            keys.add(prop.key)
            
            
            
        return v


class CreateEntityDefinitionInput(EntityDefinitionInput):
    """Input for an entity definition at the graph level (not within an event)."""
    graph: str = Field(..., description="The graph id this entitiy will beong to")
    
    
class UpdateEntityDefinitionInput(EntityDefinitionInput):
    """Input for updating an existing entity definition at the graph level."""
    id: str = Field(..., description="The ID of the entity category to update")


class DeleteEntityDefinitionInput(BaseModel):
    """Input for deleting an existing entity definition at the graph level."""
    id: str = Field(..., description="The ID of the entity category to delete")



class EventKind(str, Enum):
    """Role type for a node in an event."""
    INTRINSIC= "intrinsic"
    EXTRINSIC = "extrinsic"
    
    
    
class EntityCategoryProtocol(Protocol):
    """Protocol for entity categories to provide source definition for event linking."""
    id: str
    tags: List[str]
    ontology_references: List[OntologyReferenceInput]
        
    
    
class EntityDescriptorInput(BaseModel):
    """Input for filtering entities when linking to a structure."""
    category: Optional[List[str]] = Field(None, description="Filter by entity category/label")
    tags: Optional[List[str]] = Field(None, description="Filter by tags on the entity")
    ontotology_terms: Optional[List[str]] = Field(None, description="Filter by ontology references on the entity (format: 'PREFIX:TERM_ID')")
    
    
    def matches(self, entity: EntityCategoryProtocol) -> bool:
        """Check if a given entity matches this descriptor."""
        if self.category and entity.id not in self.category:
            return False
        if self.tags and not set(self.tags).issubset(set(entity.tags)):
            return False
        if self.ontotology_terms and not set(self.ontotology_terms).issubset(set(map(lambda x: x.uri, entity.ontology_references))):
            return False
        return True

class EventRoleInput(BaseModel):
    """Input for a role of a node in an event (input or output)."""
    key: str = Field(..., description="The label of the node participating in the event")
    role: str = Field(..., description="What type of role does this node play in the event")
    descriptor: EntityDescriptorInput = Field(..., description="Optional filters to apply when linking entities to structures for this role")
    ontology_references: List[OntologyReferenceInput] = Field(default_factory=list, description="Ontology references for this event")
    



class EventDefinitionInput(NodeDefinitionInput):
    """Input for an event definition."""
    inputs: List[EventRoleInput] = Field(default_factory=list, description="Input node roles")
    outputs: List[EventRoleInput] = Field(default_factory=list, description="Output node roles")
    properties: List[PropertyDefinitionInput] = Field(default_factory=list, description="Property definitions")
    ontology_references: List[OntologyReferenceInput] = Field(default_factory=list, description="Ontology references for this event")



class CreateEventDefinitionInput(EventDefinitionInput):
    """Input for an event definition at the graph level (not within an event)."""
    graph: str = Field(..., description="The graph id this event will belong to")
    
    
class UpdateEventDefinitionInput(EventDefinitionInput):
    """Input for updating an existing event definition at the graph level."""
    id: str = Field(..., description="The ID of the event category to update")


class DeleteEventDefinitionInput(BaseModel):
    """Input for deleting an existing event definition at the graph level."""
    id: str = Field(..., description="The ID of the event category to delete")


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
    ontology_references: List[OntologyReferenceInput] = Field(default_factory=list, description="Ontology references for this event")
    key: str = Field(..., description="Relation type name/key")
    source: List[EntityDescriptorInput] = Field(..., description="Source entity type(s)")
    target: List[EntityDescriptorInput] = Field(..., description="Target entity type(s)")
    cardinality: Literal["1:1", "1:N", "N:N"] = Field("1:N", description="Relation cardinality")
    properties: List[PropertyDefinitionInput] = Field(default_factory=list, description="Derived property definitions")

    @field_validator('source', 'target', mode='before')
    @classmethod
    def coerce_to_list(cls, v):
        """Accept either a single string or list of strings, always return list."""
        if isinstance(v, str):
            return [v]
        return v




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
    entity_id: str = Field(..., description="The ID of the entity assigned to this role")
    
class EventInput(BaseModel):
    """Input for creating a new event instance."""
    event_category: str = Field(..., description="The ID of the event category/type to create")
    inputs: List[RoleMappingInput] = Field(default_factory=list, description="List of entity IDs that are inputs to this event")
    outputs: List[RoleMappingInput] = Field(default_factory=list, description="List of entity IDs that are outputs of this event")
    supporting_evidence: List[StructureReference] = Field(default_factory=list, description="List of evidence structures with measurements")
    provenance: ProvenanceContext
    

class NaturalEventInput(EventInput):
    """Input for creating a new natural event instance."""
    pass
    
    
class CreateNaturalEventInput(NaturalEventInput):
    """Input for creating a new natural event instance."""
    event_category: str = Field(..., description="The ID of the natural event category/type to create")
    
class UpdateNaturalEventInput(NaturalEventInput):
    """Input for updating an existing natural event instance."""
    id: str = Field(..., description="The ID of the natural event to update")
    
class DeleteNaturalEventInput(BaseModel):
    """Input for deleting an existing natural event instance."""
    id: str = Field(..., description="The ID of the natural event to delete")
    
   
 
class StructureInput(BaseModel):
    """Input for creating a new structure instance."""
    identifier: str = Field(..., description="Schema identifier, e.g. '@mikro/roi'")
    object: str = Field(..., description="The unique ID of the object this structure references")
    metrics: List[MetricInput] = Field(default_factory=list, description="List of measurements associated with this structure")
    
    
class CreateStructureInput(StructureInput):
    """Input for creating a new structure instance."""
    graph: str = Field(..., description="The graph id this structure will belong to")
    
    
   
   
   

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
    
    @model_validator(mode='after')
    def validate_relation_references(self):
        """Validate that relations reference existing entity types or structure labels."""
        from graph_engine.base_models import IDENTIFIER_MAP
        
        # Structure labels from IDENTIFIER_MAP are valid
        structure_labels = set(IDENTIFIER_MAP.values())
        all_nodes = structure_labels | {e.key for e in self.entities}
        
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



class GraphInput(BaseModel):
    """Input for creating or updating a graph."""
    name: str = Field(..., description="Name of the graph")
    description: Optional[str] = Field(None, description="Description of the graph")
    definition: GraphDefinitionInput = Field(..., description="The complete graph schema definition")



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
    
    
    
class EntityCreationInput(BaseModel):
    """Input for creating a new entity with supporting evidence."""
    entity_category: str = Field(..., description="The ID of the entity category/type to create")
    supporting_evidence: List[StructureReference] = Field(default_factory=list, description="List of evidence structures with measurements")
    