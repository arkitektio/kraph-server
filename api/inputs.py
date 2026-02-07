"""
GraphQL Input types for the API using strawberry-pydantic.

These inputs use strawberry.experimental.pydantic to automatically
validate against the Pydantic input models from graph_engine.
"""
import strawberry
from strawberry.experimental import pydantic
from typing import Optional, List
from enum import Enum

from graph_engine import input_models
from .scalars import AnyScalar



# ==========================================
# Schema Creation Input Types
# ==========================================

@pydantic.input(model=input_models.CreateEntityDefinitionInput, fields=["__all__"], description="Input for creating a new entity definition in the graph schema")
class CreateEntityDefinitionInput:
    pass

@pydantic.input(model=input_models.UpdateEntityDefinitionInput, fields=["__all__"], description="Input for updating an existing entity definition in the graph schema")
class UpdateEntityDefinitionInput:
    pass
   
@pydantic.input(model=input_models.DeleteEntityDefinitionInput, fields=["__all__"], description="Input for deleting an existing entity definition in the graph schema")
class DeleteEntityDefinitionInput:
    pass



@pydantic.input(model=input_models.CreateEventDefinitionInput, fields=["__all__"], description="Input for creating a new entity definition in the graph schema")
class CreateEventDefinitionInput:
    pass

@pydantic.input(model=input_models.UpdateEntityDefinitionInput, fields=["__all__"], description="Input for updating an existing entity definition in the graph schema")
class UpdateEventDefinitionInput:
    pass
   
@pydantic.input(model=input_models.DeleteEventDefinitionInput, fields=["__all__"], description="Input for deleting an existing event definition in the graph schema")
class DeleteEventDefinitionInput:
    pass
# ==========================================
# Object Creation Input Types
# ==========================================


@pydantic.input(model=input_models.CreateNaturalEventInput, fields=["__all__"], description="Input for creating a new natural event instance")
class CreateNaturalEventInput:
    """Input for creating a new natural event instance."""
    pass







@pydantic.input(model=input_models.MetricInput)
class MetricInput:
    """
    A single measurement entry.
    Timestamps are automatically validated and converted to Unix Epoch Milliseconds.
    """
    key: strawberry.auto
    value: AnyScalar  # Override Any with our custom scalar
    confidence: strawberry.auto
    confidence_type: strawberry.auto
    unit: strawberry.auto
    timestamp: strawberry.auto
    ontology_terms: Optional[List[str]] = strawberry.field(default_factory=list, description="Optional list of ontology term IDs associated with this measurement. Is there an ontology describing this measurement? If so, include relevant term IDs here to link this measurement to the ontology.")


@pydantic.input(model=input_models.StructureReference)
class StructureReferenceInput:
    """
    Reference to an existing or new structure with optional measurements.
    """
    identifier: strawberry.auto
    object: strawberry.auto
    measurements: Optional[List[MetricInput]] = strawberry.field(default_factory=list)


@pydantic.input(model=input_models.ProvenanceContext)
class ProvenanceInput:
    """
    Provenance context for tracking who created what and when.
    """
    subject: strawberry.auto
    app_id: strawberry.auto
    action_id: strawberry.auto
    action_name: strawberry.auto
    action_args: Optional[AnyScalar] = None  # Override Dict[str, Any] with our scalar


@pydantic.input(model=input_models.EntityCreationInput, description="Input for creating a new entity with supporting evidence")
class EntityCreationInput:
    """
    Input for creating a new entity with supporting evidence.
    
    Provenance (subject, app_id) is automatically derived from the 
    authenticated request context.
    """
    entity_category: strawberry.ID = strawberry.field(default=None, description="Optional entity category/type")
    supporting_evidence: Optional[List[StructureReferenceInput]] = strawberry.field(default_factory=list, description="List of evidence structures with measurements")
    

@strawberry.input(description="Input for recalculating entity properties")
class RecalculateEntityInput:
    """Input for recalculating an entity's derived properties."""
    graph_id: strawberry.ID = strawberry.field(description="The ID of the graph containing the entity")
    entity_id: str = strawberry.field(description="The entity's string ID")
    


@pydantic.input(model=input_models.StructureCreationPayload)
class StructureCreationInput:
    """
    Input for creating a standalone structure.
    Validates against StructureCreationPayload Pydantic model.
    """
    identifier: strawberry.auto
    object: strawberry.auto


@pydantic.input(model=input_models.RelationCreationPayload)
class RelationCreationInput:
    """
    Input for creating a relation between two entities with supporting evidence.
    Validates against RelationCreationPayload Pydantic model.
    """
    ref_id: strawberry.auto
    kind: strawberry.auto
    source_id: strawberry.auto
    target_id: strawberry.auto
    supporting_evidence: Optional[List[StructureReferenceInput]] = strawberry.field(default_factory=list)
    provenance: ProvenanceInput


# ==========================================
# ADDITIONAL INPUT TYPES (not in input_models)
# ==========================================






@pydantic.input(model=input_models.OntologyReferenceInput)
class OntologyReferenceInput:
    """Input for an ontology reference."""
    prefix: strawberry.auto
    uri: strawberry.auto


@strawberry.input(description="Input for adding a measurement to a structure")
class AddMeasurementInput:
    """Input for adding a measurement to an existing structure."""
    structure_id: strawberry.ID = strawberry.field(description="ID of the structure to add the measurement to")  
    measurement: MeasurementInput = strawberry.field(description="The measurement to add")
    provenance: ProvenanceInput = strawberry.field(description="Provenance context for this measurement")


@strawberry.input(description="Input for linking a structure to an entity")
class LinkStructureInput:
    """Input for linking an existing structure to an entity."""
    structure_identifier: str = strawberry.field(description="Structure identifier")
    structure_object: str = strawberry.field(description="Structure object ID")
    entity_id: str = strawberry.field(description="Entity ID to link to")
    recalculate: Optional[bool] = strawberry.field(
        default=True, 
        description="Whether to recalculate entity properties after linking"
    )


# ==========================================
# SCHEMA DEFINITION INPUT TYPES (List-based)
# ==========================================

@pydantic.input(model=input_models.DerivationRuleInput)
class DerivationRuleInput:
    """Configuration for property derivation rules."""
    source_node: strawberry.auto
    key: strawberry.auto
    aggregation: strawberry.auto


@pydantic.input(model=input_models.PropertyDefinitionInput)
class PropertyDefinitionInput:
    """Definition of a property on an entity, structure, or relation."""
    key: strawberry.auto
    type: strawberry.auto
    unit: strawberry.auto
    ontology_references: Optional[List[OntologyReferenceInput]] = strawberry.field(default_factory=list)
    description: strawberry.auto
    derivation: strawberry.auto
    rule: Optional[DerivationRuleInput] = None


@pydantic.input(model=input_models.EntityDefinitionInput)
class EntityDefinitionInput:
    """Definition of an entity type in the graph schema."""
    key: strawberry.auto
    description: strawberry.auto
    ontology_references: Optional[List[OntologyReferenceInput]] = strawberry.field(default_factory=list)
    properties: Optional[List[PropertyDefinitionInput]] = strawberry.field(default_factory=list)


@pydantic.input(model=input_models.EvidenceRequirementInput)
class EvidenceRequirementInput:
    """Evidence requirement for relation materialization."""
    key: strawberry.auto
    unit: strawberry.auto
    description: strawberry.auto


@pydantic.input(model=input_models.MaterializationConfigInput)
class MaterializationConfigInput:
    """Configuration for relation materialization from evidence."""
    backing_link_type: strawberry.auto
    desired_evidence: Optional[List[EvidenceRequirementInput]] = strawberry.field(default_factory=list)
    properties: Optional[List[PropertyDefinitionInput]] = strawberry.field(default_factory=list)


@strawberry.enum
class CardinalityEnum(str, Enum):
    """Cardinality options for relation definitions."""
    ONE_TO_ONE = "1:1"
    ONE_TO_MANY = "1:N"
    MANY_TO_MANY = "N:N"


@pydantic.input(model=input_models.RelationDefinitionInput)
class RelationDefinitionInput:
    """Definition of a relation type in the graph schema."""
    key: strawberry.auto
    ontology_references: Optional[List[OntologyReferenceInput]] = strawberry.field(default_factory=list)
    source: List[str] = strawberry.field(description="Source entity type(s)")
    target: List[str] = strawberry.field(description="Target entity type(s)")
    cardinality: CardinalityEnum = strawberry.field(default=CardinalityEnum.ONE_TO_MANY, description="Relation cardinality")
    materialization: Optional[MaterializationConfigInput] = None


@pydantic.input(model=input_models.EventRoleInput)
class EventRoleInput:
    """Role of a node in an event (input or output)."""
    key: strawberry.auto
    role: strawberry.auto
    ontology_references: Optional[List[OntologyReferenceInput]] = strawberry.field(default_factory=list)
    

@pydantic.input(model=input_models.EventDefinitionInput)
class EventDefinitionInput:
    """Definition of an event type in the graph schema."""
    key: strawberry.auto
    description: strawberry.auto
    inputs: Optional[List[EventRoleInput]] = strawberry.field(default_factory=list)
    outputs: Optional[List[EventRoleInput]] = strawberry.field(default_factory=list)
    properties: Optional[List[PropertyDefinitionInput]] = strawberry.field(default_factory=list)
    ontology_references: Optional[List[OntologyReferenceInput]] = strawberry.field(default_factory=list)
    tags: Optional[List[str]] = strawberry.field(default_factory=list)


@pydantic.input(model=input_models.PrefixInput)
class PrefixInput:
    """Prefix definition for namespacing in the graph schema."""
    prefix: strawberry.auto
    uri: strawberry.auto

@pydantic.input(model=input_models.GraphExtensionsInput)
class GraphExtensionsInput:
    """
    The graph extensions containing all type definitions.
    
    Note: Structures are no longer defined in the schema. They are
    dynamically resolved via get_label_for_identifier() from the
    IDENTIFIER_MAP in graph_engine.base_models.
    """
    prefixes: Optional[List[PrefixInput]] = strawberry.field(default_factory=list)
    entities: Optional[List[EntityDefinitionInput]] = strawberry.field(default_factory=list)
    relations: Optional[List[RelationDefinitionInput]] = strawberry.field(default_factory=list)
    events: Optional[List[EventDefinitionInput]] = strawberry.field(default_factory=list)


@pydantic.input(model=input_models.GraphDefinitionInput)
class GraphDefinitionInput:
    """Complete graph schema definition with semantic versioning."""
    system_version: strawberry.auto
    extensions: GraphExtensionsInput


# ==========================================
# SCHEMA MANAGEMENT INPUT TYPES
# ==========================================

@strawberry.input(description="Input for validating a schema definition")
class ValidateSchemaInput:
    """
    Input for validating a graph schema before creating a graph
    from it.
    
    The definition should be a GraphDefinitionModel-compatible JSON object with:
    - system_version: Semantic version string (e.g., '1.0.0')
    - extensions: Object containing structures, entities, relations, events
    """
    definition: GraphDefinitionInput = strawberry.field(description="The graph schema definition as JSON")


@strawberry.input(description="Input for setting a new schema on a graph")
class SetSchemaInput:
    """
    Input for setting a new schema version on a graph.
    
    The version must be a valid semantic version (MAJOR.MINOR.PATCH format,
    e.g., '1.0.0', '2.1.3-beta.1').
    
    The definition is a fully typed GraphDefinition with structures, entities,
    relations, and events.
    """
    graph_id: int = strawberry.field(description="ID of the graph to set the schema on")
    version: str = strawberry.field(description="Semantic version (e.g., '1.0.0'). Must follow semver format.")
    definition: GraphDefinitionInput = strawberry.field(description="The graph schema definition")
    description: Optional[str] = strawberry.field(default=None, description="Description of changes in this version")
    activate: Optional[bool] = strawberry.field(default=True, description="Whether to immediately activate this schema")


@strawberry.input(description="Input for activating an existing schema")
class ActivateSchemaInput:
    """Input for activating an existing schema version."""
    schema_id: int = strawberry.field(description="Database ID of the schema to activate")


# ==========================================
# FILTER INPUT TYPES
# ==========================================

@strawberry.input(description="Filter options for querying entities")
class EntityFilterInput:
    """Filter options for entity queries."""
    kind: Optional[str] = strawberry.field(default=None, description="Filter by entity kind/type")
    ids: Optional[List[str]] = strawberry.field(default=None, description="Filter by specific entity IDs")
    has_property: Optional[str] = strawberry.field(default=None, description="Filter entities that have a specific property")


@strawberry.input(description="Filter options for querying structures")
class StructureFilterInput:
    """Filter options for structure queries."""
    identifier: Optional[str] = strawberry.field(default=None, description="Filter by structure identifier")
    objects: Optional[List[str]] = strawberry.field(default=None, description="Filter by specific object IDs")


@strawberry.input(description="Filter options for querying measurements")
class MeasurementFilterInput:
    """Filter options for measurement queries."""
    key: Optional[str] = strawberry.field(default=None, description="Filter by measurement key")
    keys: Optional[List[str]] = strawberry.field(default=None, description="Filter by multiple measurement keys")


# ==========================================
# PAGINATION INPUT TYPES
# ==========================================

@strawberry.input(description="Pagination options")
class PaginationInput:
    """Standard offset-based pagination."""
    offset: Optional[int] = strawberry.field(default=0, description="Number of items to skip")
    limit: Optional[int] = strawberry.field(default=100, description="Maximum number of items to return")
