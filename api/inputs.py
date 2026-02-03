"""
GraphQL Input types for the API using strawberry-pydantic.

These inputs use strawberry.experimental.pydantic to automatically
validate against the Pydantic input models from graph_engine.
"""
import strawberry
from strawberry.experimental import pydantic
from typing import Optional, List

from graph_engine import input_models
from .scalars import AnyScalar


# ==========================================
# PYDANTIC-VALIDATED INPUT TYPES
# ==========================================

@pydantic.input(model=input_models.MeasurementInput)
class MeasurementInputType:
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


@pydantic.input(model=input_models.StructureReference)
class StructureReferenceInputType:
    """
    Reference to an existing or new structure with optional measurements.
    """
    identifier: strawberry.auto
    object: strawberry.auto
    measurements: Optional[List[MeasurementInputType]] = strawberry.field(default_factory=list)


@pydantic.input(model=input_models.ProvenanceContext)
class ProvenanceInputType:
    """
    Provenance context for tracking who created what and when.
    """
    subject: strawberry.auto
    app_id: strawberry.auto
    action_id: strawberry.auto
    action_name: strawberry.auto
    action_args: Optional[AnyScalar] = None  # Override Dict[str, Any] with our scalar


@pydantic.input(model=input_models.EntityCreationPayload)
class EntityCreationInputType:
    """
    Input for creating a new entity with supporting evidence.
    Validates against EntityCreationPayload Pydantic model.
    """
    ref_id: strawberry.auto
    kind: strawberry.auto
    supporting_evidence: Optional[List[StructureReferenceInputType]] = strawberry.field(default_factory=list)
    provenance: ProvenanceInputType


@pydantic.input(model=input_models.StructureCreationPayload)
class StructureCreationInputType:
    """
    Input for creating a standalone structure.
    Validates against StructureCreationPayload Pydantic model.
    """
    identifier: strawberry.auto
    object: strawberry.auto


# ==========================================
# ADDITIONAL INPUT TYPES (not in input_models)
# ==========================================

@strawberry.input(description="Input for adding a measurement to a structure")
class AddMeasurementInputType:
    """Input for adding a measurement to an existing structure."""
    structure_identifier: str = strawberry.field(description="Structure identifier (e.g. '@mikro/roi')")
    structure_object: str = strawberry.field(description="Structure object ID")
    measurement: MeasurementInputType = strawberry.field(description="The measurement to add")
    provenance: ProvenanceInputType = strawberry.field(description="Provenance context for this measurement")


@strawberry.input(description="Input for linking a structure to an entity")
class LinkStructureInputType:
    """Input for linking an existing structure to an entity."""
    structure_identifier: str = strawberry.field(description="Structure identifier")
    structure_object: str = strawberry.field(description="Structure object ID")
    entity_id: str = strawberry.field(description="Entity ID to link to")
    recalculate: Optional[bool] = strawberry.field(
        default=True, 
        description="Whether to recalculate entity properties after linking"
    )


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
