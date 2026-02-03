"""
GraphQL Types for the API.

These types represent the output/response types for graph entities,
structures, measurements, and related objects.
"""
import strawberry
from typing import Optional, List, Any
from .scalars import AnyScalar, UnixMilliseconds, StructureIdentifier, GlobalID


# ===========================================
# CORE NODE TYPES
# ===========================================

@strawberry.type(description="A rich property with metadata from schema and graph")
class RichProperty:
    """Detailed view of a property combining database value with schema definition."""
    key: str = strawberry.field(description="The property key/name")
    value: AnyScalar = strawberry.field(description="The property value")
    unit: Optional[str] = strawberry.field(default=None, description="Unit from schema definition")
    description: Optional[str] = strawberry.field(default=None, description="Description from schema")
    derivation_mode: str = strawberry.field(default="MANUAL", description="How this property is derived (MANUAL, ROLLUP, LATEST)")
    confidence: Optional[float] = strawberry.field(default=None, description="Confidence score if available")
    last_updated: Optional[UnixMilliseconds] = strawberry.field(default=None, description="Last update timestamp")


@strawberry.interface(description="Base interface for all graph nodes")
class Node:
    """Base interface that all graph nodes implement."""
    graph_id: int = strawberry.field(description="Local AGE graph ID")
    global_id: GlobalID = strawberry.field(description="Global identifier in format 'graph_name:graph_id'")
    label: str = strawberry.field(description="The AGE graph label")


@strawberry.interface(description="Interface for versioned nodes with schema tracking")
class Versioned:
    """Interface for nodes that track schema version and derivation time."""
    schema_version: str = strawberry.field(description="Schema version used to derive properties")
    last_derived: UnixMilliseconds = strawberry.field(description="Timestamp when properties were last derived")


# ===========================================
# ENTITY TYPE
# ===========================================

@strawberry.type(description="An entity in the knowledge graph with derived properties")
class Entity(Versioned, Node):
    """
    An entity represents a domain object (e.g. AIS, Cell, Soma) with properties
    derived from supporting evidence structures.
    """
    graph_id: int = strawberry.field(description="Local AGE graph ID")
    global_id: GlobalID = strawberry.field(description="Global identifier in format 'graph_name:graph_id'")
    label: str = strawberry.field(description="The AGE graph label (entity kind)")
    schema_version: str = strawberry.field(description="Schema version used to derive properties")
    last_derived: UnixMilliseconds = strawberry.field(description="Timestamp when properties were last derived")
    
    id: str = strawberry.field(description="User-facing UUID for this entity")
    kind: str = strawberry.field(description="The entity type/kind (e.g. 'AIS', 'Cell')")
    
    # Properties access
    properties: AnyScalar = strawberry.field(description="Dictionary of all derived properties")
    rich_properties: List[RichProperty] = strawberry.field(
        default_factory=list,
        description="List of properties with full metadata"
    )
    
    @strawberry.field(description="Get a specific property by key")
    def property(self, key: str) -> Optional[AnyScalar]:
        """Get a specific property value by key."""
        if isinstance(self.properties, dict):
            return self.properties.get(key)
        return None
    
    @strawberry.field(description="Get a rich property by key")
    def rich_property(self, key: str) -> Optional[RichProperty]:
        """Get a specific rich property by key."""
        for rp in self.rich_properties:
            if rp.key == key:
                return rp
        return None


@strawberry.type(description="A natural event in the knowledge graph")
class NaturalEvent:
    """
    A natural event represents a biological/natural occurrence (e.g. Mitosis)
    with properties derived from supporting evidence.
    """
    graph_id: int = strawberry.field(description="Local AGE graph ID")
    global_id: GlobalID = strawberry.field(description="Global identifier")
    label: str = strawberry.field(description="The AGE graph label")
    schema_version: str = strawberry.field(description="Schema version")
    last_derived: UnixMilliseconds = strawberry.field(description="Last derivation timestamp")
    
    id: str = strawberry.field(description="User-facing UUID")
    kind: str = strawberry.field(description="The event type")
    properties: AnyScalar = strawberry.field(description="Derived properties")
    rich_properties: List[RichProperty] = strawberry.field(default_factory=list)


# ===========================================
# STRUCTURE TYPE
# ===========================================

@strawberry.type(description="A structure that provides evidence for entities")
class Structure:
    """
    A structure represents an evidence source (e.g. ROI, Image) that
    can have measurements attached and inform entities.
    """
    graph_id: int = strawberry.field(description="Local AGE graph ID")
    global_id: GlobalID = strawberry.field(description="Global identifier")
    label: str = strawberry.field(description="The AGE graph label (e.g. 'ROI', 'ToldYouSo')")
    
    identifier: StructureIdentifier = strawberry.field(description="Schema identifier (e.g. '@mikro/roi')")
    object: str = strawberry.field(description="External object ID this structure references")


# ===========================================
# MEASUREMENT TYPE
# ===========================================

@strawberry.type(description="A measurement attached to a structure")
class Measurement:
    """
    A measurement represents a data point attached to a structure,
    which contributes to entity property derivation.
    """
    graph_id: int = strawberry.field(description="Local AGE graph ID")
    global_id: GlobalID = strawberry.field(description="Global identifier")
    label: str = strawberry.field(description="The AGE graph label ('Measurement')")
    
    key: str = strawberry.field(description="The measurement key/property name")
    value: AnyScalar = strawberry.field(description="The measurement value")
    unit: Optional[str] = strawberry.field(default=None, description="Unit of measurement")
    confidence: Optional[float] = strawberry.field(default=None, description="Confidence score (0-1)")
    confidence_type: Optional[str] = strawberry.field(default=None, description="Type of confidence")
    timestamp: Optional[UnixMilliseconds] = strawberry.field(default=None, description="Measurement timestamp")


# ===========================================
# ASSERTION TYPE (Provenance)
# ===========================================

@strawberry.type(description="An assertion representing provenance information")
class Assertion:
    """
    An assertion records who made what claims about the graph and when.
    It links to the measurements it asserted.
    """
    graph_id: int = strawberry.field(description="Local AGE graph ID")
    global_id: GlobalID = strawberry.field(description="Global identifier")
    label: str = strawberry.field(description="The AGE graph label ('Assertion')")
    
    subject: Optional[str] = strawberry.field(default=None, description="User/subject who made the assertion")
    app_id: Optional[str] = strawberry.field(default=None, description="Application that made the assertion")
    action_id: Optional[str] = strawberry.field(default=None, description="Action identifier")
    action_name: Optional[str] = strawberry.field(default=None, description="Human-readable action name")
    action_args: Optional[AnyScalar] = strawberry.field(default=None, description="Action arguments as JSON")


# ===========================================
# RESULT TYPES
# ===========================================

@strawberry.type(description="Result of creating an entity")
class EntityCreationResult:
    """Result returned after successfully creating an entity."""
    ref_id: str = strawberry.field(description="The reference ID (external UUID)")
    db_id: str = strawberry.field(description="The database ID")
    graph_id: int = strawberry.field(description="The AGE graph ID")
    status: str = strawberry.field(default="CREATED", description="Creation status")
    
    entity: Optional[Entity] = strawberry.field(default=None, description="The created entity")


@strawberry.type(description="Result of linking a structure to an entity")
class LinkStructureResult:
    """Result returned after linking a structure to an entity."""
    success: bool = strawberry.field(description="Whether the link was successful")
    entity: Entity = strawberry.field(description="The updated entity with recalculated properties")
    structure: Structure = strawberry.field(description="The linked structure")


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


# ===========================================
# CONVERTERS (from Pydantic to Strawberry)
# ===========================================

def entity_from_response(response) -> Entity:
    """Convert EntityResponse Pydantic model to Strawberry Entity type."""
    from graph_engine.output_models import EntityResponse
    if not isinstance(response, EntityResponse):
        raise TypeError(f"Expected EntityResponse, got {type(response)}")
    
    rich_props = [
        RichProperty(
            key=rp.key,
            value=rp.value,
            unit=rp.unit,
            description=rp.description,
            derivation_mode=rp.derivation_mode,
            confidence=rp.confidence,
            last_updated=rp.last_updated,
        )
        for rp in response.rich_properties
    ]
    
    return Entity(
        graph_id=response.graph_id,
        global_id=response.global_id,
        label=response.label,
        schema_version=response.schema_version,
        last_derived=response.last_derived,
        id=response.id,
        kind=response.kind,
        properties=response.properties,
        rich_properties=rich_props,
    )


def structure_from_response(response) -> Structure:
    """Convert StructureResponse Pydantic model to Strawberry Structure type."""
    from graph_engine.output_models import StructureResponse
    if not isinstance(response, StructureResponse):
        raise TypeError(f"Expected StructureResponse, got {type(response)}")
    
    return Structure(
        graph_id=response.graph_id,
        global_id=response.global_id,
        label=response.label,
        identifier=response.identifier,
        object=response.object,
    )


def measurement_from_response(response) -> Measurement:
    """Convert MeasurementResponse Pydantic model to Strawberry Measurement type."""
    from graph_engine.output_models import MeasurementResponse
    if not isinstance(response, MeasurementResponse):
        raise TypeError(f"Expected MeasurementResponse, got {type(response)}")
    
    return Measurement(
        graph_id=response.graph_id,
        global_id=response.global_id,
        label=response.label,
        key=response.key,
        value=response.value,
        unit=response.unit,
        confidence=response.confidence,
        confidence_type=response.confidence_type,
        timestamp=response.timestamp,
    )


def assertion_from_response(response) -> Assertion:
    """Convert AssertionResponse Pydantic model to Strawberry Assertion type."""
    from graph_engine.output_models import AssertionResponse
    if not isinstance(response, AssertionResponse):
        raise TypeError(f"Expected AssertionResponse, got {type(response)}")
    
    return Assertion(
        graph_id=response.graph_id,
        global_id=response.global_id,
        label=response.label,
        subject=response.subject,
        app_id=response.app_id,
        action_id=response.action_id,
        action_name=response.action_name,
        action_args=response.action_args,
    )
