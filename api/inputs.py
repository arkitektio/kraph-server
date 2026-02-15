"""
GraphQL Input types for the API using strawberry-pydantic.

These inputs use strawberry.experimental.pydantic to automatically
validate against the Pydantic input models from graph_engine.
"""

import strawberry
from typing import Optional, List
from enum import Enum

from graph_engine import input_models
from graph_engine.scalars import AnyScalar, GraphID
from graph_engine import scalars
from strawberry.experimental import pydantic
from typing import Annotated


@pydantic.input(model=input_models.MetricInput, description="Input for creating a new natural event definition in the graph schema")
class MetricInput:
    key: str = strawberry.field(description="The key/name of the metric")
    value: AnyScalar = strawberry.field(description="The value of the metric, which can be any scalar type (string, number, boolean)")
    pass


@pydantic.input(model=input_models.PlateChildInput, description="Input for requesting media upload credentials")
class PlateChildInput:
    """Input for requesting media upload credentials"""

    id: str
    type: str | None = None
    text: str | None = None
    value: str | None = None
    color: str | None = None
    font_size: str | None = None
    background_color: str | None = None
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None
    children: List[Annotated["PlateChildInput", strawberry.lazy(".")]] | None
    pass


# ==========================================
# SCHEMA DEFINITION INPUT TYPES (List-based)
# ==========================================


@pydantic.input(model=input_models.CreateStructureInput, all_fields=True, description="Input for creating a new structure")
class PinNodeInput:
    """Input for creating a new structure."""

    pass


@pydantic.input(model=input_models.DerivationRuleInput, all_fields=True, description="Configuration for property derivation rules")
class DerivationRuleInput:
    """Configuration for property derivation rules."""

    pass


@pydantic.input(model=input_models.PropertyDefinitionInput, all_fields=True, description="Definition of a property on an entity, structure, or relation")
class PropertyDefinitionInput:
    """Definition of a property on an entity, structure, or relation."""


# Filter Models
# =========================================
# Filter Models
# =========================================
@pydantic.input(model=input_models.RenderGraphNodesFilter, all_fields=True, description="Filters for querying node lists")
class RenderGraphNodesFilter:
    pass


@pydantic.input(model=input_models.RenderGraphNodesPagination, all_fields=True, description="Pagination options for querying node lists")
class RenderGraphNodesPagination:
    pass


@pydantic.input(model=input_models.RenderGraphNodesOrder, all_fields=True, description="Ordering options for querying node lists")
class RenderGraphNodesOrder:
    pass


@pydantic.input(model=input_models.RenderGraphPathFilter, all_fields=True, description="Filters for querying node lists")
class RenderGraphPathFilter:
    pass


@pydantic.input(model=input_models.RenderGraphPathPagination, all_fields=True, description="Pagination options for querying node lists")
class RenderGraphPathPagination:
    pass


@pydantic.input(model=input_models.RenderGraphPathOrder, all_fields=True, description="Ordering options for querying node lists")
class RenderGraphPathOrder:
    pass


@pydantic.input(model=input_models.RenderGraphPairsFilter, all_fields=True, description="Filters for querying node lists")
class RenderGraphPairsFilter:
    pass


@pydantic.input(model=input_models.RenderGraphPairsPagination, all_fields=True, description="Pagination options for querying node lists")
class RenderGraphPairsPagination:
    pass


@pydantic.input(model=input_models.RenderGraphPairsOrder, all_fields=True, description="Ordering options for querying node lists")
class RenderGraphPairsOrder:
    pass


@pydantic.input(model=input_models.RenderGraphTableFilter, all_fields=True, description="Filters for querying node lists")
class RenderGraphTableFilter:
    pass


@pydantic.input(model=input_models.RenderGraphTablePagination, all_fields=True, description="Pagination options for querying node lists")
class RenderGraphTablePagination:
    pass


@pydantic.input(model=input_models.RenderGraphTableOrder, all_fields=True, description="Ordering options for querying node lists")
class RenderGraphTableOrder:
    pass


# ==========================================
# Schema Creation Input Types
# ==========================================


@pydantic.input(model=input_models.StructureReferenceInput, all_fields=True, description="Input for creating a new natural event definition in the graph schema")
class StructureReferenceInput:
    pass


@pydantic.input(model=input_models.RoleMappingInput, all_fields=True, description="Input for creating a new natural event definition in the graph schema")
class RoleMappingInput:
    pass


@pydantic.input(model=input_models.OntologyReferenceInput, all_fields=True, description="Input for creating a new natural event definition in the graph schema")
class OntologyReferenceInput:
    pass


@pydantic.input(model=input_models.EntityDescriptorInput, all_fields=True, description="Input for creating a new natural event definition in the graph schema")
class EntityDescriptorInput:
    pass


@pydantic.input(model=input_models.EventRoleInput, all_fields=True, description="Input for creating a new natural event definition in the graph schema")
class EventRoleInput:
    pass


@pydantic.input(model=input_models.SequenceMappingInput, all_fields=True, description="Input for creating a new natural event definition in the graph schema")
class SequenceMappingInput:
    pass


@pydantic.input(model=input_models.CreateNaturalEventDefinitionInput, all_fields=True, description="Input for creating a new natural event definition in the graph schema")
class CreateNaturalEventDefinitionInput:
    pass


@pydantic.input(model=input_models.UpdateNaturalEventDefinitionInput, all_fields=True, description="Input for updating an existing natural event definition in the graph schema")
class UpdateNaturalEventDefinitionInput:
    pass


@pydantic.input(model=input_models.DeleteNaturalEventDefinitionInput, all_fields=True, description="Input for deleting an existing natural event definition in the graph schema")
class DeleteNaturalEventDefinitionInput:
    pass


@pydantic.input(model=input_models.CreateProtocolEventDefinitionInput, all_fields=True, description="Input for creating a new protocol event definition in the graph schema")
class CreateProtocolEventDefinitionInput:
    pass


@pydantic.input(model=input_models.UpdateProtocolEventDefinitionInput, all_fields=True, description="Input for updating an existing protocol event definition in the graph schema")
class UpdateProtocolEventDefinitionInput:
    pass


@pydantic.input(model=input_models.DeleteProtocolEventDefinitionInput, all_fields=True, description="Input for deleting an existing protocol event definition in the graph schema")
class DeleteProtocolEventDefinitionInput:
    pass


# ==========================================
# Node Creation Input Types
# ==========================================


@pydantic.input(model=input_models.CreateEntityDefinitionInput, all_fields=True, description="Input for creating a new entity definition in the graph schema")
class CreateEntityDefinitionInput:
    """Input for creating a new entity definition in the graph schema."""

    pass


@pydantic.input(model=input_models.UpdateEntityDefinitionInput, all_fields=True, description="Input for updating an existing entity definition in the graph schema")
class UpdateEntityDefinitionInput:
    id: strawberry.ID = strawberry.field(description="The ID of the entity definition to update")
    """Input for updating an existing entity definition in the graph schema."""

    pass


@pydantic.input(model=input_models.DeleteEntityDefinitionInput, all_fields=True, description="Input for deleting an existing entity definition in the graph schema")
class DeleteEntityDefinitionInput:
    id: strawberry.ID = strawberry.field(description="The ID of the entity definition to delete")
    """Input for deleting an existing entity definition in the graph schema."""

    pass


@pydantic.input(model=input_models.CreateStructureRelationDefinitionInput, all_fields=True, description="Input for creating a new structure relation definition in the graph schema")
class CreateStructureRelationDefinitionInput:
    """Input for creating a new structure relation definition in the graph schema."""

    pass


@pydantic.input(model=input_models.UpdateStructureRelationDefinitionInput, all_fields=True, description="Input for updating an existing structure relation definition in the graph schema")
class UpdateStructureRelationDefinitionInput:
    """Input for updating an existing structure relation definition in the graph schema."""

    pass


@pydantic.input(model=input_models.DeleteStructureRelationDefinitionInput, all_fields=True, description="Input for deleting an existing structure relation definition in the graph schema")
class DeleteStructureRelationDefinitionInput:
    """Input for deleting an existing structure relation definition in the graph schema."""

    pass


@pydantic.input(model=input_models.ArchiveStructureRelationDefinitionInput, all_fields=True, description="Input for archiving (soft deleting) an existing structure relation definition in the graph schema")
class ArchiveStructureRelationDefinitionInput:
    """Input for archiving (soft deleting) an existing structure relation definition in the graph schema."""

    pass


@pydantic.input(model=input_models.CreateStructureDefinitionInput, all_fields=True, description="Input for creating a new structure definition in the graph schema")
class CreateStructureDefinitionInput:
    """Input for creating a new structure definition in the graph schema."""

    pass


@pydantic.input(model=input_models.UpdateStructureDefinitionInput, all_fields=True, description="Input for updating an existing structure definition in the graph schema")
class UpdateStructureDefinitionInput:
    """Input for updating an existing structure definition in the graph schema."""

    pass


@pydantic.input(model=input_models.DeleteStructureDefinitionInput, all_fields=True, description="Input for deleting an existing structure definition in the graph schema")
class DeleteStructureDefinitionInput:
    """Input for deleting an existing structure definition in the graph schema."""

    pass


@pydantic.input(model=input_models.ArchiveStructureDefinitionInput, all_fields=True, description="Input for archiving (soft deleting) an existing structure definition in the graph schema")
class ArchiveStructureDefinitionInput:
    """Input for archiving (soft deleting) an existing structure definition in the graph schema."""

    pass


@pydantic.input(model=input_models.CreateMetricDefinitionInput, all_fields=True, description="Input for creating a new metric definition in the graph schema")
class CreateMetricDefinitionInput:
    """Input for creating a new metric definition in the graph schema."""

    pass


@pydantic.input(model=input_models.UpdateMetricDefinitionInput, all_fields=True, description="Input for updating an existing metric definition in the graph schema")
class UpdateMetricDefinitionInput:
    """Input for updating an existing metric definition in the graph schema."""

    pass


@pydantic.input(model=input_models.DeleteMetricDefinitionInput, all_fields=True, description="Input for deleting an existing metric definition in the graph schema")
class DeleteMetricDefinitionInput:
    """Input for deleting an existing metric definition in the graph schema."""

    pass


@pydantic.input(model=input_models.ArchiveMetricDefinitionInput, all_fields=True, description="Input for archiving (soft deleting) an existing metric definition in the graph schema")
class ArchiveMetricDefinitionInput:
    """Input for archiving (soft deleting) an existing metric definition in the graph schema."""

    pass


@pydantic.input(model=input_models.CreateRelationDefinitionInput, all_fields=True, description="Input for creating a new relation definition in the graph schema")
class CreateRelationDefinitionInput:
    """Input for creating a new relation definition in the graph schema."""

    pass


@pydantic.input(model=input_models.UpdateRelationDefinitionInput, all_fields=True, description="Input for updating an existing relation definition in the graph schema")
class UpdateRelationDefinitionInput:
    """Input for updating an existing relation definition in the graph schema."""

    pass


@pydantic.input(model=input_models.DeleteRelationDefinitionInput, all_fields=True, description="Input for deleting an existing relation definition in the graph schema")
class DeleteRelationDefinitionInput:
    """Input for deleting an existing relation definition in the graph schema."""

    pass


@pydantic.input(model=input_models.ArchiveRelationDefinitionInput, all_fields=True, description="Input for archiving (soft deleting) an existing relation definition in the graph schema")
class ArchiveRelationDefinitionInput:
    """Input for archiving (soft deleting) an existing relation definition in the graph schema."""

    pass


@pydantic.input(model=input_models.CreateNaturalEventInput, all_fields=True, description="Input for creating a new natural event instance")
class CreateNaturalEventInput:
    """Input for creating a new natural event instance."""

    pass


@pydantic.input(model=input_models.UpdateNaturalEventInput, all_fields=True, description="Input for updating an existing natural event instance")
class UpdateNaturalEventInput:
    """Input for updating an existing natural event instance."""

    pass


@pydantic.input(model=input_models.ArchiveNaturalEventInput, all_fields=True, description="Input for archiving (soft deleting) an existing natural event instance")
class ArchiveNaturalEventInput:
    """Input for archiving (soft deleting) an existing natural event instance."""

    pass


@pydantic.input(model=input_models.DeleteNaturalEventInput, all_fields=True, description="Input for deleting an existing natural event instance")
class DeleteNaturalEventInput:
    """Input for deleting an existing natural event instance."""

    pass


@pydantic.input(model=input_models.RecordMetricInput, description="Input for creating a new metric")
class RecordMetricInput(MetricInput):
    """Input for creating a new metric."""

    graph: str = strawberry.field(description="The graph id this metric will belong to")
    identifier: str = strawberry.field(description="The schema identifier for this metric (e.g. '@mikro/roi_volume')")
    object: str = strawberry.field(description="The unique ID of the object this metric references")
    value_kind: input_models.PropertyType = strawberry.field(description="The kind of value this metric represents")
    value: AnyScalar = strawberry.field(description="The value of the metric, which can be any scalar type (string, number, boolean)")


@pydantic.input(model=input_models.CreateMetricInput, description="Input for creating a new metric")
class CreateMetricInput(MetricInput):
    """Input for creating a new metric."""

    key: str = strawberry.field(description="The key/name of the metric")
    value: AnyScalar = strawberry.field(description="The value of the metric, which can be any scalar type (string, number, boolean)")
    structure: scalars.GraphID = strawberry.field(description="The composite ID of the structure this metric will be attached to")
    pass

    pass


@pydantic.input(model=input_models.UpdateMetricInput, description="Input for updating an existing metric")
class UpdateMetricInput(MetricInput):
    """Input for updating an existing metric. Note: this will not update the metric in-place, but rather create a new metric and archive the old one to preserve history."""

    id: str = strawberry.field(description="The ID of the metric to update")
    key: str = strawberry.field(description="The key/name of the metric")
    value: AnyScalar = strawberry.field(description="The value of the metric, which can be any scalar type (string, number, boolean)")
    pass


@pydantic.input(model=input_models.DeleteMetricInput, all_fields=True, description="Input for deleting an existing metric")
class DeleteMetricInput:
    """Input for deleting an existing metric."""

    pass


@pydantic.input(model=input_models.ArchiveMetricInput, all_fields=True, description="Input for archiving an existing metric")
class ArchiveMetricInput:
    """Input for archiving an existing metric."""

    pass


@pydantic.input(model=input_models.CreateStructureInput, all_fields=True, description="Input for creating a new entity category/type in the graph schema")
class CreateStructureInput:
    """Input for creating a new structure."""

    pass


@pydantic.input(model=input_models.UpdateStructureInput, all_fields=True, description="Input for updating an existing structure")
class UpdateStructureInput:
    """Input for updating an existing structure."""

    pass


@pydantic.input(model=input_models.DeleteStructureInput, description="Input for deleting an existing structure")
class DeleteStructureInput:
    """Input for deleting an existing structure."""

    id: scalars.GraphID = strawberry.field(description="The composite ID of the structure to delete")

    pass


@pydantic.input(model=input_models.ArchiveStructureInput, description="Input for deleting an existing structure")
class ArchiveStructureInput:
    """Input for deleting an existing structure."""

    id: scalars.GraphID = strawberry.field(description="The composite ID of the structure to archive")

    pass


@pydantic.input(model=input_models.CreateRelationInput, all_fields=True, description="Input for creating a new relation between two entities with supporting evidence")
class CreateRelationInput:
    """Input for creating a new relation."""

    pass


@pydantic.input(model=input_models.DeleteRelationInput, description="Input for deleting an existing relation")
class DeleteRelationInput:
    """Input for deleting an existing relation."""

    id: scalars.GraphID = strawberry.field(description="The ID of the relation to delete")

    pass


@pydantic.input(model=input_models.ArchiveRelationInput, description="Input for archiving an existing relation")
class ArchiveRelationInput:
    """Input for archiving an existing relation."""

    id: scalars.GraphID = strawberry.field(description="The ID of the relation to archive")

    pass


@pydantic.input(model=input_models.UpdateEntityInput, all_fields=True, description="Input for updating an existing entity")
class UpdateEntityInput:
    """Input for updating an existing entity. Note: this will not update the properties of the entity in-place, but rather
    attach new measurements to the correspoding toldyouso evidence structure"""

    pass


@pydantic.input(model=input_models.CreateEntityInput, all_fields=True, description="Input for creating a new entity")
class CreateEntityInput:
    pass


@pydantic.input(model=input_models.UpdateEntityInput, all_fields=True, description="Input for creating a new entity")
class EnsureEntityInput:
    global_id: scalars.GlobalID = strawberry.field(description="The global ID of the entity to ensure exists. If an entity with this global ID already exists, it will be returned. If not, a new entity will be created with this global ID.")
    pass


@pydantic.input(model=input_models.DeleteEntityInput, description="Input for deleting an existing entity")
class DeleteEntityInput:
    """Input for deleting an existing entity."""

    id: scalars.GraphID = strawberry.field(description="The ID of the entity to delete")


@pydantic.input(model=input_models.ArchiveEntityInput, description="Input for recalculating an entity's derived properties")
class ArchiveEntityInput:
    """Input for recalculating an entity's derived properties."""

    id: scalars.GraphID = strawberry.field(description="The ID of the entity to recalculate")


@strawberry.input(description="Input for recalculating entity properties")
class RecalculateEntityInput:
    """Input for recalculating an entity's derived properties."""

    id: scalars.GraphID = strawberry.field(description="The ID of the graph containing the entity")
    entity_id: str = strawberry.field(description="The entity's string ID")


# ==========================================
# ADDITIONAL INPUT TYPES (not in input_models)
# ==========================================


@strawberry.input(description="Input for linking a structure to an entity")
class LinkStructureInput:
    """Input for linking an existing structure to an entity."""

    structure_identifier: str = strawberry.field(description="Structure identifier")
    structure_object: str = strawberry.field(description="Structure object ID")
    entity_id: str = strawberry.field(description="Entity ID to link to")
    recalculate: Optional[bool] = strawberry.field(default=True, description="Whether to recalculate entity properties after linking")


@pydantic.input(model=input_models.EntityDefinitionInput, all_fields=True, description="Definition of an entity type in the graph schema")
class EntityDefinitionInput:
    """Definition of an entity type in the graph schema."""


@pydantic.input(model=input_models.EvidenceRequirementInput, all_fields=True, description="Definition of an evidence requirement for relation materialization")
class EvidenceRequirementInput:
    """Evidence requirement for relation materialization."""

    key: strawberry.auto
    unit: strawberry.auto
    description: strawberry.auto


@pydantic.input(model=input_models.MaterializationConfigInput, all_fields=True, description="Configuration for relation materialization from evidence")
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


@pydantic.input(model=input_models.RelationDefinitionInput, all_fields=True, description="Definition of a relation type in the graph schema")
class RelationDefinitionInput:
    """Definition of a relation type in the graph schema."""


@pydantic.input(model=input_models.EventDefinitionInput, all_fields=True, description="Definition of an event type in the graph schema")
class EventDefinitionInput:
    """Definition of an event type in the graph schema."""


@pydantic.input(model=input_models.PrefixInput)
class PrefixInput:
    """Prefix definition for namespacing in the graph schema."""

    prefix: strawberry.auto
    uri: strawberry.auto


# ==========================================
# SCHEMA MANAGEMENT INPUT TYPES
# ==========================================


# ==========================================
# FILTER INPUT TYPES
# ==========================================


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


@pydantic.input(model=input_models.SequenceInput, all_fields=True, description="Input for creating a new graph from a schema definition")
class SequenceInput:
    pass


@pydantic.input(model=input_models.GraphTableQueryInput, all_fields=True, description="Input for creating a new graph from a schema definition")
class GraphTableQueryInput:
    pass


@pydantic.input(model=input_models.ColumnInput, all_fields=True, description="Input for a graph table query column")
class ColumnInput:
    pass


@pydantic.input(model=input_models.MatchPathInput, all_fields=True, description="Input for a graph match path")
class MatchPathInput:
    pass


@pydantic.input(model=input_models.WhereClauseInput, all_fields=True, description="Input for a where clause in a graph table query builder")
class WhereClauseInput:
    pass


@pydantic.input(model=input_models.ReturnStatementInput, all_fields=True, description="Input for a return statement in a graph table query builder")
class ReturnStatementInput:
    pass


@pydantic.input(model=input_models.BuilderArgsInput, all_fields=True, description="Builder arguments for generating a graph table query")
class BuilderArgsInput:
    pass


@pydantic.input(model=input_models.CreateGraphTableQueryThroughBuilderInput, all_fields=True, description="Input for creating a graph table query through builder arguments")
class CreateGraphTableQueryThroughBuilderInput:
    pass


@pydantic.input(model=input_models.CreateGraphTableQueryInput, all_fields=True, description="Input for creating a new graph table query")
class CreateGraphTableQueryInput:
    pass


@pydantic.input(model=input_models.UpdateGraphTableQueryInput, all_fields=True, description="Input for updating a graph table query through builder arguments")
class UpdateGraphTableQueryInput:
    pass


@pydantic.input(model=input_models.DeleteGraphTableQueryInput, all_fields=True, description="Input for deleting a graph table query")
class DeleteGraphTableQueryInput:
    id: strawberry.ID = strawberry.field(description="The ID of the graph table query to delete")
    pass


@pydantic.input(model=input_models.ArchiveGraphTableQueryInput, all_fields=True, description="Input for archiving a graph table query")
class ArchiveGraphTableQueryInput:
    id: strawberry.ID = strawberry.field(description="The ID of the graph table query to archive")


@pydantic.input(model=input_models.BuildGraphTableQueryInput, all_fields=True, description="Input for building a graph table query from builder arguments")
class BuildGraphTableQueryInput:
    pass


@pydantic.input(model=input_models.ScatterPlotInput, all_fields=True, description="Input for creating a new graph from a schema definition")
class ScatterPlotInput:
    pass


@pydantic.input(model=input_models.GraphExtensionsInput, all_fields=True, description="Input for creating a new graph from a schema definition")
class GraphExtensionsInput:
    pass


@pydantic.input(model=input_models.ActionFilterInput, all_fields=True, description="Simple boolean filter over request context for action rules")
class ActionFilterInput:
    pass


@pydantic.input(model=input_models.ActionRuleInput, all_fields=True, description="Allow/deny rule for a graph action")
class ActionRuleInput:
    pass


@pydantic.input(model=input_models.GraphDefinitionInput, all_fields=True, description="Input for creating a new graph from a schema definition")
class GraphDefinitionInput:
    pass


@pydantic.input(model=input_models.CreateGraphFromSchema, all_fields=True, description="Input for creating a new graph from a schema definition")
class CreateGraphInput:
    pass


@pydantic.input(model=input_models.DeleteGraphInput, all_fields=True, description="Input for deleting a graph")
class DeleteGraphInput:
    pass


@pydantic.input(model=input_models.ArchiveGraphInput, all_fields=True, description="Input for archiving a graph")
class ArchiveGraphInput:
    pass


@pydantic.input(model=input_models.PinGraphInput, all_fields=True, description="Input for pinning a graph")
class PinGraphInput:
    pass


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
