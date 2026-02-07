"""
GraphQL Types for the API.

These types represent the output/response types for graph entities,
structures, measurements, and related objects.

This module follows the pattern from core/types.py where:
1. Strawberry types use `strawberry.Private` to hold underlying data
2. Type matching functions convert retrieved data to appropriate subtypes
3. Fields access the private _value for their data
"""
import strawberry
from typing import Optional, List, Union
from datetime import datetime

from .scalars import AnyScalar, UnixMilliseconds, StructureIdentifier, GlobalID
from graph_engine.retrieved import RetrievedNode, RetrievedEdge, RetrievedVariable
from graph_engine import base_models
import kante
from core import models



# ===========================================
# Schema Types
# ===========================================

@kante.pydantic_type(base_models.PropertyDefinition, description="A property definition from the graph schema")
class PropertyDefinition:
    """A property definition from the graph schema."""
    key: str = strawberry.field(description="The property key/name")
    type: str = strawberry.field(description="The property type (e.g., STRING, FLOAT)")
    unit: Optional[str] = strawberry.field(default=None, description="Unit of measurement if applicable")
    description: Optional[str] = strawberry.field(default=None, description="Description of this property")




@kante.django_interface(models.EdgeCategory, description="Base interface for graph schemas")
class EdgeCategory:
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    graph_id: strawberry.ID = strawberry.field(description="ID of the graph this category belongs to")
    label: str = strawberry.field(description="Label/name of the category")
    description: Optional[str] = strawberry.field(default=None, description="Description of the category")
    purl: Optional[str] = strawberry.field(default=None, description="Persistent URL for this category")
    color: Optional[List[int]] = strawberry.field(default=None, description="Color as RGBA list (0-255)")
    tags: List[str] = strawberry.field(default_factory=list, description="List of tags associated with this category")




@kante.django_interface(models.NodeCategory, description="Base interface for graph schemas")
class NodeCategory:
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    graph_id: strawberry.ID = strawberry.field(description="ID of the graph this category belongs to")
    label: str = strawberry.field(description="Label/name of the category")
    description: Optional[str] = strawberry.field(default=None, description="Description of the category")
    purl: Optional[str] = strawberry.field(default=None, description="Persistent URL for this category")
    color: Optional[List[int]] = strawberry.field(default=None, description="Color as RGBA list (0-255)")
    tags: List[str] = strawberry.field(default_factory=list, description="List of tags associated with this category")

@kante.django_type(models.EntityCategory, description="An entity category/schema definition")
class EntityCategory(NodeCategory):
    property_definitions: List[PropertyDefinition] = strawberry.field(default_factory=list, description="List of property definitions for this entity category")

@kante.django_type(models.StructureCategory, description="A relation category/schema definition")
class StructureCategory(NodeCategory):
    pass

@kante.django_type(models.MetricCategory, description="A relation category/schema definition")
class MetricCategory(NodeCategory):
    pass

@kante.django_interface(models.NaturalEventCategory)
class EventCategory(NodeCategory):
    pass

@kante.django_type(models.NaturalEventCategory, description="A relation category/schema definition")
class ProtocolEventCategory(EventCategory):
    pass

@kante.django_type(models.NaturalEventCategory, description="A relation category/schema definition")
class NaturalEventCategory(EventCategory):
    pass


@kante.django_type(models.EdgeCategory, description="A relation category/schema definition")
class RelationCategory(EdgeCategory):
    pass



# ===========================================
# PROPERTY TYPE
# ===========================================

@strawberry.type(description="A property/variable from a node")
class Property:
    """A single property with key and value from a graph node."""
    _value: strawberry.Private[RetrievedVariable]
    
    @strawberry.field(description="The property key/name")
    def key(self) -> str:
        return self._value.key
    
    @strawberry.field(description="The property value")
    def value(self) -> AnyScalar:
        return self._value.value


@strawberry.type(description="A rich property with metadata from schema and graph")
class RichProperty:
    _entity: strawberry.Private[RetrievedNode]
    _key: strawberry.Private[str]
    
    @strawberry.field(description="Local AGE graph ID")
    def graph_id(self) -> int:
        return self._entity.graph_id
    
    @strawberry.field(description="The property key/name")
    async def definition(self) -> Optional[PropertyDefinition]:
        """Fetch the property definition from the schema based on the key."""
        # In a real implementation, we would look up the entity's category,
        # then find the property definition matching this key.
        # For this example, we'll return None for simplicity.
        return None
    
    
    @strawberry.field(description="The property value")
    async def value(self) -> AnyScalar:
        """Return the value of the property."""
        # In a real implementation, we would fetch the value from the entity's properties.
        # For this example, we'll return None for simplicity.
        return None
    
    @strawberry.field(description="Supporting evidence for this property, in form of metrics derived from observations/measurements")
    async def supporting_evidence(self) -> List["Metric"]:
        """Return the supporting evidence structures that contributed to this property."""
        # In a real implementation, we would query the graph for the structures
        # that have measurements linked to this entity and property key.
        # For this example, we'll return None for simplicity.
        return None
# ===========================================
# BASE NODE INTERFACE
# ===========================================

@strawberry.interface(description="Base interface for all graph nodes")
class Node:
    """
    Base interface that all graph nodes implement.
    Uses strawberry.Private to hold the underlying RetrievedNode data.
    """
    _value: strawberry.Private[RetrievedNode]
    
    def __hash__(self):
        return hash(self._value)
    
    @strawberry.field(description="Local AGE graph ID")
    def graph_id(self) -> int:
        return self._value.id
    
    @strawberry.field(description="Global identifier in format 'graph_name:graph_id'")
    def global_id(self) -> GlobalID:
        return self._value.global_id
    
    @strawberry.field(description="The AGE graph label")
    def label(self) -> str:
        return self._value.label
    
    @strawberry.field(description="Composite ID for node lookup")
    def id(self) -> str:
        return self._value.unique_id
    
    
    @strawberry.field(description="External ID if set")
    def external_id(self) -> Optional[str]:
        return self._value.external_id
    
    @strawberry.field(description="Local ID if set")
    def local_id(self) -> Optional[str]:
        return self._value.local_id
    
    @strawberry.field(description="Tags associated with this node")
    def tags(self) -> List[str]:
        return self._value.tags


# ===========================================
# VERSIONED NODE INTERFACE
# ===========================================

@strawberry.interface(description="Interface for versioned nodes with schema tracking")
class VersionedNode(Node):
    """Interface for nodes that track schema version and derivation time."""
    _value: strawberry.Private[RetrievedNode]
    
    @strawberry.field(description="Schema version used to derive properties")
    def schema_version(self) -> str:
        return self._value.schema_version
    
    @strawberry.field(description="Timestamp when properties were last derived (unix ms)")
    def last_derived(self) -> Optional[UnixMilliseconds]:
        return self._value.last_derived


# ===========================================
# ENTITY TYPE
# ===========================================

@strawberry.type(description="An entity in the knowledge graph with derived properties")
class Entity(VersionedNode):
    """
    An entity represents a domain object (e.g. AIS, Cell, Soma) with properties
    derived from supporting evidence structures.
    """
    _value: strawberry.Private[RetrievedNode]
    
    @strawberry.field(description="The entity type/kind (e.g. 'AIS', 'Cell')")
    def kind(self) -> str:
        return self._value.kind or self._value.label
    
    @strawberry.field(description="Category ID linking to EntityCategory model")
    def category_id(self) -> Optional[str]:
        return self._value.category_id
    
    @strawberry.field(description="When this entity became valid")
    def valid_from(self) -> Optional[datetime]:
        return self._value.valid_from
    
    @strawberry.field(description="When this entity stopped being valid")
    def valid_to(self) -> Optional[datetime]:
        return self._value.valid_to
    
    
    @strawberry.field(description="List of properties derived for this entity")
    def rich_properties(self) -> List[RichProperty]:
        """Combine raw properties with schema definitions for a rich view."""
        # In a real implementation, we would fetch the schema definitions
        # for this entity's category and merge them with the raw properties.
        # For this example, we'll just return the raw properties as RichProperties.
        return [RichProperty(_value, ) for var in self._value.cleaned_properties]
    
    
    @strawberry.field(description="List of the current derived properties for this entity")
    def properties(self) -> AnyScalar:
        """Return the structures that provide evidence for this entity."""
        # In a real implementation, we would fetch the linked structures
        # from the graph and return them as Structure types.
        # For this example, we'll return an empty list.
        return self._value.cleaned_properties


# ===========================================
# STRUCTURE TYPE
# ===========================================

@strawberry.type(description="A structure that provides evidence for entities")
class Structure(Node):
    """
    A structure represents an evidence source (e.g. ROI, Image) that
    can have measurements attached and inform entities.
    """
    _value: strawberry.Private[RetrievedNode]
    
    @strawberry.field(description="Schema identifier (e.g. '@mikro/roi')")
    def identifier(self) -> StructureIdentifier:
        return self._value.identifier or ""
    
    @strawberry.field(description="External object ID this structure references")
    def object(self) -> str:
        return self._value.object or ""
    
    @strawberry.field(description="Category ID linking to StructureCategory model")
    def category_id(self) -> Optional[str]:
        return self._value.category_id


# ===========================================
# NATURAL EVENT TYPE
# ===========================================

@strawberry.type(description="A natural event in the knowledge graph")
class NaturalEvent(VersionedNode):
    """
    A natural event represents a biological/natural occurrence (e.g. Mitosis)
    with properties derived from supporting evidence.
    """
    _value: strawberry.Private[RetrievedNode]
    
    @strawberry.field(description="The event type/kind")
    def kind(self) -> str:
        return self._value.kind or self._value.label
    
    @strawberry.field(description="Category ID linking to NaturalEventCategory model")
    def category_id(self) -> Optional[str]:
        return self._value.category_id


# ===========================================
# METRIC TYPE
# ===========================================

@strawberry.type(description="A metric node representing computed values")
class Metric(Node):
    """
    A metric represents a computed or aggregated value in the graph.
    """
    _value: strawberry.Private[RetrievedMetric]
    
    @strawberry.field(description="Category ID linking to MetricCategory model")
    def category_id(self) -> Optional[str]:
        return self._value.category_id
    
    @strawberry.field(description="The metric value")
    def value(self) -> AnyScalar:
        return self._value.value


# ===========================================
# REAGENT TYPE
# ===========================================

@strawberry.type(description="A reagent node in the graph")
class Reagent(Node):
    """
    A reagent represents a chemical or biological agent used in experiments.
    """
    _value: strawberry.Private[RetrievedNode]
    
    @strawberry.field(description="Category ID linking to ReagentCategory model")
    def category_id(self) -> Optional[str]:
        return self._value.category_id


# ===========================================
# PROTOCOL EVENT TYPE
# ===========================================

@strawberry.type(description="A protocol event in the graph")
class ProtocolEvent(VersionedNode):
    """
    A protocol event represents a step in an experimental protocol.
    """
    _value: strawberry.Private[RetrievedNode]
    
    @strawberry.field(description="The event type/kind")
    def kind(self) -> str:
        return self._value.kind or self._value.label
    
    @strawberry.field(description="Category ID linking to ProtocolEventCategory model")
    def category_id(self) -> Optional[str]:
        return self._value.category_id


# ===========================================
# BASE EDGE INTERFACE
# ===========================================

@strawberry.interface(description="Base interface for all graph edges")
class Edge:
    """
    Base interface that all graph edges implement.
    Uses strawberry.Private to hold the underlying RetrievedEdge data.
    """
    _value: strawberry.Private[RetrievedEdge]
    
    def __hash__(self):
        return hash(self._value)
    
    @strawberry.field(description="Local AGE graph ID")
    def graph_id(self) -> int:
        return self._value.id
    
    @strawberry.field(description="Global identifier in format 'graph_name:graph_id'")
    def global_id(self) -> GlobalID:
        return self._value.global_id
    
    @strawberry.field(description="Composite ID for edge lookup")
    def id(self) -> str:
        return self._value.unique_id
    
    @strawberry.field(description="The edge label/type")
    def label(self) -> str:
        return self._value.label
    
    @strawberry.field(description="Global ID of the source/left node")
    def left_id(self) -> str:
        return self._value.unique_left_id
    
    @strawberry.field(description="Global ID of the target/right node")
    def right_id(self) -> str:
        return self._value.unique_right_id


# ===========================================
# MEASUREMENT TYPE
# ===========================================

@strawberry.type(description="A measurement attached to a structure")
class Measurement(Edge):
    """
    A measurement represents a data point from a structure to an entity,
    which contributes to entity property derivation.
    """
    _value: strawberry.Private[RetrievedEdge]
    
    @strawberry.field(description="The measurement key/property name")
    def key(self) -> str:
        return self._value.key or ""
    
    @strawberry.field(description="The measurement value")
    def value(self) -> AnyScalar:
        return self._value.value
    
    @strawberry.field(description="Unit of measurement")
    def unit(self) -> Optional[str]:
        return self._value.unit
    
    @strawberry.field(description="Confidence score (0-1)")
    def confidence(self) -> Optional[float]:
        return self._value.confidence
    
    @strawberry.field(description="Type of confidence measure")
    def confidence_type(self) -> Optional[str]:
        return self._value.confidence_type
    
    @strawberry.field(description="Measurement timestamp (unix ms)")
    def timestamp(self) -> Optional[UnixMilliseconds]:
        return self._value.timestamp
    
    @strawberry.field(description="When this measurement became valid")
    def valid_from(self) -> Optional[datetime]:
        return self._value.valid_from
    
    @strawberry.field(description="When this measurement stopped being valid")
    def valid_to(self) -> Optional[datetime]:
        return self._value.valid_to
    
    @strawberry.field(description="Category ID linking to MeasurementCategory model")
    def category_id(self) -> Optional[str]:
        return self._value.category_id


# ===========================================
# ASSERTION TYPE (Provenance)
# ===========================================

@strawberry.type(description="An assertion representing provenance information")
class Assertion(Edge):
    """
    An assertion records who made what claims about the graph and when.
    It links to the measurements it asserted.
    """
    _value: strawberry.Private[RetrievedEdge]
    
    @strawberry.field(description="User/subject who made the assertion")
    def subject(self) -> Optional[str]:
        return self._value.subject
    
    @strawberry.field(description="Application that made the assertion")
    def app_id(self) -> Optional[str]:
        return self._value.app_id
    
    @strawberry.field(description="Action identifier")
    def action_id(self) -> Optional[str]:
        return self._value.action_id
    
    @strawberry.field(description="Human-readable action name")
    def action_name(self) -> Optional[str]:
        return self._value.action_name
    
    @strawberry.field(description="Action arguments as JSON")
    def action_args(self) -> Optional[AnyScalar]:
        return self._value.action_args
    
    @strawberry.field(description="When this assertion was created")
    def created_at(self) -> Optional[datetime]:
        return self._value.created_at


# ===========================================
# RELATION TYPE
# ===========================================

@strawberry.type(description="A relation edge between two entities")
class Relation(Edge):
    """
    A relation is an edge between two entities that establishes a
    non-measurement relationship (e.g., parent-child, part-of).
    """
    _value: strawberry.Private[RetrievedEdge]
    
    @strawberry.field(description="When this relation became valid")
    def valid_from(self) -> Optional[datetime]:
        return self._value.valid_from
    
    @strawberry.field(description="When this relation stopped being valid")
    def valid_to(self) -> Optional[datetime]:
        return self._value.valid_to
    
    @strawberry.field(description="When this relation was created")
    def created_at(self) -> Optional[datetime]:
        return self._value.created_at
    
    @strawberry.field(description="Category ID linking to RelationCategory model")
    def category_id(self) -> Optional[str]:
        return self._value.category_id


# ===========================================
# STRUCTURE RELATION TYPE
# ===========================================

@strawberry.type(description="A relation edge between two structures")
class StructureRelation(Edge):
    """
    A structure relation connects two structures (e.g., containment, adjacency).
    """
    _value: strawberry.Private[RetrievedEdge]
    
    @strawberry.field(description="When this relation was created")
    def created_at(self) -> Optional[datetime]:
        return self._value.created_at
    
    @strawberry.field(description="Category ID linking to StructureRelationCategory model")
    def category_id(self) -> Optional[str]:
        return self._value.category_id


# ===========================================
# TYPE MATCHING FUNCTIONS
# ===========================================

# Union type for all node subtypes
NodeSubtype = Union[Entity, Structure, NaturalEvent, Metric, Reagent, ProtocolEvent]

# Union type for all edge subtypes
EdgeSubtype = Union[Measurement, Assertion, Relation, StructureRelation]


def node_to_subtype(node: RetrievedNode) -> NodeSubtype:
    """
    Convert a RetrievedNode to the appropriate Strawberry type based on its node_type.
    
    This matches the pattern from core/types.py's entity_to_node_subtype function.
    
    Args:
        node: The retrieved node from AGE
        
    Returns:
        The appropriate Strawberry type instance (Entity, Structure, etc.)
        
    Raises:
        ValueError: If the node type is unknown
    """
    match node.node_type:
        case "ENTITY":
            return Entity(_value=node)
        case "STRUCTURE":
            return Structure(_value=node)
        case "NATURAL_EVENT":
            return NaturalEvent(_value=node)
        case "METRIC":
            return Metric(_value=node)
        case "REAGENT":
            return Reagent(_value=node)
        case "PROTOCOL_EVENT":
            return ProtocolEvent(_value=node)
        case None:
            # Default based on label if type property not set
            label = node.label.upper()
            if label == "ENTITY":
                return Entity(_value=node)
            elif label == "STRUCTURE":
                return Structure(_value=node)
            else:
                # Default to Entity for unknown types
                return Entity(_value=node)
        case _:
            raise ValueError(f"Unknown node type: {node.node_type}")


def edge_to_subtype(edge: RetrievedEdge) -> EdgeSubtype:
    """
    Convert a RetrievedEdge to the appropriate Strawberry type based on its edge_type.
    
    This matches the pattern from core/types.py's relation_to_edge_subtype function.
    
    Args:
        edge: The retrieved edge from AGE
        
    Returns:
        The appropriate Strawberry type instance (Measurement, Assertion, etc.)
        
    Raises:
        ValueError: If the edge type is unknown
    """
    match edge.edge_type:
        case "MEASUREMENT":
            return Measurement(_value=edge)
        case "ASSERTION":
            return Assertion(_value=edge)
        case "RELATION":
            return Relation(_value=edge)
        case "STRUCTURE_RELATION":
            return StructureRelation(_value=edge)
        case None:
            # Default based on label if type property not set
            label = edge.label.upper()
            if "MEASURE" in label:
                return Measurement(_value=edge)
            elif "ASSERT" in label:
                return Assertion(_value=edge)
            else:
                return Relation(_value=edge)
        case _:
            raise ValueError(f"Unknown edge type: {edge.edge_type}")


# ===========================================
# RESULT TYPES
# ===========================================

@strawberry.type(description="Result of creating an entity")
class EntityCreationResult:
    """Result returned after successfully creating an entity."""
    ref_id: str = strawberry.field(description="The reference ID (external UUID)")
    db_id: str = strawberry.field(description="The database ID")
    graph_id: str = strawberry.field(description="The AGE graph ID (as string for 64-bit support)")
    status: str = strawberry.field(default="CREATED", description="Creation status")
    
    entity: Optional[Entity] = strawberry.field(default=None, description="The created entity")


@strawberry.type(description="Result of creating a relation")
class RelationCreationResult:
    """Result returned after successfully creating a relation between entities."""
    ref_id: str = strawberry.field(description="The reference ID (external UUID)")
    db_id: str = strawberry.field(description="The database ID (source->target)")
    graph_id: str = strawberry.field(description="The AGE graph ID of the edge (as string for 64-bit support)")
    status: str = strawberry.field(default="CREATED", description="Creation status")
    
    relation: Optional[Relation] = strawberry.field(default=None, description="The created relation edge")


@strawberry.type(description="Result of linking a structure to an entity")
class LinkStructureResult:
    """Result returned after linking a structure to an entity."""
    success: bool = strawberry.field(description="Whether the link was successful")
    entity: Entity = strawberry.field(description="The updated entity with recalculated properties")
    structure: Structure = strawberry.field(description="The linked structure")


# ===========================================
# SCHEMA TYPES
# ===========================================

@strawberry.type(description="A validation error from schema validation")
class SchemaValidationError:
    """A single validation error."""
    location: List[str] = strawberry.field(description="Path to the error (e.g., ['extensions', 'entities', 'Neuron'])")
    message: str = strawberry.field(description="Human-readable error message")
    type: str = strawberry.field(default="validation_error", description="Error type")


@strawberry.type(description="Result of validating a schema")
class SchemaValidationResult:
    """Result of schema validation."""
    is_valid: bool = strawberry.field(description="Whether the schema is valid")
    errors: List[SchemaValidationError] = strawberry.field(description="List of validation errors")
    warnings: List[SchemaValidationError] = strawberry.field(description="List of warnings (non-fatal)")


@strawberry.type(description="A graph schema version")
class GraphSchemaType:
    """A versioned schema for a graph."""
    id: int = strawberry.field(description="Database ID of this schema")
    version: str = strawberry.field(description="Semantic version (e.g., '1.0.0')")
    index: int = strawberry.field(description="Sequential index of this version")
    is_active: bool = strawberry.field(description="Whether this is the active schema")
    created_at: datetime = strawberry.field(description="When this schema was created")
    description: Optional[str] = strawberry.field(default=None, description="Description of this version")
    definition: AnyScalar = strawberry.field(description="The full schema definition as JSON")


@strawberry.type(description="Result of setting a new schema")
class SetSchemaResult:
    """Result of setting a new schema version."""
    schema: GraphSchemaType = strawberry.field(description="The created schema")
    activated: bool = strawberry.field(description="Whether the schema was activated")
    migration_required: bool = strawberry.field(
        default=False, 
        description="Whether existing nodes may need migration"
    )


# ===========================================
# CONNECTION TYPES (for pagination)
# ===========================================

@strawberry.type(description="Pagination info for connections")
class PageInfo:
    """Pagination metadata."""
    has_next_page: bool = strawberry.field(description="Whether there are more items")
    has_previous_page: bool = strawberry.field(description="Whether there are previous items")
    total_count: int = strawberry.field(description="Total number of items")
    offset: int = strawberry.field(default=0, description="Current offset")
    limit: int = strawberry.field(default=100, description="Current limit")


@strawberry.type(description="A paginated list of entities")
class EntityConnection:
    """Paginated entity results."""
    items: List[Entity] = strawberry.field(description="List of entities")
    page_info: PageInfo = strawberry.field(description="Pagination info")


@strawberry.type(description="A paginated list of structures")
class StructureConnection:
    """Paginated structure results."""
    items: List[Structure] = strawberry.field(description="List of structures")
    page_info: PageInfo = strawberry.field(description="Pagination info")


@strawberry.type(description="A paginated list of measurements")
class MeasurementConnection:
    """Paginated measurement results."""
    items: List[Measurement] = strawberry.field(description="List of measurements")
    page_info: PageInfo = strawberry.field(description="Pagination info")


@strawberry.type(description="A paginated list of nodes (mixed types)")
class NodeConnection:
    """Paginated node results of mixed types."""
    items: List[NodeSubtype] = strawberry.field(description="List of nodes")
    page_info: PageInfo = strawberry.field(description="Pagination info")


@strawberry.type(description="A paginated list of edges (mixed types)")
class EdgeConnection:
    """Paginated edge results of mixed types."""
    items: List[EdgeSubtype] = strawberry.field(description="List of edges")
    page_info: PageInfo = strawberry.field(description="Pagination info")


# ===========================================
# CONVERTERS (from Pydantic to Strawberry via Retrieved)
# ===========================================

def entity_from_response(response) -> Entity:
    """
    Convert EntityResponse Pydantic model or RetrievedEntity to Strawberry Entity type.
    Creates a RetrievedNode as the intermediary.
    """
    from graph_engine.output_models import EntityResponse
    from graph_engine.retrieved import RetrievedEntity
    
    if isinstance(response, RetrievedEntity):
        # RetrievedEntity is already a RetrievedNode subclass, use it directly
        return Entity(_value=response)
    
    if isinstance(response, EntityResponse):
        # Build properties dict from response
        props = {
            "type": "ENTITY",
            "kind": response.kind,
            "external_id": response.id,
            "schema_version": response.schema_version,
            "last_derived": response.last_derived,
            **response.properties,
        }
        
        # Parse global_id to get graph_name and graph_id
        parts = response.global_id.split(":")
        graph_name = parts[0] if len(parts) > 1 else "default"
        
        node = RetrievedNode(
            graph_name=graph_name,
            id=response.graph_id,
            label=response.label,
            properties=props,
        )
        
        return Entity(_value=node)
    
    raise TypeError(f"Expected EntityResponse or RetrievedEntity, got {type(response)}")


def structure_from_response(response) -> Structure:
    """
    Convert StructureResponse Pydantic model to Strawberry Structure type.
    Creates a RetrievedNode as the intermediary.
    """
    from graph_engine.output_models import StructureResponse
    if not isinstance(response, StructureResponse):
        raise TypeError(f"Expected StructureResponse, got {type(response)}")
    
    props = {
        "type": "STRUCTURE",
        "identifier": response.identifier,
        "object": response.object,
    }
    
    parts = response.global_id.split(":")
    graph_name = parts[0] if len(parts) > 1 else "default"
    
    node = RetrievedNode(
        graph_name=graph_name,
        id=response.graph_id,
        label=response.label,
        properties=props,
    )
    
    return Structure(_value=node)


def measurement_from_response(response) -> Measurement:
    """
    Convert MeasurementResponse Pydantic model to Strawberry Measurement type.
    Creates a RetrievedEdge as the intermediary.
    """
    from graph_engine.output_models import MeasurementResponse
    if not isinstance(response, MeasurementResponse):
        raise TypeError(f"Expected MeasurementResponse, got {type(response)}")
    
    props = {
        "type": "MEASUREMENT",
        "key": response.key,
        "value": response.value,
        "unit": response.unit,
        "confidence": response.confidence,
        "confidence_type": response.confidence_type,
        "timestamp": response.timestamp,
    }
    
    parts = response.global_id.split(":")
    graph_name = parts[0] if len(parts) > 1 else "default"
    
    edge = RetrievedEdge(
        graph_name=graph_name,
        id=response.graph_id,
        label=response.label,
        left_id=0,  # Not available from response
        right_id=0,  # Not available from response
        properties=props,
    )
    
    return Measurement(_value=edge)


def assertion_from_response(response) -> Assertion:
    """
    Convert AssertionResponse Pydantic model to Strawberry Assertion type.
    Creates a RetrievedEdge as the intermediary.
    """
    from graph_engine.output_models import AssertionResponse
    if not isinstance(response, AssertionResponse):
        raise TypeError(f"Expected AssertionResponse, got {type(response)}")
    
    props = {
        "type": "ASSERTION",
        "subject": response.subject,
        "app_id": response.app_id,
        "action_id": response.action_id,
        "action_name": response.action_name,
        "action_args": response.action_args,
    }
    
    parts = response.global_id.split(":")
    graph_name = parts[0] if len(parts) > 1 else "default"
    
    edge = RetrievedEdge(
        graph_name=graph_name,
        id=response.graph_id,
        label=response.label,
        left_id=0,
        right_id=0,
        properties=props,
    )
    
    return Assertion(_value=edge)
