"""
Root Mutation type for the API.

Assembles all mutation resolvers into the root Mutation type.
"""
from kante.types import Info

from api.types import (
    Entity, Structure, Measurement, EntityCreationResult, 
    LinkStructureResult, RelationCreationResult, SchemaValidationResult, SetSchemaResult,
)
from api.inputs import (
    EntityCreationInput,
    RecalculateEntityInput,
    StructureCreationInput,
    AddMeasurementInput,
    LinkStructureInput,
    RelationCreationInput,
    ValidateSchemaInput,
    SetSchemaInput,
    ActivateSchemaInput,
)
from . import entity as entity_mutations
from . import structure as structure_mutations
from . import metric as measurement_mutations
from . import relation as relation_mutations
from . import schema as schema_mutations
import kante

@kante.type(description="Graph Engine Mutations")
class Mutation:
    """Root mutation type for the graph engine API."""

    @kante.django_mutation(description="Create a new entity with supporting evidence")
    def create_entity(
        self,
        info: Info,
        input: EntityCreationInput,
    ) -> EntityCreationResult:
        """
        Create a new entity with optional supporting evidence structures.
        
        Properties are automatically derived from the evidence according to
        the graph schema rules. Provenance (subject, app_id) is automatically
        derived from the authenticated request context.
        """
        return entity_mutations.create_entity(info, input)

    @kante.django_mutation(description="Recalculate entity properties from its evidence")
    def recalculate_entity(
        self,
        info: Info,
        input: RecalculateEntityInput,
    ) -> Entity:
        """
        Force recalculation of an entity's derived properties.
        
        This is useful after batch linking operations where
        recalculate was set to False.
        """
        return entity_mutations.recalculate_entity(info, input)

    @kante.django_mutation(description="Create a new standalone structure")
    def create_structure(
        self,
        info: Info,
        input: StructureCreationInput,
    ) -> Structure:
        """
        Create a new structure (or return existing if already exists).
        
        Structures are idempotent - creating the same structure twice
        returns the existing one.
        """
        return structure_mutations.create_structure(info, input)

    @kante.django_mutation(description="Add a measurement to a structure")
    def add_measurement(
        self,
        info: Info,
        input: AddMeasurementInput,
    ) -> Measurement:
        """
        Add a measurement to an existing structure.
        
        If the structure doesn't exist, it will be created automatically.
        """
        return measurement_mutations.add_measurement(info, input)

    @kante.django_mutation(description="Link an existing structure to an entity")
    def link_structure_to_entity(
        self,
        info: Info,
        input: LinkStructureInput,
    ) -> LinkStructureResult:
        """
        Link an existing structure to an existing entity.
        
        This creates an INFORMS relationship, allowing the structure's
        measurements to contribute to the entity's derived properties.
        
        By default, entity properties are recalculated after linking.
        Set recalculate=False for batch operations.
        """
        return structure_mutations.link_structure_to_entity(info, input)

    @kante.django_mutation(description="Create a new relation between two entities")
    def create_relation(
        self,
        info: Info,
        input: RelationCreationInput,
    ) -> RelationCreationResult:
        """
        Create a new relation between two entities with optional supporting evidence.
        
        Relations are edges between entities that can be backed by evidence
        (e.g., ROI overlaps that prove a synapse connection). Properties on
        the relation are automatically derived from the evidence according
        to the graph schema's materialization rules.
        
        A relation between the same source and target (in the same direction)
        will use MERGE semantics - adding more evidence will update the
        existing relation's materialized properties.
        """
        return relation_mutations.create_relation(info, input)

    # ===========================================
    # SCHEMA MUTATIONS
    # ===========================================

    @kante.django_mutation(description="Validate a schema definition without saving")
    def validate_schema(
        self,
        info: Info,
        input: ValidateSchemaInput,
    ) -> SchemaValidationResult:
        """
        Validate a schema definition and return pydantic-style errors.
        
        Use this to check a schema before committing it. This does not
        save the schema to the database.
        """
        return schema_mutations.validate_schema(info, input)

    @kante.django_mutation(description="Create and optionally activate a new schema version")
    def set_schema(
        self,
        info: Info,
        input: SetSchemaInput,
    ) -> SetSchemaResult:
        """
        Create a new schema version for the current graph.
        
        The schema is validated before saving. By default, if no active
        schema exists, the new schema becomes active. Use activate=True
        to always activate, or activate=False to create without activating.
        """
        return schema_mutations.set_schema(info, input)

    @kante.django_mutation(description="Activate an existing schema version")
    def activate_schema(
        self,
        info: Info,
        input: ActivateSchemaInput,
    ) -> SetSchemaResult:
        """
        Make a specific schema version the active one for its graph.
        
        All previously active schemas for the same graph are deactivated.
        """
        return schema_mutations.activate_schema(info, input)
