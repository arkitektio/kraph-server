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
from typing import Generic, Optional, List, Type, TypeVar, Union, cast
from datetime import datetime
from api import loaders, order, pagination, filters
from datalayer.types import MediaStore
from graph_engine.scalars import AnyScalar, UnixMilliseconds, StructureIdentifier, GlobalID
from graph_engine.retrieved import RetrievedMetric, RetrievedNode, RetrievedEdge, RetrievedStructure, RetrievedVariable
from graph_engine import input_models
import kante
from core import models
from graph_engine import retrieved, scalars
from api import filters
from core import enums
from stats.gen import create_stats_type


# ===========================================
# Schema Types
# ===========================================
@kante.pydantic_type(input_models.OntologyReferenceInput, description="An ontology reference in the graph schema")
class OntologyReference:
    """An ontology reference in the graph schema."""

    prefix: str = strawberry.field(description="The ontology prefix (e.g., 'GO', 'CL')")
    term_id: str = strawberry.field(description="The ontology term ID (e.g., '0008150')")


@kante.pydantic_type(input_models.DerivationRuleInput, all_fields=True, description="A derivation rule in the graph schema")
class DerivationRule:
    """A derivation rule in the graph schema, which defines how to derive new entities or relations based on existing ones."""


@kante.pydantic_type(input_models.PropertyDefinitionInput, all_fields=True, description="A property definition from the graph schema")
class PropertyDefinition:
    """A property definition from the graph schema."""


@kante.pydantic_type(input_models.EntityDescriptorInput, all_fields=True, description="Input type for creating a new graph query")
class EntityDescriptor:
    """Descriptor for an entity, used as input for creating new graph queries."""

    keys: Optional[List[str]] = kante.field(default=None, description="Filter by entity key/label")
    tags: Optional[List[str]] = kante.field(default=None, description="Filter by tags on the entity")
    ontotology_terms: Optional[List[str]] = kante.field(default=None, description="Filter by ontology references on the entity (format: 'PREFIX:TERM_ID')")
    default_category_key: Optional[str] = kante.field(default=None, description="Default category to use for this entity if we aim to create a new one based on this descriptor")


@kante.pydantic_type(input_models.StructureDescriptorInput, description="Input type for creating a new graph query")
class StructureDescriptor:
    """Descriptor for a structure, used as input for creating new graph queries."""

    keys: Optional[List[str]] = kante.field(default=None, description="Filter by structure key/label")
    tags: Optional[List[str]] = kante.field(default=None, description="Filter by tags on the structure")
    ontotology_terms: Optional[List[str]] = kante.field(default=None, description="Filter by ontology references on the structure (format: 'PREFIX:TERM_ID')")
    default_category_key: Optional[str] = kante.field(default=None, description="Default category to use for this structure if we aim to create a new one based on this descriptor")


@kante.pydantic_type(input_models.ColumnInput, all_fields=True, description="Input type for defining a graph schema")
class Column:
    """A column definition for a graph schema."""


@kante.pydantic_type(input_models.WhereClauseInput, all_fields=True, description="Input type for defining a graph schema")
class WhereClause:
    """A column definition for a graph schema."""


@kante.pydantic_type(input_models.MatchPathInput, all_fields=True, description="Input type for creating a new graph")
class MatchPath:
    """A path definition for matching patterns in the graph."""


@kante.pydantic_type(input_models.ReturnStatementInput, all_fields=True, description="Input type for creating a new graph")
class ReturnStatement:
    """A return statement definition for a table query."""


@kante.pydantic_type(input_models.BuilderArgsInput, all_fields=True, description="Input type for creating a new graph query")
class BuilderArgs:
    """Arguments for building a graph query."""


@kante.pydantic_type(input_models.EventRoleInput, all_fields=True, description="Input type for defining roles in an event category")
class EventRole:
    """Definition of a role in an event category."""


@kante.django_type(models.MaterializedEdge, filters=filters.MaterializedEdgeFilter, ordering=order.MaterializedEdgeOrder, pagination=True, description="A materialized edge representing a relationship in the graph")
class MaterializedEdge:
    """A materialized edge representing a relationship in the graph."""

    id: strawberry.ID = strawberry.field(description="Database ID of the edge")
    source: "NodeCategory"
    target: "NodeCategory"
    edge: "EdgeCategory"
    graph: "Graph"


@kante.django_type(models.Graph, filters=filters.GraphFilter, pagination=True, ordering=order.GraphOrder, description="Base interface for graph schemas")
class Graph:
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    age_name: str = strawberry.field(description="The name of the graph as used in AGE (e.g. 'CellGraph')")
    graph_id: strawberry.ID = strawberry.field(description="ID of the graph this category belongs to")
    label: str = strawberry.field(description="Label/name of the category")
    description: Optional[str] = strawberry.field(default=None, description="Description of the category")
    purl: Optional[str] = strawberry.field(default=None, description="Persistent URL for this category")
    color: Optional[List[int]] = strawberry.field(default=None, description="Color as RGBA list (0-255)")
    tags: List[str] = strawberry.field(default_factory=list, description="List of tags associated with this category")
    name: str = strawberry.field(description="Name of the graph")
    materialized_edges: List["MaterializedEdge"] = strawberry.field(default_factory=list, description="List of materialized edges in the graph")
    image: MediaStore = strawberry.field(description="An image representing this graph, for visualization purposes")
    # Schemas
    node_categories: List["NodeCategory"] = strawberry.field(default_factory=list, description="List of node categories/schemas defined in this graph")
    edge_categories: List["EdgeCategory"] = strawberry.field(default_factory=list, description="List of edge categories/schemas defined in this graph")

    measurement_categories: List["MeasurementCategory"] = strawberry.field(default_factory=list, description="List of measurement categories/schemas defined in this graph")
    entity_categories: List["EntityCategory"] = strawberry.field(default_factory=list, description="List of entity categories/schemas defined in this graph")
    structure_categories: List["StructureCategory"] = strawberry.field(default_factory=list, description="List of structure categories/schemas defined in this graph")
    metric_categories: List["MetricCategory"] = strawberry.field(default_factory=list, description="List of metric categories/schemas defined in this graph")
    protocol_event_categories: List["ProtocolEventCategory"] = strawberry.field(default_factory=list, description="List of protocol event categories/schemas defined in this graph")
    natural_event_categories: List["NaturalEventCategory"] = strawberry.field(default_factory=list, description="List of natural event categories/schemas defined in this graph")
    relation_categories: List["RelationCategory"] = strawberry.field(default_factory=list, description="List of relation categories/schemas defined in this graph")
    structure_relation_categories: List["StructureRelationCategory"] = strawberry.field(default_factory=list, description="List of structure relation categories/schemas defined in this graph")

    # Queries
    queries: List["GraphQuery"] = strawberry.field(default_factory=list, description="List of graph queries defined in this graph")

    @kante.django_field(description="The graph this category belongs to")
    def pinned(self, info: kante.Info) -> bool:
        """Whether this category is pinned for quick access in the UI."""
        # In a real implementation, we would check the user's preferences or a pinned categories list.
        # For this example, we'll return False for simplicity.
        return cast(models.Graph, self).pinned_by.filter(id=info.context.user.id).exists()


@kante.django_type(models.CategoryTag, filters=filters.CategoryTagFilter, pagination=True, ordering=order.CategoryTagOrder, description="Base interface for graph nodes representing entities")
class CategoryTag:
    id: strawberry.ID = strawberry.field(description="Database ID of the category tag")
    name: str = strawberry.field(description="Name of the category tag")
    description: Optional[str] = strawberry.field(default=None, description="Description of the category tag")


@kante.django_interface(models.Category, description="Base interface for structure categories/schemas")
class Category:
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    label: str = strawberry.field(description="Label/name of the category")
    description: Optional[str] = strawberry.field(default=None, description="Description of the category")
    age_name: str = strawberry.field(description="The name of the category as used in AGE (e.g. 'Cell', 'ROI')")
    purl: Optional[str] = strawberry.field(default=None, description="Persistent URL for this category")
    color: Optional[List[int]] = strawberry.field(default=None, description="Color as RGBA list (0-255)")
    tags: List[CategoryTag] = kante.django_field(description="List of tags associated with this category")
    image: MediaStore = strawberry.field(description="An image representing this category, for visualization purposes")
    graph: Graph = strawberry.field(description="The graph this category belongs to")
    relevant_queries: List["GraphQuery"] = strawberry.field(default_factory=list, description="List of relevant queries that use this category as input")

    @kante.django_field(description="The graph this category belongs to")
    def pinned(self, info: kante.Info) -> bool:
        """Whether this category is pinned for quick access in the UI."""
        # In a real implementation, we would check the user's preferences or a pinned categories list.
        # For this example, we'll return False for simplicity.
        return cast(models.Category, self).pinned_by.filter(id=info.context.user.id).exists()


@kante.django_interface(models.EdgeCategory, description="Base interface for graph schemas")
class EdgeCategory:
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    graph_id: strawberry.ID = strawberry.field(description="ID of the graph this category belongs to")
    label: str = strawberry.field(description="Label/name of the category")

    description: Optional[str] = strawberry.field(default=None, description="Description of the category")
    purl: Optional[str] = strawberry.field(default=None, description="Persistent URL for this category")
    color: Optional[List[int]] = strawberry.field(default=None, description="Color as RGBA list (0-255)")
    relevant_edge_queries: List["EdgeQuery"] = strawberry.field(default_factory=list, description="List of relevant queries that use this category as input")

    @kante.django_field(description="The graph this category belongs to")
    def materializable_as(self) -> List[MaterializedEdge]:
        """Return a list of materialized edges that can be derived for this edge category."""
        # In a real implementation, we would check if this edge category is used in any GraphPairsQuery,
        # and if so, return the corresponding materialized edges from the graph.
        # For this example, we'll return an empty list for simplicity.
        return []


@kante.django_interface(models.NodeCategory, description="Base interface for graph schemas")
class NodeCategory:
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    label: str = strawberry.field(description="Label/name of the category")
    graph_id: strawberry.ID = strawberry.field(description="ID of the graph this category belongs to")
    description: Optional[str] = strawberry.field(default=None, description="Description of the category")
    purl: Optional[str] = strawberry.field(default=None, description="Persistent URL for this category")
    color: Optional[List[int]] = strawberry.field(default=None, description="Color as RGBA list (0-255)")
    position_x: float = strawberry.field(description="X coordinate")
    position_y: float = strawberry.field(description="Y coordinate")
    position_z: Optional[float] = strawberry.field(default=None, description="Z coordinate (optional)")
    width: Optional[float] = strawberry.field(default=None, description="Width for visualization (optional)")
    height: Optional[float] = strawberry.field(default=None, description="Height for visualization (optional)")
    relevant_node_queries: List["NodeQuery"] = strawberry.field(default_factory=list, description="List of relevant node queries that use this category as input")


@kante.interface(description="Base interface for plottable queries")
class Plottable:
    columns: List[Column] = strawberry.field(description="List of columns to return in the table query result")

    @kante.django_field(description="The graph this category belongs to")
    def scatter_plots(self) -> List["ScatterPlot"]:
        """Return a list of table queries that can be visualized as scatterplots."""
        # In a real implementation, we would check if this query is used in any GraphTableQuery with a scatterplot visualization,
        # and if so, return those queries.
        # For this example, we'll return an empty list for simplicity.
        return []


@kante.django_interface(models.GraphQuery, description="Base interface for entity categories/schemas")
class GraphQuery:
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    graph: "Graph" = strawberry.field(description="The graph this query belongs to")
    label: str = strawberry.field(description="Label/name of the category")
    description: Optional[str] = strawberry.field(default=None, description="Description of the category")
    relevant_for: List["NodeCategory"] = strawberry.field(default_factory=list, description="List of node categories for which this query is relevant")


@kante.django_type(models.GraphNodesQuery, filters=filters.GraphNodesQueryFilter, pagination=True, ordering=order.GraphNodesQueryOrder, description="Base interface for graph schemas")
class GraphNodesQuery(GraphQuery):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    node_category: "NodeCategory" = strawberry.field(description="The node category/schema to query")


@kante.django_type(models.GraphTableQuery, filters=filters.GraphTableQueryFilter, pagination=True, ordering=order.GraphTableQueryOrder, description="Base interface for graph schemas")
class GraphTableQuery(GraphQuery, Plottable):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    query: scalars.CypherLiteral = strawberry.field(description="The Cypher query to execute for this table query")
    columns: List[Column] = strawberry.field(description="List of columns to return in the table query result")
    builder_args: Optional[BuilderArgs] = strawberry.field(default=None, description="If this graph was built using a builder function, the arguments used for building it, which can be used for debugging or rebuilding the graph with different parameters")


@kante.django_type(models.GraphPairsQuery, filters=filters.GraphPairsQueryFilter, pagination=True, ordering=order.GraphPairsQueryOrder, description="Base interface for graph schemas")
class GraphPairsQuery(GraphQuery):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    source_category: "NodeCategory" = strawberry.field(description="The source node category/schema to query")
    target_category: "NodeCategory" = strawberry.field(description="The target node category/schema to query")
    edge_category: Optional["EdgeCategory"] = strawberry.field(default=None, description="Optional edge category/schema to filter pairs by")


@kante.django_type(models.GraphPathQuery, filters=filters.GraphPathQueryFilter, pagination=True, ordering=order.GraphPathQueryOrder, description="Base interface for graph schemas")
class GraphPathQuery(GraphQuery):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")


@kante.django_type(models.EntityCategory, filters=filters.EntityCategoryFilter, pagination=True, ordering=order.EntityCategoryOrder, description="An entity category/schema definition")
class EntityCategory(NodeCategory, Category):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    graph: "Graph" = strawberry.field(description="The graph this category belongs to")
    label: str = strawberry.field(description="Label/name of the category")
    instance_kind: strawberry.auto = strawberry.field(description="What type of instance, (taking from the universe) 'LOT', 'BIOLOGICAL', 'PHYSICAL'")
    property_definitions: List[PropertyDefinition] = strawberry.field(default_factory=list, description="List of property definitions for this entity category")

    @kante.django_field(description="The graph this category belongs to")
    def entities(self, filters: filters.EntityFilter | None = None, ordering: list[order.EntityOrder] | None = None, pagination: pagination.GraphPaginationInput | None = None) -> List["Entity"]:
        """Fetch the latest entity instance of this category."""
        # In a real implementation, we would query the graph for the most recently derived entity
        # that belongs to this category. For this example, we'll return None for simplicity.
        raise NotImplementedError("Latest entity fetching not implemented yet")


@kante.django_type(models.StructureCategory, filters=filters.StructureCategoryFilter, pagination=True, ordering=order.StructureCategoryOrder, description="A structure category/schema definition")
class StructureCategory(NodeCategory, Category):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    identifier: str = kante.django_field(description="The identifier for this structure category, which is used to link structures to entities (e.g. 'Cell', 'ROI', 'Tissue')")


@kante.django_type(models.MetricCategory, filters=filters.MetricCategoryFilter, pagination=True, ordering=order.MetricCategoryOrder, description="A metric category/schema definition")
class MetricCategory(NodeCategory, Category):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    value_kind: enums.ValueKind = strawberry.field(description="What type of value, (taking from the universe) 'QUANTITATIVE', 'QUALITATIVE', 'BOOLEAN'")
    structure_category: StructureCategory = kante.django_field(description="The structure category/schema this metric is relevant for, if applicable")
    pass


@kante.django_interface(models.NaturalEventCategory, description="Base interface for event categories/schemas")
class EventCategory(NodeCategory, Category):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    property_definitions: List[PropertyDefinition] = strawberry.field(default_factory=list, description="List of property definitions for this entity category")

    @kante.django_field(description="The graph this category belongs to")
    def inputs(self) -> List[EventRole]:
        """Return the list of roles defined for this event category."""
        # In a real implementation, we would query the database for the roles associated with this event category.
        # For this example, we'll return an empty list for simplicity.
        return []

    @kante.django_field(description="The graph this category belongs to")
    def outputs(self) -> List[EventRole]:
        """Return the list of roles defined for this event category."""
        # In a real implementation, we would query the database for the roles associated with this event category.
        # For this example, we'll return an empty list for simplicity.
        return []

    pass


@kante.django_type(models.ProtocolEventCategory, filters=filters.ProtocolEventCategoryFilter, pagination=True, ordering=order.ProtocolEventCategoryOrder, description="A relation category/schema definition")
class ProtocolEventCategory(EventCategory, Category):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    """A protocol event category/schema definition, which is a subtype of EventCategory."""

    pass


@kante.django_type(models.NaturalEventCategory, filters=filters.NaturalEventCategoryFilter, pagination=True, ordering=order.NaturalEventCategoryOrder, description="A relation category/schema definition")
class NaturalEventCategory(EventCategory, Category):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    """A natural event category/schema definition, which is a subtype of EventCategory."""

    pass


@kante.django_type(models.MeasurementCategory, filters=filters.MeasurementCategoryFilter, pagination=True, ordering=order.MeasurementCategoryOrder, description="A measurement category/schema definition")
class MeasurementCategory(EdgeCategory, Category):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    """A relation category/schema definition, which defines the type of a relation edge between entities. It can also include property definitions for the relation."""
    property_definitions: List[PropertyDefinition] = strawberry.field(default_factory=list, description="List of property definitions for this entity category")

    @kante.django_field(description="The graph this category belongs to")
    def source_descriptor(self) -> StructureDescriptor:
        """Return the source node category definition if this edge category is used in a pairs query."""
        # In a real implementation, we would check if this edge category is used as a filter in any EdgePairsQuery,
        # and if so, return the source node category from that query.
        # For this example, we'll return None for simplicity.
        return StructureDescriptor.from_pydantic(cast(models.MeasurementCategory, self).source_definition_model)

    @kante.django_field(description="The graph this category belongs to")
    def target_descriptor(self) -> EntityDescriptor:
        """Return the target node category definition if this edge category is used in a pairs query."""
        # In a real implementation, we would check if this edge category is used as a filter in any EdgePairsQuery,
        # and if so, return the target node category from that query.
        # For this example, we'll return None for simplicity.
        return EntityDescriptor.from_pydantic(cast(models.MeasurementCategory, self).target_definition_model)

    pass


@kante.django_type(models.RelationCategory, filters=filters.RelationCategoryFilter, pagination=True, ordering=order.RelationCategoryOrder, description="A relation category/schema definition")
class RelationCategory(EdgeCategory, Category):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    """A relation category/schema definition, which defines the type of a relation edge between entities. It can also include property definitions for the relation."""
    property_definitions: List[PropertyDefinition] = strawberry.field(default_factory=list, description="List of property definitions for this entity category")

    @kante.django_field(description="The graph this category belongs to")
    def source_descriptor(self) -> EntityDescriptor:
        """Return the source node category definition if this edge category is used in a pairs query."""
        # In a real implementation, we would check if this edge category is used as a filter in any EdgePairsQuery,
        # and if so, return the source node category from that query.
        # For this example, we'll return None for simplicity.
        return EntityDescriptor.from_pydantic(cast(models.EdgeCategory, self).source_definition_model)

    @kante.django_field(description="The graph this category belongs to")
    def target_descriptor(self) -> EntityDescriptor:
        """Return the target node category definition if this edge category is used in a pairs query."""
        # In a real implementation, we would check if this edge category is used as a filter in any EdgePairsQuery,
        # and if so, return the target node category from that query.
        # For this example, we'll return None for simplicity.
        return EntityDescriptor.from_pydantic(cast(models.EdgeCategory, self).target_definition_model)

    pass


@kante.django_type(models.StructureRelationCategory, filters=filters.StructureRelationCategoryFilter, pagination=True, ordering=order.StructureRelationCategoryOrder, description="A relation category/schema definition")
class StructureRelationCategory(EdgeCategory, Category):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    """A relation category/schema definition, which defines the type of a relation edge between entities. It can also include property definitions for the relation."""
    property_definitions: List[PropertyDefinition] = strawberry.field(default_factory=list, description="List of property definitions for this entity category")

    @kante.django_field(description="The graph this category belongs to")
    def source_descriptor(self) -> StructureDescriptor:
        """Return the source node category definition if this edge category is used in a pairs query."""
        # In a real implementation, we would check if this edge category is used as a filter in any EdgePairsQuery,
        # and if so, return the source node category from that query.
        # For this example, we'll return None for simplicity.
        return StructureDescriptor.from_pydantic(cast(models.StructureRelationCategory, self).source_definition_model)

    @kante.django_field(description="The graph this category belongs to")
    def target_descriptor(self) -> StructureDescriptor:
        """Return the target node category definition if this edge category is used in a pairs query."""
        # In a real implementation, we would check if this edge category is used as a filter in any EdgePairsQuery,
        # and if so, return the target node category from that query.
        # For this example, we'll return None for simplicity.
        return StructureDescriptor.from_pydantic(cast(models.StructureRelationCategory, self).target_definition_model)


@kante.django_interface(models.NodeQuery, description="Base interface for entity categories/schemas")
class NodeQuery:
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    graph: "Graph" = strawberry.field(description="The graph this query belongs to")
    label: str = strawberry.field(description="Label/name of the category")
    description: Optional[str] = strawberry.field(default=None, description="Description of the category")
    relevant_for: List["NodeCategory"] = strawberry.field(default_factory=list, description="List of node categories for which this query is relevant")


@kante.django_type(models.NodeTableQuery, filters=filters.NodeTableQueryFilter, pagination=True, ordering=order.NodeTableQueryOrder, description="Base interface for graph schemas")
class NodeTableQuery(NodeQuery, Plottable):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    query: scalars.CypherLiteral = strawberry.field(description="The Cypher query to execute for this table query")
    columns: List[Column] = strawberry.field(description="List of columns to return in the table query result")
    builder_args: Optional[BuilderArgs] = strawberry.field(default=None, description="If this graph was built using a builder function, the arguments used for building it, which can be used for debugging or rebuilding the graph with different parameters")


@kante.django_type(models.NodePairsQuery, filters=filters.NodePairsQueryFilter, pagination=True, ordering=order.NodePairsQueryOrder, description="Base interface for graph schemas")
class NodePairsQuery(NodeQuery):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    source_category: "NodeCategory" = strawberry.field(description="The source node category/schema to query")
    target_category: "NodeCategory" = strawberry.field(description="The target node category/schema to query")
    edge_category: Optional["EdgeCategory"] = strawberry.field(default=None, description="Optional edge category/schema to filter pairs by")


@kante.django_type(models.NodePathQuery, filters=filters.NodePathQueryFilter, pagination=True, ordering=order.NodePathQueryOrder, description="Base interface for graph schemas")
class NodePathQuery(NodeQuery):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")


@kante.django_interface(models.EdgeQuery, description="Base interface for entity categories/schemas")
class EdgeQuery:
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    graph: "Graph" = strawberry.field(description="The graph this query belongs to")
    label: str = strawberry.field(description="Label/name of the category")
    description: Optional[str] = strawberry.field(default=None, description="Description of the category")
    relevant_for: List["NodeCategory"] = strawberry.field(default_factory=list, description="List of node categories for which this query is relevant")


@kante.django_type(models.EdgeTableQuery, filters=filters.EdgeTableQueryFilter, pagination=True, ordering=order.EdgeTableQueryOrder, description="Base interface for graph schemas")
class EdgeTableQuery(EdgeQuery, Plottable):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    query: scalars.CypherLiteral = strawberry.field(description="The Cypher query to execute for this table query")
    columns: List[Column] = strawberry.field(description="List of columns to return in the table query result")
    builder_args: Optional[BuilderArgs] = strawberry.field(default=None, description="If this graph was built using a builder function, the arguments used for building it, which can be used for debugging or rebuilding the graph with different parameters")


@kante.django_type(models.EdgePairsQuery, filters=filters.EdgePairsQueryFilter, pagination=True, ordering=order.EdgePairsQueryOrder, description="Base interface for graph schemas")
class EdgePairsQuery(EdgeQuery):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    source_category: "NodeCategory" = strawberry.field(description="The source node category/schema to query")
    target_category: "NodeCategory" = strawberry.field(description="The target node category/schema to query")
    edge_category: Optional["EdgeCategory"] = strawberry.field(default=None, description="Optional edge category/schema to filter pairs by")


@kante.django_type(models.EdgePathQuery, filters=filters.EdgePathQueryFilter, pagination=True, ordering=order.EdgePathQueryOrder, description="Base interface for graph schemas")
class EdgePathQuery(EdgeQuery):
    id: strawberry.ID = strawberry.field(description="Database ID of the category")


# ===========================================
# PROPERTY TYPE
# ===========================================


@kante.django_type(models.ScatterPlot, filters=filters.ScatterPlotFilter, pagination=True, ordering=order.ScatterPlotOrder, description="Result of linking a structure to an entity")
class ScatterPlot:
    label: str = strawberry.field(description="Label/name of the scatter plot definition")
    description: Optional[str] = strawberry.field(default=None, description="Description of the scatter plot definition")
    id: strawberry.ID = strawberry.field(description="Database ID of the category")
    id_column: str = strawberry.field(description="The name of the column to use for point identifiers (e.g. structure ID, or entity id)")
    x_column: str = strawberry.field(description="The name of the column to use for x values")
    y_column: str = strawberry.field(description="The name of the column to use for y values")
    color_column: Optional[str] = strawberry.field(default=None, description="The name of the column to use for color values (optional)")
    size_column: Optional[str] = strawberry.field(default=None, description="The name of the column to use for size values (optional)")
    shape_column: Optional[str] = strawberry.field(default=None, description="The name of the column to use for shape values (optional)")

    @kante.django_field(description="The graph this category belongs to")
    def query(self) -> Plottable:
        """Fetch the data points for this scatter plot."""
        # In a real implementation, we would query the graph for the data points linked to this structure and entity.
        # For this example, we'll return an empty list for simplicity.
        model = cast(models.ScatterPlot, self)
        if model.graph_query:
            return model.graph_query
        elif model.node_query:
            return model.node_query
        elif model.path_query:
            return model.path_query
        else:
            raise ValueError("ScatterPlot must have either a graph_query, node_query, or path_query")


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
    def graph_id(self) -> scalars.GraphID:
        return self._entity.graph_id

    @strawberry.field(description="The property key/name")
    async def definition(self) -> Optional[PropertyDefinition]:
        """Fetch the property definition from the schema based on the key."""
        # In a real implementation, we would look up the entity's category,
        # then find the property definition matching this key.
        # For this example, we'll return None for simplicity.
        return None

    @strawberry.field(description="The timestamp when this property was last derived (unix ms)")
    async def key(self) -> Optional[str]:
        """Return the property key/name."""
        return self._key

    @strawberry.field(description="The property value")
    async def value(self) -> AnyScalar | None:
        """Return the value of the property."""
        # In a real implementation, we would fetch the value from the entity's properties.
        # For this example, we'll return None for simplicity.
        value = self._entity.get_property(self._key)

        return value

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

T = TypeVar("T", bound="Node")
V = TypeVar("V", bound=RetrievedNode)


@strawberry.interface(description="Base interface for all graph nodes")
class Node(Generic[V]):
    """
    Base interface that all graph nodes implement.
    Uses strawberry.Private to hold the underlying RetrievedNode data.
    """

    _value: strawberry.Private[V]

    def __hash__(self):
        return hash(self._value)

    @strawberry.field(description="Local AGE graph ID")
    def graph_id(self) -> int:
        return self._value.id

    @kante.django_field(description="The graph this node belongs to")
    def graph(self) -> Graph:
        """Fetch the graph this node belongs to."""
        # In a real implementation, we would fetch the graph based on the node's graph_id.
        # For this example, we'll return None for simplicity.
        return cast(Graph, models.Graph.objects.get_graph_from_graph_name(self._value.graph_name))

    @strawberry.field(description="Global identifier in format 'graph_name:graph_id'")
    def global_id(self) -> GlobalID:
        return self._value.global_id

    @strawberry.field(description="The AGE graph label as recently materialized (e.g. 'Cell IAC100', 'ROI 1')")
    def label(self) -> str:
        """Should return the most specific label for this node (e.g. 'Cell' instead of 'Entity') Composed by its propetries"""
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

    @strawberry.field(description="The timestamp when this entity was materialized (unix ms)")
    def pinned(self) -> bool:
        """ """
        return False

    @classmethod
    def to_subtype(cls, value: RetrievedNode) -> "Node":
        """Factory method to create the appropriate Node subtype based on the value."""
        return cast_node_to_graphql_type(value)

    @classmethod
    def from_specific(cls: Type[T], subtype: V) -> T:
        """Factory method to convert a Node subtype back to the base Node interface."""
        return cls(_value=subtype)


# ===========================================
# VERSIONED NODE INTERFACE
# ===========================================


@strawberry.interface(description="Interface for versioned nodes with schema tracking")
class VersionedNode(Node):
    """Interface for nodes that track schema version and derivation time."""

    @strawberry.field(description="External object ID this entity references")
    def lifecycle(self) -> Optional[str]:
        return self._value.lifecycle

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
class Entity(VersionedNode, Node[RetrievedNode]):
    """
    An entity represents a domain object (e.g. AIS, Cell, Soma) with properties
    derived from supporting evidence structures.
    """

    @strawberry.field(description="The entity type/kind (e.g. 'AIS', 'Cell')")
    def kind(self) -> str:
        return self._value.kind or self._value.label

    @strawberry.field(description="Category ID linking to EntityCategory model")
    def category_id(self) -> Optional[str]:
        return self._value.category_id

    @kante.django_field(description="The graph this node belongs to")
    def category(self) -> EntityCategory:
        """Fetch the graph this node belongs to."""
        # In a real implementation, we would fetch the graph based on the node's graph_id.
        # For this example, we'll return None for simplicity.
        return cast(EntityCategory, models.EntityCategory.objects.get(id=self._value.category_id))

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

    @kante.django_field(description="The source entity of this relation")
    def measured_by(self) -> List["Measurement"]:
        """Return the structures that provide evidence for this relation."""
        # In a real implementation, we would fetch the linked structures
        # from the graph and return them as Structure types.
        # For this example, we'll return an empty list.
        return []

    @kante.django_field(description="The source entity of this relation")
    def participated_in(self) -> List["InputParticipation"]:
        """Return the structures that provide evidence for this relation."""
        # In a real implementation, we would fetch the linked structures
        # from the graph and return them as Structure types.
        # For this example, we'll return an empty list.
        return []

    @kante.django_field(description="The source entity of this relation")
    def resulted_out(self) -> List["OutputParticipation"]:
        """Return the structures that provide evidence for this relation."""
        # In a real implementation, we would fetch the linked structures
        # from the graph and return them as Structure types.
        # For this example, we'll return an empty list.
        return []


# ===========================================
# STRUCTURE TYPE
# ===========================================


@strawberry.type(description="A structure that provides evidence for entities")
class Structure(Node[RetrievedStructure]):
    """
    A structure represents an evidence source (e.g. ROI, Image) that
    can have measurements attached and inform entities.
    """

    @strawberry.field(description="Schema identifier (e.g. '@mikro/roi')")
    def identifier(self) -> StructureIdentifier:
        return self._value.identifier or ""

    @strawberry.field(description="External object ID this structure references")
    def object(self) -> str:
        return self._value.object or ""

    @strawberry.field(description="Category ID linking to StructureCategory model")
    def category_id(self) -> str:
        return self._value.category_id

    @kante.django_field(description="The graph this node belongs to")
    async def category(self) -> "StructureCategory":
        """Fetch the graph this node belongs to."""
        return await loaders.structure_category_loader.load(self._value.category_id)

    @kante.django_field(description="The graph this node belongs to")
    async def metrics(self) -> List["Metric"]:
        """Fetch the graph this node belongs to."""
        return []


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

    @strawberry.field(description="List of the current derived properties for this event")
    def measured_from(self) -> datetime:
        """Return the structures that provide evidence for this event."""
        # In a real implementation, we would fetch the linked structures
        # from the graph and return them as Structure types.
        # For this example, we'll return an empty list.
        return self._value.cleaned_properties

    @kante.django_field(description="The source entity of this relation")
    def measured_to(self) -> datetime:
        """Return the structures that provide evidence for this event."""
        # In a real implementation, we would fetch the linked structures
        # from the graph and return them as Structure types.
        # For this example, we'll return an empty list.
        return self._value.cleaned_properties

    @kante.django_field(description="The source entity of this relation")
    def category(self) -> NaturalEventCategory:
        """Return the category of this natural event."""
        # In a real implementation, we would fetch the category based on the category_id.
        # For this example, we'll return None for simplicity.
        assert self._value.category_id is not None, "NaturalEvent must have a category_id to fetch category"
        return cast(NaturalEventCategory, models.NaturalEventCategory.objects.get(id=self._value.category_id))

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
# METRIC TYPE
# ===========================================


@strawberry.type(description="A metric node representing computed values")
class Metric(Node[RetrievedMetric]):
    """
    A metric represents a computed or aggregated value in the graph.
    """

    @strawberry.field(description="Category ID linking to MetricCategory model")
    def category_id(self) -> Optional[str]:
        return self._value.category_id

    @strawberry.field(description="The metric value")
    def value(self) -> AnyScalar:
        return self._value.value

    @kante.django_field(description="The source entity of this relation")
    def category(self) -> MetricCategory:
        """Return the category of this natural event."""
        # In a real implementation, we would fetch the category based on the category_id.
        # For this example, we'll return None for simplicity.
        assert self._value.category_id is not None, "NaturalEvent must have a category_id to fetch category"
        return cast(MetricCategory, models.MetricCategory.objects.get(id=self._value.category_id))


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

    @strawberry.field(description="List of the current derived properties for this event")
    def measured_from(self) -> datetime:
        """Return the structures that provide evidence for this event."""
        # In a real implementation, we would fetch the linked structures
        # from the graph and return them as Structure types.
        # For this example, we'll return an empty list.
        return self._value.cleaned_properties

    @kante.django_field(description="The source entity of this relation")
    def measured_to(self) -> datetime:
        """Return the structures that provide evidence for this event."""
        # In a real implementation, we would fetch the linked structures
        # from the graph and return them as Structure types.
        # For this example, we'll return an empty list.
        return self._value.cleaned_properties

    @kante.django_field(description="The source entity of this relation")
    def category(self) -> ProtocolEventCategory:
        """Return the category of this natural event."""
        # In a real implementation, we would fetch the category based on the category_id.
        # For this example, we'll return None for simplicity.
        assert self._value.category_id is not None, "NaturalEvent must have a category_id to fetch category"
        return cast(ProtocolEventCategory, models.ProtocolEventCategory.objects.get(id=self._value.category_id))

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
# BASE EDGE INTERFACE
# ===========================================
T = TypeVar("T", bound="Edge")
V = TypeVar("V", bound=RetrievedEdge)


@strawberry.interface(description="Base interface for all graph edges")
class Edge(Generic[V]):
    """
    Base interface that all graph edges implement.
    Uses strawberry.Private to hold the underlying RetrievedEdge data.
    """

    _value: strawberry.Private[V]

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
    def source_id(self) -> str:
        return self._value.unique_left_id

    @strawberry.field(description="Global ID of the target/right node")
    def target_id(self) -> str:
        return self._value.unique_right_id

    @classmethod
    def to_subtype(cls, value: RetrievedEdge) -> "Edge":
        """Factory method to create the appropriate Edge subtype based on the value."""
        return cast_edge_to_graphql_type(value)

    @classmethod
    def from_specific(cls: Type[T], subtype: V) -> T:
        """Factory method to convert an Edge subtype back to the base Edge interface."""
        return cls(_value=subtype)


@strawberry.interface(description="Interface for edges that track schema version and derivation time")
class Event:
    """
    Base interface for all event types in the graph.
    """


@strawberry.type(description="An activity representing provenance information")
class Activity(Node):
    """
    An activity records who performed what provenance action and when.
    It links to the graph artifacts it generated or asserted.
    """

    _value: strawberry.Private[RetrievedNode]

    @strawberry.field(description="User/subject who performed the activity")
    def subject(self) -> Optional[str]:
        return self._value.subject

    @strawberry.field(description="Application that performed the activity")
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

    @strawberry.field(description="When this activity was created")
    def created_at(self) -> Optional[datetime]:
        return self._value.created_at


@strawberry.type(description="A relation representing a connection between two entities")
class ShadowLink(Node[retrieved.RetrievedShadowLink]):
    """
    A shadow link represents a relation between two entities that is not materialized in the graph but is inferred from other data.
    """

    @strawberry.field(description="The relation type/kind")
    def kind(self) -> str:
        return self._value.kind or self._value.label

    @strawberry.field(description="Category ID linking to RelationCategory model")
    def category_id(self) -> Optional[str]:
        return self._value.category_id


# ===========================================
# RELATION TYPE
# ===========================================


@strawberry.type(description="A relation edge between two entities")
class Relation(Edge[retrieved.RetrievedEdge]):
    """
    A relation is an edge between two entities that establishes a
    non-measurement relationship (e.g., parent-child, part-of).
    """

    _value: strawberry.Private[RetrievedEdge]

    @kante.django_field(description="The graph this node belongs to")
    async def source(self) -> Entity:
        """Fetch the source structure of this relation."""
        # In a real implementation, we would fetch the source structure based on the left_id.
        # For this example, we'll return None for simplicity.
        raise NotImplementedError("Source fetching not implemented")

    @kante.django_field(description="The graph this node belongs to")
    async def target(self) -> Entity:
        """Fetch the target structure of this relation."""
        # In a real implementation, we would fetch the target structure based on the right_id.
        # For this example, we'll return None for simplicity.
        raise NotImplementedError("Source fetching not implemented")

    @strawberry.field(description="When this relation became valid according to the evidence")
    def measured_from(self) -> Optional[datetime]:
        return self._value.valid_from

    @strawberry.field(description="When this relation stopped being valid according to the evidence")
    def measured_to(self) -> Optional[datetime]:
        return self._value.valid_to

    @strawberry.field(description="When this relation was created")
    def created_at(self) -> Optional[datetime]:
        return self._value.created_at

    @kante.django_field(description="The graph this node belongs to")
    async def category(self) -> "RelationCategory":
        """Fetch the graph this node belongs to."""
        return await loaders.relation_category_loader.load(self._value.category_id)

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

    @kante.django_field(description="The graph this node belongs to")
    async def source(self) -> Structure:
        """Fetch the source structure of this relation."""
        # In a real implementation, we would fetch the source structure based on the left_id.
        # For this example, we'll return None for simplicity.
        raise NotImplementedError("Source fetching not implemented")

    @kante.django_field(description="The graph this node belongs to")
    async def target(self) -> Structure:
        """Fetch the target structure of this relation."""
        # In a real implementation, we would fetch the target structure based on the right_id.
        # For this example, we'll return None for simplicity.
        raise NotImplementedError("Source fetching not implemented")

    @strawberry.field(description="When this relation was created")
    def created_at(self) -> Optional[datetime]:
        return self._value.created_at

    @strawberry.field(description="Category ID linking to StructureRelationCategory model")
    def category_id(self) -> Optional[str]:
        return self._value.category_id

    @strawberry.field(description="When this relation became valid according to the evidence")
    def measured_from(self) -> Optional[datetime]:
        return self._value.valid_from

    @strawberry.field(description="When this relation stopped being valid according to the evidence")
    def measured_to(self) -> Optional[datetime]:
        return self._value.valid_to

    @kante.django_field(description="The graph this node belongs to")
    async def category(self) -> "StructureRelationCategory":
        """Fetch the graph this node belongs to."""
        return await loaders.structure_relation_category_loader.load(self._value.category_id)


@kante.type(description="A natural event category/schema definition")
class Describes(Edge):
    pass

    @kante.django_field(description="The graph this node belongs to")
    async def source(self) -> Metric:
        """Fetch the source structure of this relation."""
        # In a real implementation, we would fetch the source structure based on the left_id.
        # For this example, we'll return None for simplicity.
        raise NotImplementedError("Source fetching not implemented")

    @kante.django_field(description="The graph this node belongs to")
    async def target(self) -> Structure:
        """Fetch the target structure of this relation."""
        # In a real implementation, we would fetch the target structure based on the right_id.
        # For this example, we'll return None for simplicity.
        raise NotImplementedError("Source fetching not implemented")


@kante.type(description="A natural event category/schema definition")
class Measurement(Edge):
    pass

    @kante.django_field(description="The graph this node belongs to")
    async def category(self) -> "MeasurementCategory":
        """Fetch the graph this node belongs to."""
        return await loaders.measurement_category_loader.load(self._value.category_id)

    @kante.django_field(description="The graph this node belongs to")
    async def source(self) -> Structure:
        """Fetch the source structure of this relation."""
        # In a real implementation, we would fetch the source structure based on the left_id.
        # For this example, we'll return None for simplicity.
        raise NotImplementedError("Source fetching not implemented")

    @kante.django_field(description="The graph this node belongs to")
    async def target(self) -> Entity:
        """Fetch the target structure of this relation."""
        # In a real implementation, we would fetch the target structure based on the right_id.
        # For this example, we'll return None for simplicity.
        raise NotImplementedError("Source fetching not implemented")

    @strawberry.field(description="When this relation became valid according to the evidence")
    async def measured_from(self) -> Optional[datetime]:
        return self._value.valid_from

    @strawberry.field(description="When this relation stopped being valid according to the evidence")
    async def measured_to(self) -> Optional[datetime]:
        return self._value.valid_to


@kante.type(description="An assertion edge linking provenance activity to asserted graph artifacts")
class Assertion(Edge):
    pass


@kante.type(description="A natural event category/schema definition")
class Generated(Edge):
    pass


@kante.type(description="A natural event category/schema definition")
class InputParticipation(Edge):
    pass

    @kante.django_field(description="The graph this node belongs to")
    async def role(self) -> str:
        """Fetch the graph this node belongs to."""
        # In a real implementation, we would fetch the role property from this participation edge.
        # For this example, we'll return None for simplicity.
        return self._value.role or "participant"

    @kante.django_field(description="The graph this node belongs to")
    async def target(self) -> Event:
        """Fetch the graph this node belongs to."""
        # In a real implementation, we would fetch the role property from this participation edge.
        # For this example, we'll return None for simplicity.
        return self._value.role or "participant"

    @kante.django_field(description="The graph this node belongs to")
    async def source(self) -> Entity:
        """Fetch the graph this node belongs to."""
        # In a real implementation, we would fetch the role property from this participation edge.
        # For this example, we'll return None for simplicity.
        return self._value.role or "participant"


@kante.type(description="A natural event category/schema definition")
class OutputParticipation(Edge):
    pass

    @kante.django_field(description="The graph this node belongs to")
    async def role(self) -> str:
        """Fetch the graph this node belongs to."""
        # In a real implementation, we would fetch the role property from this participation edge.
        # For this example, we'll return None for simplicity.
        return self._value.role or "participant"

    @kante.django_field(description="The graph this node belongs to")
    async def target(self) -> Entity:
        """Fetch the graph this node belongs to."""
        # In a real implementation, we would fetch the role property from this participation edge.
        # For this example, we'll return None for simplicity.
        return self._value.role or "participant"

    @kante.django_field(description="The graph this node belongs to")
    async def source(self) -> NaturalEvent:
        """Fetch the graph this node belongs to."""
        # In a real implementation, we would fetch the role property from this participation edge.
        # For this example, we'll return None for simplicity.
        return self._value.role or "participant"


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
NodeSubtype = Union[Entity, Structure, NaturalEvent, Metric, Reagent, ProtocolEvent, Activity]

# Union type for all edge subtypes
EdgeSubtype = Union[Relation, StructureRelation, Describes, Measurement, Assertion, Generated, ReifiesAsSource, ReifiesAsTarget, InputParticipation, OutputParticipation]


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
        case "ASSERTION":
            return Activity(_value=node)
        case "ACTIVITY":
            return Activity(_value=node)
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
        The appropriate Strawberry type instance (Measurement, Assertion edge, etc.)

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

    @strawberry.field(description="The graph name used for this render")
    def graph_name(self) -> str:
        return self._value.graph_name

    @strawberry.field(description="The graph rendered by this query")
    async def graph(self) -> Graph:
        return await loaders.graph_by_id_loader.load(self._value.graph_id)

    @strawberry.field(description="The graph query used for this render")
    async def query(self) -> GraphNodesQuery:
        return await loaders.graph_nodes_query_by_id_loader.load(self._value.graph_query_id)


@strawberry.interface(description="Base interface for graph render results")
class PathLike:
    nodes: List[Node] = strawberry.field(description="Nodes in the path")
    edges: List[Edge] = strawberry.field(description="Edges in the path")


@strawberry.type(description="Result of linking a structure to an entity")
class GraphPathRender(PathLike):
    _value: strawberry.Private[retrieved.RetrievedGraphPathRender]

    @strawberry.field(description="The graph name used for this render")
    def nodes(self) -> List[Node]:
        return [cast_node_to_graphql_type(node) for node in self._value.nodes]

    @strawberry.field(description="The graph name used for this render")
    def edges(self) -> List[Edge]:
        return [cast_edge_to_graphql_type(edge) for edge in self._value.edges]

    @strawberry.field(description="The graph name used for this render")
    def graph_name(self) -> str:
        return self._value.graph_name

    @strawberry.field(description="The graph rendered by this query")
    async def graph(self) -> Graph:
        return await loaders.graph_by_id_loader.load(self._value.graph_id)

    @strawberry.field(description="The graph query used for this render")
    async def query(self) -> GraphPathQuery:
        return await loaders.graph_path_query_by_id_loader.load(self._value.graph_query_id)


@strawberry.type(description="Result of linking a structure to an entity")
class GraphPairsRender:
    _value: strawberry.Private[retrieved.RetrievedGraphPairsRender]

    @strawberry.field(description="The graph name used for this render")
    def graph_name(self) -> str:
        return self._value.graph_name

    @strawberry.field(description="The graph rendered by this query")
    async def graph(self) -> Graph:
        return await loaders.graph_by_id_loader.load(self._value.graph_id)

    @strawberry.field(description="The graph query used for this render")
    async def query(self) -> GraphPairsQuery:
        return await loaders.graph_pairs_query_by_id_loader.load(self._value.graph_query_id)


@strawberry.type(description="Result of linking a structure to an entity")
class GraphTableRender:
    _value: strawberry.Private[retrieved.RetrievedGraphTableRender]

    @strawberry.field(description="The graph name used for this render")
    def graph_name(self) -> str:
        return self._value.graph_name

    @strawberry.field(description="The graph rendered by this query")
    async def graph(self) -> Graph:
        return await loaders.graph_by_id_loader.load(self._value.graph_id)

    @strawberry.field(description="The query used to generate this table")
    async def query(self) -> GraphTableQuery:
        return await loaders.graph_table_query_by_id_loader.load(self._value.graph_query_id)

    @strawberry.field(description="Rows of the rendered table")
    def rows(self) -> List[AnyScalar]:
        return self._value.rows


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


GraphStats, GraphStatsResolver = create_stats_type(
    model=models.Graph,
    filters=filters.GraphFilter,
    allowed_fields={
        "created_at": "created_at",
    },
    allowed_datetime_fields={"created_at": "created_at"},
)


CategoryTagStats, CategoryTagStatsResolver = create_stats_type(
    model=models.CategoryTag,
    filters=filters.CategoryTagFilter,
    allowed_fields={
        "created_at": "created_at",
    },
    allowed_datetime_fields={"created_at": "created_at"},
)


EntityCategoryStats, EntityCategoryStatsResolver = create_stats_type(
    model=models.EntityCategory,
    filters=filters.EntityCategoryFilter,
    allowed_fields={
        "created_at": "created_at",
    },
    allowed_datetime_fields={"created_at": "created_at"},
)


StructureCategoryStats, StructureCategoryStatsResolver = create_stats_type(
    model=models.StructureCategory,
    filters=filters.StructureCategoryFilter,
    allowed_fields={
        "created_at": "created_at",
    },
    allowed_datetime_fields={"created_at": "created_at"},
)


MetricCategoryStats, MetricCategoryStatsResolver = create_stats_type(
    model=models.MetricCategory,
    filters=filters.MetricCategoryFilter,
    allowed_fields={
        "created_at": "created_at",
    },
    allowed_datetime_fields={"created_at": "created_at"},
)


MeasurementCategoryStats, MeasurementCategoryStatsResolver = create_stats_type(
    model=models.MeasurementCategory,
    filters=filters.MeasurementCategoryFilter,
    allowed_fields={
        "created_at": "created_at",
    },
    allowed_datetime_fields={"created_at": "created_at"},
)


RelationCategoryStats, RelationCategoryStatsResolver = create_stats_type(
    model=models.RelationCategory,
    filters=filters.RelationCategoryFilter,
    allowed_fields={
        "created_at": "created_at",
    },
    allowed_datetime_fields={"created_at": "created_at"},
)


StructureRelationCategoryStats, StructureRelationCategoryStatsResolver = create_stats_type(
    model=models.StructureRelationCategory,
    filters=filters.StructureRelationCategoryFilter,
    allowed_fields={
        "created_at": "created_at",
    },
    allowed_datetime_fields={"created_at": "created_at"},
)


ProtocolEventCategoryStats, ProtocolEventCategoryStatsResolver = create_stats_type(
    model=models.ProtocolEventCategory,
    filters=filters.ProtocolEventCategoryFilter,
    allowed_fields={
        "created_at": "created_at",
    },
    allowed_datetime_fields={"created_at": "created_at"},
)


NaturalEventCategoryStats, NaturalEventCategoryStatsResolver = create_stats_type(
    model=models.NaturalEventCategory,
    filters=filters.NaturalEventCategoryFilter,
    allowed_fields={
        "created_at": "created_at",
    },
    allowed_datetime_fields={"created_at": "created_at"},
)
