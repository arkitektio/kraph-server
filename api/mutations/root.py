"""
Root Mutation type for the API.

Assembles all mutation resolvers into the root Mutation type.
"""

from kante.types import Info


from api import inputs, context, types
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
        input: inputs.CreateEntityInput,
    ) -> types.Entity:
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
        input: inputs.RecalculateEntityInput,
    ) -> types.Entity:
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
        input: inputs.CreateStructureInput,
    ) -> types.Structure:
        """
        Create a new structure (or return existing if already exists).

        Structures are idempotent - creating the same structure twice
        returns the existing one.
        """
        return structure_mutations.create_structure(info, input)

    @kante.django_mutation(description="Add a measurement to a structure")
    def create_metric(
        self,
        info: Info,
        input: inputs.CreateMetricInput,
    ) -> types.Metric:
        """
        Add a measurement to an existing structure.

        If the structure doesn't exist, it will be created automatically.
        """
        return measurement_mutations.add_measurement(info, input)

    @kante.django_mutation(description="Link an existing structure to an entity")
    def link_structure_to_entity(
        self,
        info: Info,
        input: inputs.LinkStructureInput,
    ) -> types.Describes:
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
        input: inputs.CreateRelationInput,
    ) -> types.Relation:
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
        input: inputs.ValidateSchemaInput,
    ) -> types.SchemaValidationResult:
        """
        Validate a schema definition and return pydantic-style errors.

        Use this to check a schema before committing it. This does not
        save the schema to the database.
        """
        return schema_mutations.validate_schema(info, input)
