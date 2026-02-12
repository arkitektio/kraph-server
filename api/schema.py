"""
GraphQL Schema for the API.

This module assembles the complete GraphQL schema from queries,
mutations, and subscriptions.
"""

from strawberry.schema.config import StrawberryConfig
from strawberry.extensions import QueryDepthLimiter
from typing import Optional
from authentikate.strawberry.extension import AuthentikateExtension

from .subscriptions import Subscription
from .extensions.cypher import CypherEngineExtension
import kante
from graph_engine.engine.age_engine import AgeEngine
from graph_engine.engine.protocol import CypherEngine
from datalayer.extension import DatalayerExtension


import strawberry
from typing import List
from kante.types import Info

from api.types import Entity, Structure, Metric, Assertion
from api.scalars import StructureIdentifier
from api import queries, types, scalars, mutations


@strawberry.type(description="Graph Engine Queries")
class Query:
    """Root query type for the graph engine API."""

    graph: types.Graph = kante.django_field(description="Get a graph by ID")

    # Schema Operations
    entity_categories: list[types.EntityCategory] = kante.django_field(description="List of all entity categories/schemas")
    entity_category: types.EntityCategory = kante.django_field(description="Get a single entity category/schema by ID")
    structure_categories: list[types.StructureCategory] = kante.django_field(description="List of all structure categories/schemas")
    structure_category: types.StructureCategory = kante.django_field(description="Get a single structure category/schema by ID")
    metric_categories: list[types.MetricCategory] = kante.django_field(description="List of all metric categories/schemas")
    metric_category: types.MetricCategory = kante.django_field(description="Get a single metric category/schema by ID")
    relation_categories: list[types.RelationCategory] = kante.django_field(description="List of all relation categories/schemas")
    relation_category: types.RelationCategory = kante.django_field(description="Get a single relation category/schema by ID")

    entity = kante.django_field(queries.entity, description="Get an entity by ID")

    @strawberry.field(description="Get entities informed by a specific structure")
    def entities_informed_by(
        self,
        info: Info,
        identifier: StructureIdentifier,
        object: str,
    ) -> List[Entity]:
        """Fetch all entities that are informed by a given structure."""
        return queries.entities_informed_by(info, identifier, object)

    @strawberry.field(description="Get a structure by identifier and object")
    def structure(
        self,
        info: Info,
        identifier: StructureIdentifier,
        object: str,
    ) -> Optional[Structure]:
        """Fetch a specific structure by its identifier and object ID."""
        return queries.structure(info, identifier, object)

    @strawberry.field(description="Get all structures that inform an entity")
    def informing_structures(
        self,
        info: Info,
        entity_id: str,
    ) -> List[Structure]:
        """Fetch all structures that inform a given entity."""
        return queries.informing_structures(info, entity_id)

    @strawberry.field(description="Get all measurements for a structure")
    def measurements_for_structure(
        self,
        info: Info,
        identifier: StructureIdentifier,
        object: str,
    ) -> List[Metric]:
        """Fetch all measurements attached to a structure."""
        return queries.metrics_for_structure(info, identifier, object)

    @strawberry.field(description="Get the assertion that generated an entity")
    def assertion_for_entity(
        self,
        info: Info,
        entity_id: str,
    ) -> Optional[Assertion]:
        """Fetch the assertion (provenance) that generated an entity."""
        return queries.assertion_for_entity(info, entity_id)

    @strawberry.field(description="Get all metrics asserted by an assertion")
    def metrics_for_assertion(
        self,
        info: Info,
        assertion_id: int,
    ) -> List[Metric]:
        """Fetch all measurements that were asserted by a given assertion."""
        return queries.metrics_for_structure(info, assertion_id)


@strawberry.type(description="Graph Engine Mutations")
class Mutation:
    create_graph_from_schema = kante.django_mutation(
        description="Create a new graph based on a provided graph schema definition",
        resolver=mutations.create_graph_from_schema,
    )


def create_schema(
    max_depth: int = 10,
    debug: bool = False,
    include_subscriptions: bool = True,
    cypher_engine: Optional[CypherEngine] = None,
) -> kante.Schema:
    """
    Create a configured GraphQL schema for the graph engine.

    Args:
        max_depth: Maximum query depth (default 10)
        debug: Enable debug mode
        include_subscriptions: Whether to include subscriptions (default True)
        cypher_engine: The CypherEngine instance to use for graph operations

    Returns:
        Configured Kante schema
    """
    extensions = [
        QueryDepthLimiter(max_depth=max_depth),
        AuthentikateExtension(),
        DatalayerExtension(),
    ]

    # Add CypherEngineExtension if an engine is provided
    if cypher_engine is not None:
        extensions.append(CypherEngineExtension(engine=cypher_engine))

    if include_subscriptions:
        return kante.Schema(
            query=Query,
            mutation=Mutation,
            subscription=Subscription,
            extensions=extensions,
            config=StrawberryConfig(
                scalar_map={
                    scalars.AnyScalar: strawberry.scalar(
                        name="Base64",
                        serialize=lambda v: v,  # Implement your serialization logic here
                        parse_value=lambda v: v,  # Implement your parsing logic here
                    ),
                    scalars.StructureIdentifier: strawberry.scalar(
                        name="StructureIdentifier",
                        serialize=lambda v: v,  # Implement your serialization logic here
                        parse_value=lambda v: v,  # Implement your parsing logic here
                    ),
                    scalars.GlobalID: strawberry.scalar(
                        name="GlobalID",
                        serialize=lambda v: v,  # Implement your serialization logic here
                        parse_value=lambda v: v,  # Implement your parsing logic here
                    ),
                    scalars.UnixMilliseconds: strawberry.scalar(
                        name="UnixMilliseconds",
                        serialize=lambda v: v,  # Implement your serialization logic here
                        parse_value=lambda v: v,  # Implement your parsing logic here
                    ),
                }
            ),
        )
    else:
        return kante.Schema(
            query=Query,
            mutation=Mutation,
            extensions=extensions,
        )


# Schema introspection helpers
def get_schema_sdl() -> str:
    """Get the GraphQL Schema Definition Language (SDL) for this schema."""
    return str(schema)


def print_schema() -> None:
    """Print the schema SDL to stdout."""
    print(get_schema_sdl())


# Create the schema with subscription support
schema = create_schema(
    max_depth=10,
    debug=True,
    include_subscriptions=True,
    cypher_engine=AgeEngine(),  # You can pass a CypherEngine instance here if needed
)
