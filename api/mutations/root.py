"""
Root Mutation type for the API.

Assembles all mutation resolvers into the root Mutation type.
"""
import strawberry
from kante.types import Info

from api.types import Entity, Structure, Measurement, EntityCreationResult, LinkStructureResult
from api.inputs import (
    EntityCreationInputType,
    StructureCreationInputType,
    AddMeasurementInputType,
    LinkStructureInputType,
)
from . import entity as entity_mutations
from . import structure as structure_mutations
from . import measurement as measurement_mutations


@strawberry.type(description="Graph Engine Mutations")
class Mutation:
    """Root mutation type for the graph engine API."""

    @strawberry.mutation(description="Create a new entity with supporting evidence")
    def create_entity(
        self,
        info: Info,
        input: EntityCreationInputType,
    ) -> EntityCreationResult:
        """
        Create a new entity with optional supporting evidence structures.
        
        Properties are automatically derived from the evidence according to
        the graph schema rules.
        """
        return entity_mutations.create_entity(info, input)

    @strawberry.mutation(description="Recalculate entity properties from its evidence")
    def recalculate_entity(
        self,
        info: Info,
        entity_id: str,
    ) -> Entity:
        """
        Force recalculation of an entity's derived properties.
        
        This is useful after batch linking operations where
        recalculate was set to False.
        """
        return entity_mutations.recalculate_entity(info, entity_id)

    @strawberry.mutation(description="Create a new standalone structure")
    def create_structure(
        self,
        info: Info,
        input: StructureCreationInputType,
    ) -> Structure:
        """
        Create a new structure (or return existing if already exists).
        
        Structures are idempotent - creating the same structure twice
        returns the existing one.
        """
        return structure_mutations.create_structure(info, input)

    @strawberry.mutation(description="Add a measurement to a structure")
    def add_measurement(
        self,
        info: Info,
        input: AddMeasurementInputType,
    ) -> Measurement:
        """
        Add a measurement to an existing structure.
        
        If the structure doesn't exist, it will be created automatically.
        """
        return measurement_mutations.add_measurement(info, input)

    @strawberry.mutation(description="Link an existing structure to an entity")
    def link_structure_to_entity(
        self,
        info: Info,
        input: LinkStructureInputType,
    ) -> LinkStructureResult:
        """
        Link an existing structure to an existing entity.
        
        This creates an INFORMS relationship, allowing the structure's
        measurements to contribute to the entity's derived properties.
        
        By default, entity properties are recalculated after linking.
        Set recalculate=False for batch operations.
        """
        return structure_mutations.link_structure_to_entity(info, input)
