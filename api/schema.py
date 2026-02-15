"""
GraphQL Schema for the API.

This module assembles the complete GraphQL schema from queries,
mutations, and subscriptions.
"""

from duckdb import description
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
from datalayer import mutations as datalayer_mutations
from graph_engine import scalars


@strawberry.type(description="Graph Engine Queries")
class Query:
    """Root query type for the graph engine API."""

    graph: types.Graph = kante.django_field(description="Get a graph by ID")
    graphs: list[types.Graph] = kante.django_field(description="List of all graphs in the graph engine")

    # Schema Operations
    entity_categories: list[types.EntityCategory] = kante.django_field(description="List of all entity categories/schemas")
    entity_category: types.EntityCategory = kante.django_field(description="Get a single entity category/schema by ID")
    structure_categories: list[types.StructureCategory] = kante.django_field(description="List of all structure categories/schemas")
    structure_category: types.StructureCategory = kante.django_field(description="Get a single structure category/schema by ID")
    metric_categories: list[types.MetricCategory] = kante.django_field(description="List of all metric categories/schemas")
    measurement_categories: list[types.MeasurementCategory] = kante.django_field(description="List of all measurement categories/schemas")
    measurement_category: types.MeasurementCategory = kante.django_field(description="Get a single measurement category/schema by ID")
    metric_category: types.MetricCategory = kante.django_field(description="Get a single metric category/schema by ID")
    relation_categories: list[types.RelationCategory] = kante.django_field(description="List of all relation categories/schemas")
    relation_category: types.RelationCategory = kante.django_field(description="Get a single relation category/schema by ID")
    materialized_edges: list[types.MaterializedEdge] = kante.django_field(description="List of all materialized edges in the graph")
    materialized_edge: types.MaterializedEdge = kante.django_field(description="Get a single materialized edge by ID")

    # Entity queries
    entity = kante.django_field(queries.entity, description="Get an entity by ID")
    structure = kante.django_field(queries.structure, description="Get a structure by composite graph ID")
    structure_by_identifier = kante.django_field(queries.structure_by_identifier, description="Get a structure by graph, identifier and object")
    metric = kante.django_field(queries.metric, description="Get a metric by ID")
    entities = kante.django_field(queries.entities, description="List of entities with optional filters and ordering")

    # Insights
    graph_queries: list[types.GraphQuery] = kante.django_field(description="Show all saved graph queries")
    graph_query: types.GraphQuery = kante.django_field(description="Show a single saved graph query by ID")
    graph_table_queries: list[types.GraphTableQuery] = kante.django_field(description="Show all saved graph table queries")
    graph_table_query: types.GraphTableQuery = kante.django_field(description="Show a single saved graph table query by ID")
    graph_nodes_queries: list[types.GraphNodesQuery] = kante.django_field(description="Show all saved graph nodes queries")
    graph_node_query: types.GraphNodesQuery = kante.django_field(description="Show a single saved graph node query by ID")

    graph_pairs_queries: list[types.GraphPairsQuery] = kante.django_field(description="Show all saved graph pairs queries")
    graph_pairs_query: types.GraphPairsQuery = kante.django_field(description="Show a single saved graph pairs query by ID")

    render_graph_nodes = kante.django_field(queries.render_graph_nodes, description="Render results for a graph nodes query")
    render_graph_path = kante.django_field(queries.render_graph_path, description="Render results for a graph path query")
    render_graph_pairs = kante.django_field(queries.render_graph_pairs, description="Render results for a graph pairs query")
    render_graph_table = kante.django_field(queries.render_graph_table, description="Render results for a graph table query")

    edge_queries: list[types.EdgeQuery] = kante.django_field(description="Show all saved edge queries")
    edge_query: types.EdgeQuery = kante.django_field(description="Show a single saved edge query by ID")
    edge_table_queries: list[types.EdgeTableQuery] = kante.django_field(description="Show all saved edge table queries")
    edge_table_query: types.EdgeTableQuery = kante.django_field(description="Show a single saved edge table query by ID")
    edge_path_queries: list[types.EdgePathQuery] = kante.django_field(description="Show all saved edge path queries")
    edge_path_query: types.EdgePathQuery = kante.django_field(description="Show a single saved edge path query by ID")
    edge_pairs_queries: list[types.EdgePairsQuery] = kante.django_field(description="Show all saved edge pairs queries")
    edge_pairs_query: types.EdgePairsQuery = kante.django_field(description="Show a single saved edge pairs query by ID")

    node_queries: list[types.NodeQuery] = kante.django_field(description="Show all saved node queries")
    node_query: types.NodeQuery = kante.django_field(description="Show a single saved node query by ID")
    node_table_queries: list[types.NodeTableQuery] = kante.django_field(description="Show all saved node table queries")
    node_table_query: types.NodeTableQuery = kante.django_field(description="Show a single saved node table query by ID")
    node_pairs_queries: list[types.NodePairsQuery] = kante.django_field(description="Show all saved node pairs queries")
    node_pairs_query: types.NodePairsQuery = kante.django_field(description="Show a single saved node pairs query by ID")
    node_path_queries: list[types.NodePathQuery] = kante.django_field(description="Show all saved node path queries")
    node_path_query: types.NodePathQuery = kante.django_field(description="Show a single saved node path query by ID")

    # Plots
    scatter_plots: list[types.ScatterPlot] = kante.django_field(description="Show all saved scatter plots")
    scatter_plot: types.ScatterPlot = kante.django_field(description="Show a single saved scatter plot by ID")


@strawberry.type(description="Graph Engine Mutations")
class Mutation:
    pin_node = kante.django_mutation(
        description="Pin a node in the UI for a user",
        resolver=mutations.pin_node,
    )

    create_entity = kante.django_mutation(
        description="Create a new entity in the graph",
        resolver=mutations.create_entity,
    )
    delete_entity = kante.django_mutation(
        description="Delete an entity from the graph",
        resolver=mutations.delete_entity,
    )
    archive_entity = kante.django_mutation(
        description="Archive an entity in the graph (soft delete)",
        resolver=mutations.archive_entity,
    )
    update_entity = kante.django_mutation(
        description="Update an existing entity in the graph",
        resolver=mutations.update_entity,
    )
    create_structure = kante.django_mutation(
        description="Create a new structure in the graph",
        resolver=mutations.create_structure,
    )
    delete_structure = kante.django_mutation(
        description="Delete a structure from the graph",
        resolver=mutations.delete_structure,
    )
    archive_structure = kante.django_mutation(
        description="Archive a structure in the graph (soft delete)",
        resolver=mutations.archive_structure,
    )
    update_structure = kante.django_mutation(
        description="Update an existing structure in the graph",
        resolver=mutations.update_structure,
    )
    record_metric = kante.django_mutation(
        description="Record a metric, auto-creating structure when allowed",
        resolver=mutations.record_metric,
    )
    create_metric = kante.django_mutation(
        description="Create a new metric in the graph",
        resolver=mutations.create_metric,
    )
    delete_metric = kante.django_mutation(
        description="Delete a metric from the graph",
        resolver=mutations.delete_metric,
    )
    archive_metric = kante.django_mutation(
        description="Archive a metric in the graph (soft delete)",
        resolver=mutations.archive_metric,
    )
    update_metric = kante.django_mutation(
        description="Update an existing metric in the graph",
        resolver=mutations.update_metric,
    )

    upload_media = kante.django_mutation(
        description="Upload media and return a URL for access",
        resolver=datalayer_mutations.upload_media,
    )

    #
    create_graph = kante.django_mutation(
        description="Create a new graph in the graph engine",
        resolver=mutations.create_graph,
    )
    create_graph_table_query_through_builder = kante.django_mutation(
        description="Create or update a graph table query using builder arguments",
        resolver=mutations.create_graph_table_query_through_builder,
    )
    delete_graph = kante.django_mutation(
        description="Delete a graph from the graph engine",
        resolver=mutations.delete_graph,
    )
    archive_graph = kante.django_mutation(
        description="Archive a graph in the graph engine (soft delete)",
        resolver=mutations.archive_graph,
    )

    # Categories/schema mutations
    create_entity_category = kante.django_mutation(
        description="Create a new entity category/schema in the graph",
        resolver=mutations.create_entity_category,
    )
    delete_entity_category = kante.django_mutation(
        description="Delete an entity category/schema from the graph",
        resolver=mutations.delete_entity_category,
    )
    update_entity_category = kante.django_mutation(
        description="Update an existing entity category/schema in the graph",
        resolver=mutations.update_entity_category,
    )
    create_structure_category = kante.django_mutation(
        description="Create a new structure category/schema in the graph",
        resolver=mutations.create_structure_category,
    )
    delete_structure_category = kante.django_mutation(
        description="Delete a structure category/schema from the graph",
        resolver=mutations.delete_structure_category,
    )
    update_structure_category = kante.django_mutation(
        description="Update an existing structure category/schema in the graph",
        resolver=mutations.update_structure_category,
    )
    create_structure_relation_category = kante.django_mutation(
        description="Create a new structure relation category/schema in the graph",
        resolver=mutations.create_structure_relation_category,
    )
    delete_structure_relation_category = kante.django_mutation(
        description="Delete a structure relation category/schema from the graph",
        resolver=mutations.delete_structure_relation_category,
    )
    update_structure_relation_category = kante.django_mutation(
        description="Update an existing structure relation category/schema in the graph",
        resolver=mutations.update_structure_relation_category,
    )
    create_metric_category = kante.django_mutation(
        description="Create a new metric category/schema in the graph",
        resolver=mutations.create_metric_category,
    )
    delete_metric_category = kante.django_mutation(
        description="Delete a metric category/schema from the graph",
        resolver=mutations.delete_metric_category,
    )
    update_metric_category = kante.django_mutation(
        description="Update an existing metric category/schema in the graph",
        resolver=mutations.update_metric_category,
    )
    create_relation_category = kante.django_mutation(
        description="Create a new relation category/schema in the graph",
        resolver=mutations.create_relation_category,
    )
    delete_relation_category = kante.django_mutation(
        description="Delete a relation category/schema from the graph",
        resolver=mutations.delete_relation_category,
    )
    update_relation_category = kante.django_mutation(
        description="Update an existing relation category/schema in the graph",
        resolver=mutations.update_relation_category,
    )
    create_natural_event_category = kante.django_mutation(
        description="Create a new natural event category/schema in the graph",
        resolver=mutations.create_natural_event_category,
    )
    delete_natural_event_category = kante.django_mutation(
        description="Delete a natural event category/schema from the graph",
        resolver=mutations.delete_natural_event_category,
    )
    update_natural_event_category = kante.django_mutation(
        description="Update an existing natural event category/schema in the graph",
        resolver=mutations.update_natural_event_category,
    )
    create_protocol_event_category = kante.django_mutation(
        description="Create a new protocol event category/schema in the graph",
        resolver=mutations.create_protocol_event_category,
    )
    delete_protocol_event_category = kante.django_mutation(
        description="Delete a protocol event category/schema from the graph",
        resolver=mutations.delete_protocol_event_category,
    )
    update_protocol_event_category = kante.django_mutation(
        description="Update an existing protocol event category/schema in the graph",
        resolver=mutations.update_protocol_event_category,
    )

    # Add more mutations as needed


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
            types=[
                # Explicitly include all types that are not directly referenced in the Query/Mutation/Subscription root types
                # Node Types
                types.Entity,
                types.Structure,
                types.Metric,
                types.Assertion,
                # Edge Types
                types.Measurement,
                types.Asserted,
                types.Relation,
                types.StructureRelation,
            ],
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
                    scalars.StructureObject: strawberry.scalar(
                        name="StructureObject",
                        description="The `StructureObject` scalar type represents a structure object (e.g 1) on a specific identifier)",
                        serialize=lambda v: v,  # Implement your serialization logic here
                        parse_value=lambda v: v,  # Implement your parsing logic here
                    ),
                    scalars.StructureGlobalID: strawberry.scalar(
                        name="StructureGlobalID",
                        description="The `StructureGlobalID` scalar type represents a structure global identifier (e.g. '@mikro/roi:433')",
                        serialize=lambda v: v,  # Implement your serialization logic here
                        parse_value=lambda v: v,  # Implement your parsing logic here
                    ),
                    scalars.StructureIdentifier: strawberry.scalar(
                        name="StructureIdentifier",
                        description="The `StructureIdentifier` scalar type represents a structure identifier (e.g. '@mikro/roi')",
                        serialize=lambda v: v,  # Implement your serialization logic here
                        parse_value=lambda v: v,  # Implement your parsing logic here
                    ),
                    scalars.AnyScalar: strawberry.scalar(
                        name="AnyScalar",
                        description="The `AnyScalar` scalar type represents an arbitrary JSON-like value",
                        serialize=lambda v: v,  # Implement your serialization logic here
                        parse_value=lambda v: v,  # Implement your parsing logic here
                    ),
                    scalars.CypherLiteral: strawberry.scalar(
                        name="CypherLiteral",
                        description="The `CypherLiteral` scalar type represents a raw Cypher query or fragment",
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
