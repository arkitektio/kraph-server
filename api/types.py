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
from api import loaders, order
from .scalars import AnyScalar, UnixMilliseconds, StructureIdentifier, GlobalID
from graph_engine.retrieved import RetrievedMetric, RetrievedNode, RetrievedEdge, RetrievedVariable
from graph_engine import base_models
import kante
from core import models
from graph_engine import retrieved
from api import filters


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


@kante.django_interface(models.Graph, description="Base interface for graph schemas")
class Graph:
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    graph_id: strawberry.ID = strawberry.field(description="ID of the graph this category belongs to")
    label: str = strawberry.field(description="Label/name of the category")
    description: Optional[str] = strawberry.field(default=None, description="Description of the category")
    purl: Optional[str] = strawberry.field(default=None, description="Persistent URL for this category")
    color: Optional[List[int]] = strawberry.field(default=None, description="Color as RGBA list (0-255)")
    tags: List[str] = strawberry.field(default_factory=list, description="List of tags associated with this category")


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


@kante.django_type(models.EntityCategory, filters=filters.EntityCategoryFilter, pagination=True, ordering=order.EntityCategoryOrder, description="An entity category/schema definition")
class EntityCategory(NodeCategory):
    property_definitions: List[PropertyDefinition] = strawberry.field(default_factory=list, description="List of property definitions for this entity category")


@kante.django_type(models.StructureCategory, filters=filters.StructureCategoryFilter, pagination=True, ordering=order.StructureCategoryOrder, description="A structure category/schema definition")
class StructureCategory(NodeCategory):
    pass


@kante.django_type(models.MetricCategory, filters=filters.MetricCategoryFilter, pagination=True, ordering=order.MetricCategoryOrder, description="A metric category/schema definition")
class MetricCategory(NodeCategory):
    pass


@kante.django_interface(models.NaturalEventCategory, description="Base interface for event categories/schemas")
class EventCategory(NodeCategory):
    pass


@kante.django_type(models.ProtocolEventCategory, filters=filters.ProtocolEventCategoryFilter, pagination=True, ordering=order.ProtocolEventCategoryOrder, description="A relation category/schema definition")
class ProtocolEventCategory(EventCategory):
    """A protocol event category/schema definition, which is a subtype of EventCategory."""

    pass


@kante.django_type(models.NaturalEventCategory, filters=filters.NaturalEventCategoryFilter, pagination=True, ordering=order.NaturalEventCategoryOrder, description="A relation category/schema definition")
class NaturalEventCategory(EventCategory):
    """A natural event category/schema definition, which is a subtype of EventCategory."""

    pass


@kante.django_type(models.RelationCategory, filters=filters.RelationCategoryFilter, pagination=True, ordering=order.RelationCategoryOrder, description="A relation category/schema definition")
class RelationCategory(EdgeCategory):
    """A relation category/schema definition, which defines the type of a relation edge between entities. It can also include property definitions for the relation."""

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
    _category: strawberry.Private[EntityCategory]

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
        return []


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
    async def rich_properties(self) -> List[RichProperty]:
        """Combine raw properties with schema definitions for a rich view."""
        # Category lookup and schema merging logic would go here in a real implementation.
        assert self._value.category_id is not None, "Entity must have a category_id to fetch property definitions"
        category = await loaders.entity_category_loader.load([self._value.category_id])

        return [RichProperty(_node=self, _key=var, _category=category) for var in self._value.cleaned_properties]

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
# ASSERTION TYPE (Provenance)
# ===========================================


@strawberry.type(description="An assertion representing provenance information")
class Assertion(Node):
    """
    An assertion records who made what claims about the graph and when.
    It links to the measurements it asserted.
    """

    _value: strawberry.Private[RetrievedNode]

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

    @strawberry.field(description="List of properties derived for this entity")
    def rich_properties(self) -> List[RichProperty]:
        """Combine raw properties with schema definitions for a rich view."""
        # In a real implementation, we would fetch the schema definitions
        # for this entity's category and merge them with the raw properties.
        # For this example, we'll just return the raw properties as RichProperties.
        return [
            RichProperty(
                _value,
            )
            for var in self._value.cleaned_properties
        ]

    @strawberry.field(description="List of the current derived properties for this entity")
    def properties(self) -> AnyScalar:
        """Return the structures that provide evidence for this entity."""
        # In a real implementation, we would fetch the linked structures
        # from the graph and return them as Structure types.
        # For this example, we'll return an empty list.
        return self._value.cleaned_properties


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


@kante.type(description="A natural event category/schema definition")
class Describes(Edge):
    pass


@kante.type(description="A natural event category/schema definition")
class Informs(Edge):
    pass


@kante.type(description="A natural event category/schema definition")
class Asserted(Edge):
    pass


@kante.type(description="A natural event category/schema definition")
class Generated(Edge):
    pass


@kante.type(description="A relation edge between two structures")
class ReifiesAsSource(Edge):
    pass


@kante.type(description="A relation edge between two structures")
class ReifiesAsTarget(Edge):
    pass


# ===========================================
# TYPE MATCHING FUNCTIONS
# ===========================================

# Union type for all node subtypes
NodeSubtype = Union[Entity, Structure, NaturalEvent, Metric, Reagent, ProtocolEvent]

# Union type for all edge subtypes
EdgeSubtype = Union[Assertion, Relation, StructureRelation, Describes, Informs, Asserted, Generated, ReifiesAsSource, ReifiesAsTarget]


def cast_node_to_graphql_type(node: RetrievedNode) -> NodeSubtype:
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


def cast_edge_to_graphql_type(edge: RetrievedEdge) -> EdgeSubtype:
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
            return Metric(_value=edge)
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
@strawberry.type(description="Result of linking a structure to an entity")
class GraphNodesRender:
    _value: strawberry.Private[retrieved.RetrievedGraphNodesRender]
    pass


@strawberry.type(description="Result of linking a structure to an entity")
class GraphPathRender:
    _value: strawberry.Private[retrieved.RetrievedGraphPathRender]
    pass


@strawberry.type(description="Result of linking a structure to an entity")
class GraphPairsRender:
    _value: strawberry.Private[retrieved.RetrievedGraphPairsRender]
    pass


@strawberry.type(description="Result of linking a structure to an entity")
class GraphTableRender:
    _value: strawberry.Private[retrieved.RetrievedGraphTableRender]
    pass


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
    migration_required: bool = strawberry.field(default=False, description="Whether existing nodes may need migration")
