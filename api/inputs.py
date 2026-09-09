"""
GraphQL Input types for the API using strawberry-pydantic.

These inputs use strawberry.experimental.pydantic to automatically
validate against the Pydantic input models from graph_engine.
"""

import strawberry
from strawberry.scalars import JSON
from datetime import datetime
from typing import Optional, List

from core import enums
from graph_engine import input_models
from graph_engine.scalars import AnyScalar
from strawberry.experimental import pydantic
from typing import Annotated


@pydantic.input(model=input_models.CategoryNodePositionInput, all_fields=True, description="Input for specifying the position of a node in the graph visualization")
class CategoryNodePositionInput:
    """Input for specifying the position of a node in the graph visualization. This can be used to set or update the x and y coordinates of a node for layout purposes."""

    pass


@pydantic.input(model=input_models.UpdateGraphVisuals, all_fields=True, description="Input for updating the visual properties of a graph element")
class UpdateGraphVisualInput:
    """Input for updating the visual properties of a graph element, such as a node or edge. This can include properties like color, size, shape, etc. The specific visual properties that can be updated will depend on the implementation of the graph rendering on the frontend."""

    pass


@pydantic.input(model=input_models.MetricInput, description="One measured value about a structure")
class MetricInput:
    key: str = strawberry.field(description="The key/name of the metric")
    value: AnyScalar = strawberry.field(description="The value of the metric, which can be any scalar type (string, number, boolean)")
    # Non-null, and before the defaulted fields — a field without a default
    # cannot follow one that has it. Nothing infers this: it decides both the
    # column the value lands in and the term the measurement is recorded under.
    value_kind: input_models.PropertyType = strawberry.field(description="What type of value this is. Required — it decides the storage column and the measurement term")
    unit: Optional[str] = strawberry.field(default=None, description="Unit of measurement, e.g. 'um'")
    confidence: Optional[float] = strawberry.field(default=None, description=input_models.CONFIDENCE_FIELD_DESCRIPTION)
    confidence_type: Optional[str] = strawberry.field(default=None, description="What kind of number `confidence` is — a method's own score, a p-value. Measurement-only")
    observed_at: Optional[datetime] = strawberry.field(default=None, description=input_models.OBSERVED_AT_FIELD_DESCRIPTION)
    derived_from: List[str] = strawberry.field(default_factory=list, description=input_models.DERIVED_FROM_FIELD_DESCRIPTION)


@pydantic.input(model=input_models.ClaimConditionInput, all_fields=True, description="One condition: (field, operator, value) — IS/IN/NOT_IN on WORD/SUBJECT/APP/ACTION/KIND/KEY, BEFORE/SINCE on ASSERTED_AT/OBSERVED_AT, AT_LEAST/BELOW on CONFIDENCE (RFC 0010, 0015, 0016)")
class ClaimConditionInput:
    """One (field, operator, value) condition."""

    value: AnyScalar = strawberry.field(description="One string for IS, a string list for IN/NOT_IN, an ISO datetime for BEFORE/SINCE. For field KIND: one of CLASSIFICATION, EXISTENCE, SAMENESS, EVIDENCE, MEASUREMENT")


@pydantic.input(model=input_models.ClaimConditionGroupInput, all_fields=True, description="An exception: a conjunction that, when it holds whole, blocks its rule")
class ClaimConditionGroupInput:
    """One exception group."""

    pass


@pydantic.input(model=input_models.ClaimRuleInput, all_fields=True, description="One rule: matches when all `when` conditions hold and no `unless` group does")
class ClaimRuleInput:
    """One rule."""

    pass


@pydantic.input(model=input_models.CategoryDefinitionInput, all_fields=True, description="What a category means: a union of clauses over classification claims — flat form for one clause, anyOf for several, never both (RFC 0007)")
class CategoryDefinitionInput:
    """A category's meaning, as a predicate over claims."""

    pass


# `GraphSelectorInput` is gone (RFC 0009): trust lives in the category
# definitions and in `rule.evidence`, so a graph has no claim scope of its own.


@pydantic.input(model=input_models.MetricEvidenceInput, all_fields=True, description="A property's own metric rule: the definition's rule list over metric rows — no WORD or KIND, KEY allowed anywhere")
class MetricEvidenceInput:
    """A property's own metric rule (RFC 0014)."""

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
@pydantic.input(model=input_models.RenderGraphTableFilter, all_fields=True, description="A render-time filter on one returned alias of a saved table query")
class RenderGraphTableFilter:
    value: JSON = strawberry.field(description="The value to compare against; bound as a parameter")


@pydantic.input(model=input_models.RenderGraphTablePagination, all_fields=True, description="Pagination options for querying node lists")
class RenderGraphTablePagination:
    pass


@pydantic.input(model=input_models.RenderGraphTableOrder, all_fields=True, description="Ordering options for querying node lists")
class RenderGraphTableOrder:
    pass


# ==========================================
# Schema Creation Input Types
# ==========================================


@pydantic.input(model=input_models.StructureReferenceInput, all_fields=True, description="A reference to a structure by identifier and object")
class StructureReferenceInput:
    pass


@pydantic.input(model=input_models.RoleMappingInput, all_fields=True, description="How a participant maps onto a declared event role")
class RoleMappingInput:
    pass


@pydantic.input(model=input_models.OntologyReferenceInput, all_fields=True, description="A reference to a published ontology term")
class OntologyReferenceInput:
    pass


@pydantic.input(model=input_models.EntityDescriptorInput, all_fields=True, description="Filters that select which entity categories a descriptor matches")
class EntityDescriptorInput:
    # The pydantic field was spelled `ontotology_terms` — with an extra `to` — so
    # `all_fields=True` put `ontotologyTerms` in the schema. A hand-written
    # `ontology_terms` was declared here alongside it, which read correctly and
    # did nothing: `to_pydantic()` builds its kwargs from the *model's* fields,
    # so anything sent under the correct spelling was dropped on the floor. The
    # model is spelled correctly now and this override is unnecessary.
    keys: List[str] | None = strawberry.field(default=None, description="The list of keys/identifiers that define this entity descriptor")


@pydantic.input(model=input_models.EventRoleInput, all_fields=True, description="One declared role on an event category")
class EventRoleInput:
    pass


@pydantic.input(model=input_models.StructureDefinitionInput, all_fields=True, description="Definition of a structure type in the graph schema")
class StructureDefinitionInput:
    """Definition of a structure type in the graph schema."""


@pydantic.input(model=input_models.CreateNaturalEventCategoryInput, all_fields=True, description="Input for creating a new natural event definition in the graph schema")
class CreateNaturalEventCategoryInput:
    pass


@pydantic.input(model=input_models.UpdateNaturalEventCategoryInput, all_fields=True, description="Input for updating an existing natural event definition in the graph schema")
class UpdateNaturalEventCategoryInput:
    pass


@pydantic.input(model=input_models.DeleteNaturalEventCategoryInput, all_fields=True, description="Input for deleting an existing natural event definition in the graph schema")
class DeleteNaturalEventCategoryInput:
    pass


@pydantic.input(model=input_models.CreateProtocolEventCategoryInput, all_fields=True, description="Input for creating a new protocol event definition in the graph schema")
class CreateProtocolEventCategoryInput:
    pass


@pydantic.input(model=input_models.UpdateProtocolEventCategoryInput, all_fields=True, description="Input for updating an existing protocol event definition in the graph schema")
class UpdateProtocolEventCategoryInput:
    pass


@pydantic.input(model=input_models.DeleteProtocolEventCategoryInput, all_fields=True, description="Input for deleting an existing protocol event definition in the graph schema")
class DeleteProtocolEventCategoryInput:
    pass


# ==========================================
# Node Creation Input Types
# ==========================================


@pydantic.input(model=input_models.CreateEntityCategoryInput, all_fields=True, description="Input for creating a new entity definition in the graph schema")
class CreateEntityCategoryInput:
    """Input for creating a new entity definition in the graph schema."""

    pass


@pydantic.input(model=input_models.UpdateEntityCategoryInput, all_fields=True, description="Input for updating an existing entity definition in the graph schema")
class UpdateEntityCategoryInput:
    id: strawberry.ID = strawberry.field(description="The ID of the entity definition to update")
    """Input for updating an existing entity definition in the graph schema."""

    pass


@pydantic.input(model=input_models.DeleteEntityCategoryInput, all_fields=True, description="Input for deleting an existing entity definition in the graph schema")
class DeleteEntityCategoryInput:
    id: strawberry.ID = strawberry.field(description="The ID of the entity definition to delete")
    """Input for deleting an existing entity definition in the graph schema."""

    pass


@pydantic.input(model=input_models.StructureDescriptorInput, all_fields=True, description="Input for creating a new structure relation definition in the graph schema")
class StructureDescriptorInput:
    """Input for creating a new structure relation definition in the graph schema."""

    identifiers: List[str] | None = strawberry.field(default=None, description="The list of ontology terms associated with this entity descriptor")

    pass


@pydantic.input(model=input_models.CreateStructureRelationCategoryInput, all_fields=True, description="Input for creating a new structure relation definition in the graph schema")
class CreateStructureRelationCategoryInput:
    """Input for creating a new structure relation definition in the graph schema."""

    pass


@pydantic.input(model=input_models.UpdateStructureRelationCategoryInput, all_fields=True, description="Input for updating an existing structure relation definition in the graph schema")
class UpdateStructureRelationCategoryInput:
    """Input for updating an existing structure relation definition in the graph schema."""

    pass


@pydantic.input(model=input_models.DeleteStructureRelationCategoryInput, all_fields=True, description="Input for deleting an existing structure relation definition in the graph schema")
class DeleteStructureRelationCategoryInput:
    """Input for deleting an existing structure relation definition in the graph schema."""

    pass


@pydantic.input(model=input_models.CreateTermInput, all_fields=True, description="Input for declaring one of the organization's words")
class CreateTermInput:
    """Input for declaring one of the organization's words."""


@pydantic.input(model=input_models.UpdateTermInput, all_fields=True, description="Input for editing how one of the organization's words presents itself")
class UpdateTermInput:
    """Input for editing how one of the organization's words presents itself."""


@pydantic.input(model=input_models.DeleteTermInput, all_fields=True, description="Input for retiring one of the organization's words")
class DeleteTermInput:
    """Input for retiring one of the organization's words."""


@pydantic.input(model=input_models.UpdateStructureKindInput, all_fields=True, description="Input for updating an existing structure definition in the graph schema")
class UpdateStructureKindInput:
    """Input for updating an existing structure definition in the graph schema."""

    pass


@pydantic.input(model=input_models.DeleteStructureKindInput, all_fields=True, description="Input for deleting an existing structure definition in the graph schema")
class DeleteStructureKindInput:
    """Input for deleting an existing structure definition in the graph schema."""

    pass


@pydantic.input(model=input_models.UpdateMetricKindInput, all_fields=True, description="Input for updating an existing metric definition in the graph schema")
class UpdateMetricKindInput:
    """Input for updating an existing metric definition in the graph schema."""

    pass


@pydantic.input(model=input_models.DeleteMetricKindInput, all_fields=True, description="Input for deleting an existing metric definition in the graph schema")
class DeleteMetricKindInput:
    """Input for deleting an existing metric definition in the graph schema."""

    pass


@pydantic.input(model=input_models.CreateRelationCategoryInput, all_fields=True, description="Input for creating a new relation definition in the graph schema")
class CreateRelationCategoryInput:
    """Input for creating a new relation definition in the graph schema."""

    pass


@pydantic.input(model=input_models.UpdateRelationCategoryInput, all_fields=True, description="Input for updating an existing relation definition in the graph schema")
class UpdateRelationCategoryInput:
    """Input for updating an existing relation definition in the graph schema."""

    pass


@pydantic.input(model=input_models.DeleteRelationCategoryInput, all_fields=True, description="Input for deleting an existing relation definition in the graph schema")
class DeleteRelationCategoryInput:
    """Input for deleting an existing relation definition in the graph schema."""

    pass


@pydantic.input(model=input_models.CreateMeasurementCategoryInput, all_fields=True, description="Input for creating a new measurement definition in the graph schema")
class CreateMeasurementCategoryInput:
    """Input for creating a new measurement definition in the graph schema."""

    pass


@pydantic.input(model=input_models.UpdateMeasurementCategoryInput, all_fields=True, description="Input for updating an existing measurement definition in the graph schema")
class UpdateMeasurementCategoryInput:
    """Input for updating an existing measurement definition in the graph schema."""

    pass


@pydantic.input(model=input_models.DeleteMeasurementCategoryInput, all_fields=True, description="Input for deleting an existing measurement definition in the graph schema")
class DeleteMeasurementCategoryInput:
    """Input for deleting an existing measurement definition in the graph schema."""

    pass


@pydantic.input(model=input_models.AssertNaturalEventExistsInput, all_fields=True, description="Input for creating a new natural event instance")
class AssertNaturalEventExistsInput:
    """Input for creating a new natural event instance."""

    pass


@pydantic.input(model=input_models.AssertParticipationInput, all_fields=True, description="Input for claiming that an entity took part in an event")
class AssertParticipationInput:
    pass


@pydantic.input(model=input_models.RetractParticipationInput, all_fields=True, description="Input for retracting one participation claim")
class RetractParticipationInput:
    pass


@pydantic.input(model=input_models.ParticipantInput, all_fields=True, description="One entity's part in an event, inside a batch")
class ParticipantInput:
    pass


@pydantic.input(model=input_models.AssertParticipationsInput, all_fields=True, description="Input for claiming that several entities took part in one event, as one act")
class AssertParticipationsInput:
    pass


@pydantic.input(model=input_models.ClassificationInput, all_fields=True, description="One claim that a node is of a word, inside a batch")
class ClassificationInput:
    pass


@pydantic.input(model=input_models.ClassifyNodesInput, all_fields=True, description="Input for claiming that several nodes are of a word, as one act")
class ClassifyNodesInput:
    pass


@pydantic.input(model=input_models.RetractLinksInput, all_fields=True, description="Input for retracting several link claims as one act")
class RetractLinksInput:
    pass


@pydantic.input(model=input_models.DescendantNode, description="One node of a comment's rich body — shape-compatible with lok's komment descendants")
class DescendantInput:
    """Recursive by hand, the way lok declares it: strawberry cannot derive a
    self-referential field, so `children` is annotated lazily. A MENTION's `user`
    is a subject id — `Assertion.subject`'s vocabulary — not a user row."""

    kind: enums.DescendantKind = strawberry.field(description="LEAF, MENTION or PARAGRAPH")
    children: Optional[List[Annotated["DescendantInput", strawberry.lazy(__name__)]]] = strawberry.field(default=None, description="The children of this node. Always empty for leafs")
    text: Optional[str] = strawberry.field(default=None, description="The text of a leaf")
    bold: Optional[bool] = strawberry.field(default=None, description="Render a leaf bold")
    italic: Optional[bool] = strawberry.field(default=None, description="Render a leaf italic")
    underline: Optional[bool] = strawberry.field(default=None, description="Render a leaf underlined")
    code: Optional[bool] = strawberry.field(default=None, description="Render a leaf as code")
    user: Optional[str] = strawberry.field(default=None, description="The mentioned subject id, for MENTION nodes")
    size: Optional[str] = strawberry.field(default=None, description="The size of a paragraph")


@pydantic.input(model=input_models.CommentOnStructureInput, description="Input for remarking on an external datum, minting its structure if new")
class CommentOnStructureInput:
    """Input for commenting on a structure — the datum named by `(identifier, object)`, as lok names it."""

    identifier: str = strawberry.field(description="The structure identifier of the datum, e.g. '@mikro/roi'")
    object: str = strawberry.field(description="The id of the external object on its service")
    descendants: List[DescendantInput] = strawberry.field(description="The rich body of the remark")
    parent: Optional[strawberry.ID] = strawberry.field(default=None, description="The comment this replies to. Must be on the same structure's thread")


@pydantic.input(model=input_models.RetractCommentInput, all_fields=True, description="Input for claiming a remark no longer stands — withdrawn or resolved; the assertion records whose position it is")
class RetractCommentInput:
    pass


@pydantic.input(model=input_models.AttestCommentInput, all_fields=True, description="Input for claiming a remark stands again — reopening, as new evidence")
class AttestCommentInput:
    pass


@pydantic.input(model=input_models.RetractNaturalEventInput, all_fields=True, description="Input for retracting a natural event claim — a Standing(stands=false), not a deletion")
class RetractNaturalEventInput:
    """Input for retracting a natural event claim."""

    pass


@pydantic.input(model=input_models.AssertProtocolEventExistsInput, all_fields=True, description="Input for creating a new protocol event instance")
class AssertProtocolEventExistsInput:
    """Input for creating a new protocol event instance."""

    pass


@pydantic.input(model=input_models.RetractProtocolEventInput, all_fields=True, description="Input for retracting a protocol event claim — a Standing(stands=false), not a deletion")
class RetractProtocolEventInput:
    """Input for retracting a protocol event claim."""

    pass


@pydantic.input(model=input_models.CreateScatterPlotInput, all_fields=True, description="Input for creating a scatter plot")
class CreateScatterPlotInput:
    """Input for creating a scatter plot."""

    pass


@pydantic.input(model=input_models.UpdateScatterPlotInput, all_fields=True, description="Input for updating a scatter plot")
class UpdateScatterPlotInput:
    """Input for updating a scatter plot."""

    pass


@pydantic.input(model=input_models.DeleteScatterPlotInput, all_fields=True, description="Input for deleting a scatter plot")
class DeleteScatterPlotInput:
    """Input for deleting a scatter plot."""

    pass


@pydantic.input(model=input_models.AssertMetricValueInput, description="Input for creating a new metric")
class AssertMetricValueInput(MetricInput):
    """Input for creating a new metric."""

    identifier: str = strawberry.field(description="The schema identifier for this metric (e.g. '@mikro/roi_volume')")
    object: str = strawberry.field(description="The unique ID of the object this metric references")
    # `value_kind` is inherited. It used to be re-declared here because this was
    # the only input that had one; it is now on every measurement input.
    value: AnyScalar = strawberry.field(description="The value of the metric, which can be any scalar type (string, number, boolean)")


@pydantic.input(model=input_models.AssertMetricValueForStructureInput, description="Input for creating a new metric")
class AssertMetricValueForStructureInput(MetricInput):
    """Input for creating a new metric."""

    key: str = strawberry.field(description="The key/name of the metric")
    value: AnyScalar = strawberry.field(description="The value of the metric, which can be any scalar type (string, number, boolean)")
    structure: strawberry.ID = strawberry.field(description="The ID of the structure this metric will be attached to — a bare uuid, its evidence primary key")
    pass

    pass


@pydantic.input(model=input_models.SupersedeMetricValueInput, description="Input for superseding a metric value")
class SupersedeMetricValueInput(MetricInput):
    """Input for superseding a metric value: a Standing(stands=false) on the old metric and a new metric, under one assertion — both stay on the record."""

    id: str = strawberry.field(description="The ID of the metric to supersede")
    key: str = strawberry.field(description="The key/name of the metric")
    value: AnyScalar = strawberry.field(description="The value of the metric, which can be any scalar type (string, number, boolean)")
    pass


@pydantic.input(model=input_models.RetractMetricInput, all_fields=True, description="Input for retracting a metric claim — a Standing(stands=false), not a deletion")
class RetractMetricInput:
    """Input for retracting a metric claim."""

    pass


@pydantic.input(model=input_models.AssertStructureExistsInput, all_fields=True, description="Input for claiming that an external datum exists")
class AssertStructureExistsInput:
    """Input for creating a new structure."""

    pass


@pydantic.input(model=input_models.EnsureStructureInput, all_fields=True, description="Input for getting the structure for an external datum, creating it if new")
class EnsureStructureInput:
    """Input for creating a new structure."""

    pass


@pydantic.input(model=input_models.UpdateStructureInput, all_fields=True, description="Input for updating an existing structure")
class UpdateStructureInput:
    """Input for updating an existing structure."""

    pass


@pydantic.input(model=input_models.RetractStructureInput, description="Input for retracting a structure claim — a Standing(stands=false), not a deletion")
class RetractStructureInput:
    """Input for retracting a structure claim."""

    id: strawberry.ID = strawberry.field(description="The ID of the structure to retract — a bare uuid, its evidence primary key")
    at: Optional[datetime] = strawberry.field(default=None, description=input_models.STANDING_AT_FIELD_DESCRIPTION)
    confidence: Optional[float] = strawberry.field(default=None, description=input_models.CONFIDENCE_FIELD_DESCRIPTION)


@pydantic.input(model=input_models.AssertRelationExistsInput, all_fields=True, description="Input for creating a new relation between two entities with supporting evidence")
class AssertRelationExistsInput:
    """Input for creating a new relation."""

    pass


@pydantic.input(model=input_models.RetractRelationInput, description="Input for retracting a relation claim — a Standing(stands=false), not a deletion")
class RetractRelationInput:
    """Input for retracting a relation claim."""

    id: strawberry.ID = strawberry.field(description="The ID of the relation claim to retract — its `Link` primary key")
    at: Optional[datetime] = strawberry.field(default=None, description=input_models.STANDING_AT_FIELD_DESCRIPTION)
    confidence: Optional[float] = strawberry.field(default=None, description=input_models.CONFIDENCE_FIELD_DESCRIPTION)


@pydantic.input(model=input_models.UpdateRelationInput, all_fields=True, description="Input for updating an existing relation")
class UpdateRelationInput:
    """Input for updating an existing relation."""

    pass


@pydantic.input(model=input_models.AssertStructureRelationExistsInput, all_fields=True, description="Input for creating a new structure relation")
class AssertStructureRelationExistsInput:
    """Input for creating a new structure relation."""

    pass


@pydantic.input(model=input_models.UpdateStructureRelationInput, all_fields=True, description="Input for updating an existing structure relation")
class UpdateStructureRelationInput:
    """Input for updating an existing structure relation."""

    pass


@pydantic.input(model=input_models.RetractStructureRelationInput, all_fields=True, description="Input for retracting a structure relation claim — a Standing(stands=false), not a deletion")
class RetractStructureRelationInput:
    """Input for retracting a structure relation claim."""

    pass


@pydantic.input(model=input_models.AssertMeasurementExistsInput, all_fields=True, description="Input for creating a new measurement edge")
class AssertMeasurementExistsInput:
    """Input for creating a new measurement edge."""

    pass


@pydantic.input(model=input_models.RetractMeasurementInput, all_fields=True, description="Input for retracting a measurement claim — a Standing(stands=false), not a deletion")
class RetractMeasurementInput:
    """Input for retracting a measurement claim."""

    pass


@pydantic.input(model=input_models.AssertEntityExistsInput, all_fields=True, description="Input for creating a new entity")
class AssertEntityExistsInput:
    pass


@pydantic.input(model=input_models.AssertSameInstanceInput, all_fields=True, description="Input for claiming that several recorded instances are one thing")
class AssertSameInstanceInput:
    """Input for claiming that several recorded instances are one thing."""

    pass


@pydantic.input(model=input_models.RetractSameInstanceInput, all_fields=True, description="Input for withdrawing one sameness claim")
class RetractSameInstanceInput:
    """Input for withdrawing one sameness claim."""

    pass


@pydantic.input(model=input_models.AssertDifferentInstanceInput, all_fields=True, description="Input for claiming that several recorded instances are distinct things (RFC 0019)")
class AssertDifferentInstanceInput:
    """Input for claiming that several recorded instances are distinct things."""

    pass


@pydantic.input(model=input_models.RetractDifferentInstanceInput, all_fields=True, description="Input for withdrawing one difference claim")
class RetractDifferentInstanceInput:
    """Input for withdrawing one difference claim."""

    pass


@pydantic.input(model=input_models.RetractEntityInput, description="Input for retracting an entity claim")
class RetractEntityInput:
    """Input for retracting an entity claim."""

    id: strawberry.ID = strawberry.field(description="The ID of the entity to retract")
    at: Optional[datetime] = strawberry.field(default=None, description=input_models.STANDING_AT_FIELD_DESCRIPTION)
    confidence: Optional[float] = strawberry.field(default=None, description=input_models.CONFIDENCE_FIELD_DESCRIPTION)


@pydantic.input(model=input_models.AttestStructureInput, all_fields=True, description="Input for claiming that a structure still stands")
class AttestStructureInput:
    """Input for attesting a structure."""


@pydantic.input(model=input_models.AttestMetricInput, all_fields=True, description="Input for claiming that a measurement still stands")
class AttestMetricInput:
    """Input for attesting a metric."""


@pydantic.input(model=input_models.AttestLinkInput, all_fields=True, description="Input for claiming that a link claim still stands")
class AttestLinkInput:
    """Input for attesting a link claim of any kind."""


@pydantic.input(model=input_models.AttestEntityInput, all_fields=True, description="Input for claiming that an entity exists")
class AttestEntityInput:
    """Input for claiming that an entity exists."""


@pydantic.input(model=input_models.AttestNaturalEventInput, all_fields=True, description="Input for claiming that a natural event exists")
class AttestNaturalEventInput:
    """Input for claiming that a natural event exists."""


@pydantic.input(model=input_models.AttestProtocolEventInput, all_fields=True, description="Input for claiming that a protocol event exists")
class AttestProtocolEventInput:
    """Input for claiming that a protocol event exists."""


# `RecalculateEntityInput` used to sit here, with an `id` documented as "the ID of
# the graph containing the entity". No resolver referenced it — the mutation it
# belonged to was removed when derivation moved to the projector — and its shape
# said the opposite of what identity now means: a node id names the node, and a
# graph is not part of it.


# ==========================================
# ADDITIONAL INPUT TYPES (not in input_models)
# ==========================================


@strawberry.input(description="Input for linking a structure to an entity")
class LinkStructureInput:
    """Input for asserting that a structure is evidence for an entity.

    Identified by `(identifier, object)` rather than by primary key, because that
    pair is what a caller naturally has — the ROI they just analysed — and it is
    the structure's identity within the organization anyway.

    The old `recalculate` flag is gone: linking records a claim, and deciding
    which entities need re-deriving as a result is the projector's job (M3), not
    something a client should be toggling per call.
    """

    structure_identifier: str = strawberry.field(description="Structure identifier, e.g. '@mikro/roi'")
    structure_object: str = strawberry.field(description="Structure object ID")
    entity_id: str = strawberry.field(description="The ID of the entity this structure informs — a bare uuid")


@pydantic.input(model=input_models.EntityDefinitionInput, all_fields=True, description="Definition of an entity type in the graph schema")
class EntityDefinitionInput:
    """Definition of an entity type in the graph schema."""


@pydantic.input(model=input_models.RelationDefinitionInput, all_fields=True, description="Definition of a relation type in the graph schema")
class RelationDefinitionInput:
    """Definition of a relation type in the graph schema."""


@pydantic.input(model=input_models.EventDefinitionInput, all_fields=True, description="Definition of an event type in the graph schema")
class EventDefinitionInput:
    """Definition of an event type in the graph schema."""


@pydantic.input(model=input_models.ColumnInput, all_fields=True, description="Input for a graph table query column")
class ColumnInput:
    pass


@pydantic.input(model=input_models.MatchPathInput, all_fields=True, description="Input for a graph match path")
class MatchPathInput:
    pass


@pydantic.input(model=input_models.WhereClauseInput, all_fields=True, description="Input for a where clause in a graph table query builder")
class WhereClauseInput:
    # A JSON value — number, string, boolean, list — bound as a parameter.
    value: JSON = strawberry.field(description="The value to compare against. Bound as a parameter, never a Cypher literal")


@pydantic.input(model=input_models.ReturnStatementInput, all_fields=True, description="Input for a return statement in a graph table query builder")
class ReturnStatementInput:
    pass


@pydantic.input(model=input_models.TableQueryPlanInput, all_fields=True, description="What a saved table query means: matches, wheres, returns. Compiled per projection kind")
class TableQueryPlanInput:
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


@pydantic.input(model=input_models.MeasurementDefinitionInput, all_fields=True, description="Declares a measurement category in a graph schema")
class MeasurementDefinitionInput:
    pass


@pydantic.input(model=input_models.StructureRelationDefinitionInput, all_fields=True, description="Declares a structure relation category in a graph schema")
class StructureRelationDefinitionInput:
    pass


@pydantic.input(model=input_models.GraphExtensionsInput, all_fields=True, description="The categories a graph schema declares")
class GraphExtensionsInput:
    pass


@pydantic.input(model=input_models.GraphDefinitionInput, all_fields=True, description="A complete graph schema definition")
class GraphDefinitionInput:
    pass


@pydantic.input(model=input_models.CreateGraphFromSchema, all_fields=True, description="Input for creating a new graph from a schema definition")
class CreateGraphInput:
    pass


@pydantic.input(model=input_models.UpdateGraphInput, all_fields=True, description="Input for updating an existing graph")
class UpdateGraphInput:
    pass


@pydantic.input(model=input_models.DeleteGraphInput, all_fields=True, description="Input for deleting a graph")
class DeleteGraphInput:
    pass


@pydantic.input(model=input_models.ArchiveGraphInput, all_fields=True, description="Input for archiving a graph")
class ArchiveGraphInput:
    pass
