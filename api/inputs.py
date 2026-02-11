"""
GraphQL Input types for the API using strawberry-pydantic.

These inputs use strawberry.experimental.pydantic to automatically
validate against the Pydantic input models from graph_engine.
"""

import strawberry
import kante
from typing import Optional, List
from enum import Enum

from graph_engine import input_models
from .scalars import AnyScalar
from strawberry.experimental import pydantic


# ==========================================
# Schema Creation Input Types
# ==========================================


@pydantic.input(model=input_models.MetricInput, description="Input for creating a new natural event definition in the graph schema")
class MetricInput:
    key: str = strawberry.field(description="The key/name of the metric")
    value: AnyScalar = strawberry.field(description="The value of the metric, which can be any scalar type (string, number, boolean)")
    pass


@pydantic.input(model=input_models.StructureReferenceInput, all_fields=True, description="Input for creating a new natural event definition in the graph schema")
class StructureReferenceInput:
    pass


@pydantic.input(model=input_models.RoleMappingInput, all_fields=True, description="Input for creating a new natural event definition in the graph schema")
class RoleMappingInput:
    pass


@pydantic.input(model=input_models.DerivationRuleInput, all_fields=True, description="Input for creating a new natural event definition in the graph schema")
class DerivationRuleInput:
    pass


@pydantic.input(model=input_models.OntologyReferenceInput, all_fields=True, description="Input for creating a new natural event definition in the graph schema")
class OntologyReferenceInput:
    pass


@pydantic.input(model=input_models.PropertyDefinitionInput, all_fields=True, description="Input for creating a new natural event definition in the graph schema")
class PropertyDefinitionInput:
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
    """Input for updating an existing entity definition in the graph schema."""

    pass


@pydantic.input(model=input_models.DeleteEntityDefinitionInput, all_fields=True, description="Input for deleting an existing entity definition in the graph schema")
class DeleteEntityDefinitionInput:
    """Input for deleting an existing entity definition in the graph schema."""

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


@pydantic.input(model=input_models.CreateMetricInput, description="Input for creating a new metric")
class CreateMetricInput(MetricInput):
    """Input for creating a new metric."""

    key: str = strawberry.field(description="The key/name of the metric")
    value: AnyScalar = strawberry.field(description="The value of the metric, which can be any scalar type (string, number, boolean)")
    pass

    pass


@pydantic.input(model=input_models.UpdateMetricInput, all_fields=True, description="Input for updating an existing metric")
class UpdateMetricInput:
    """Input for updating an existing metric. Note: this will not update the metric in-place, but rather create a new metric and archive the old one to preserve history."""

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


@pydantic.input(model=input_models.DeleteStructureInput, all_fields=True, description="Input for deleting an existing structure")
class DeleteStructureInput:
    """Input for deleting an existing structure."""

    pass


@pydantic.input(model=input_models.ArchiveStructureInput, all_fields=True, description="Input for deleting an existing structure")
class ArchiveStructureInput:
    """Input for deleting an existing structure."""

    pass


@pydantic.input(model=input_models.CreateRelationInput, all_fields=True, description="Input for creating a new relation between two entities with supporting evidence")
class CreateRelationInput:
    """Input for creating a new relation."""

    pass


@pydantic.input(model=input_models.DeleteRelationInput, all_fields=True, description="Input for deleting an existing relation")
class DeleteRelationInput:
    """Input for deleting an existing relation."""

    pass


@pydantic.input(model=input_models.ArchiveRelationInput, all_fields=True, description="Input for archiving an existing relation")
class ArchiveRelationInput:
    """Input for archiving an existing relation."""

    pass


@pydantic.input(model=input_models.CreateEntityInput, all_fields=True, description="Input for creating a new entity")
class CreateEntityInput:
    pass


@pydantic.input(model=input_models.DeleteEntityInput, description="Input for deleting an existing entity")
class DeleteEntityInput:
    """Input for deleting an existing entity."""

    id: strawberry.ID = strawberry.field(description="The ID of the entity to delete")


@pydantic.input(model=input_models.ArchiveEntityInput, description="Input for recalculating an entity's derived properties")
class ArchiveEntityInput:
    """Input for recalculating an entity's derived properties."""

    id: strawberry.ID = strawberry.field(description="The ID of the entity to recalculate")


@strawberry.input(description="Input for recalculating entity properties")
class RecalculateEntityInput:
    """Input for recalculating an entity's derived properties."""

    graph_id: strawberry.ID = strawberry.field(description="The ID of the graph containing the entity")
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
