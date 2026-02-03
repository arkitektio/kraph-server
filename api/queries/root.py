"""
Root Query type for the API.

Assembles all query resolvers into the root Query type.
"""
import strawberry
from typing import Optional, List
from kante.types import Info

from api.types import Entity, Structure, Measurement, Assertion
from api.scalars import StructureIdentifier
from . import entity as entity_resolvers
from . import structure as structure_resolvers
from . import measurement as measurement_resolvers
from . import assertion as assertion_resolvers


@strawberry.type(description="Graph Engine Queries")
class Query:
    """Root query type for the graph engine API."""

    @strawberry.field(description="Get a single entity by ID")
    def entity(self, info: Info, id: str) -> Entity:
        """Fetch a single entity by its ID."""
        return entity_resolvers.entity(info, id)

    @strawberry.field(description="Get entities informed by a specific structure")
    def entities_informed_by(
        self,
        info: Info,
        identifier: StructureIdentifier,
        object: str,
    ) -> List[Entity]:
        """Fetch all entities that are informed by a given structure."""
        return entity_resolvers.entities_informed_by(info, identifier, object)

    @strawberry.field(description="Get a structure by identifier and object")
    def structure(
        self,
        info: Info,
        identifier: StructureIdentifier,
        object: str,
    ) -> Optional[Structure]:
        """Fetch a specific structure by its identifier and object ID."""
        return structure_resolvers.structure(info, identifier, object)

    @strawberry.field(description="Get all structures that inform an entity")
    def informing_structures(
        self,
        info: Info,
        entity_id: str,
    ) -> List[Structure]:
        """Fetch all structures that inform a given entity."""
        return structure_resolvers.informing_structures(info, entity_id)

    @strawberry.field(description="Get all measurements for a structure")
    def measurements_for_structure(
        self,
        info: Info,
        identifier: StructureIdentifier,
        object: str,
    ) -> List[Measurement]:
        """Fetch all measurements attached to a structure."""
        return measurement_resolvers.measurements_for_structure(info, identifier, object)

    @strawberry.field(description="Get the assertion that generated an entity")
    def assertion_for_entity(
        self,
        info: Info,
        entity_id: str,
    ) -> Optional[Assertion]:
        """Fetch the assertion (provenance) that generated an entity."""
        return assertion_resolvers.assertion_for_entity(info, entity_id)

    @strawberry.field(description="Get all measurements asserted by an assertion")
    def measurements_for_assertion(
        self,
        info: Info,
        assertion_id: int,
    ) -> List[Measurement]:
        """Fetch all measurements that were asserted by a given assertion."""
        return measurement_resolvers.measurements_for_assertion(info, assertion_id)
