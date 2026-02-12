"""
GraphQL Schema for the API.

This module assembles the complete GraphQL schema from queries,
mutations, and subscriptions.
"""

from strawberry.schema.config import StrawberryConfig
from strawberry.extensions import QueryDepthLimiter
from typing import AsyncGenerator, Optional
from authentikate.strawberry.extension import AuthentikateExtension

from .extensions.cypher import CypherEngineExtension
import kante
from graph_engine.engine.age_engine import AgeEngine
from graph_engine.engine.protocol import CypherEngine
from datalayer.extension import DatalayerExtension


import strawberry
from typing import List
from kante.types import Info

from api.types import Entity, Structure, Metric, Assertion

from api import queries, types, mutations
from graph_engine import scalars


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
    structure = kante.django_field(queries.structure, description="Get a structure by ID")
    metric = kante.django_field(queries.metric, description="Get a metric by ID")


@strawberry.type(description="Graph Engine Mutations")
class Mutation:
    create_graph_from_schema = kante.django_mutation(
        description="Create a new graph based on a provided graph schema definition",
        resolver=mutations.create_graph_from_schema,
    )
    create_entity = kante.django_mutation(
        description="Create a new entity in the graph",
        resolver=mutations.create_entity,
    )


@strawberry.type(description="Graph Engine Subscriptions")
class Subscription:
    """A GraphQL subscription type for real-time updates from the graph engine."""

    @strawberry.subscription(description="Subscribe to updates for a specific graph")
    async def graph_updated(self, info: Info, graph_id: scalars.GraphID) -> AsyncGenerator[types.Graph, None]:
        """
        Subscription that triggers when a graph is updated.

        Args:
            info: Strawberry Info context
            graph_id: The ID of the graph to subscribe to updates for
        """
        yield None


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
                    scalars.GraphID: strawberry.scalar(
                        name="GraphID",
                        serialize=lambda v: v,  # Implement your serialization logic here
                        parse_value=lambda v: v,  # Implement your parsing logic here
                    ),
                    scalars.LocalID: strawberry.scalar(
                        name="LocalID",
                        serialize=lambda v: v,  # Implement your serialization logic here
                        parse_value=lambda v: v,  # Implement your parsing logic here
                    ),
                    scalars.AnyScalar: strawberry.scalar(
                        name="AnyScalar",
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
