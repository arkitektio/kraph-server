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
from .loaders import LoaderExtension
import kante
from graph_engine.engine.age_engine import AgeEngine
from graph_engine.engine.protocol import CypherEngine


import strawberry
from typing import List
from kante.types import Info

from api.types import Entity, Structure, Metric, Assertion

from api import queries, types, mutations
from datalayer import mutations as datalayer_mutations
from graph_engine import scalars


@strawberry.type(description="Graph Engine Queries")
class Query:
    """Root query type, grouped by domain sections: Entity Type, Schema, and Insights."""

    # =========================
    # Entity Type Section
    # =========================
    node = kante.django_field(queries.node, description="Get a node by ID")
    nodes = kante.django_field(queries.nodes, description="List nodes with optional filters, ordering, and pagination")

    entity = kante.django_field(queries.entity, description="Get an entity by ID")
    entities = kante.django_field(queries.entities, description="List entities with optional filters, ordering, and pagination")
    structure = kante.django_field(queries.structure, description="Get a structure by composite graph ID")
    structures = kante.django_field(queries.structures, description="List structures with optional filters, ordering, and pagination")
    structure_by_identifier = kante.django_field(queries.structure_by_identifier, description="Get a structure by graph, identifier and object")
    informing_structures = kante.django_field(queries.informing_structures, description="List the structures that are evidence for an entity")
    natural_event = kante.django_field(queries.natural_event, description="Get a natural event by composite graph ID")
    natural_events = kante.django_field(queries.natural_events, description="List natural events for a natural event category")
    protocol_event = kante.django_field(queries.protocol_event, description="Get a protocol event by composite graph ID")
    protocol_events = kante.django_field(queries.protocol_events, description="List protocol events for a protocol event category")
    measurement = kante.django_field(queries.measurement, description="Get a measurement by composite graph ID")
    measurements = kante.django_field(queries.measurements, description="List measurements for a measurement category")
    description = kante.django_field(queries.description, description="Get a description edge by composite graph ID")
    descriptions = kante.django_field(queries.descriptions, description="List description edges in a graph")
    input_participation = kante.django_field(queries.input_participation, description="Get an input participation edge by composite graph ID")
    input_participations = kante.django_field(queries.input_participations, description="List input participation edges in a graph")
    output_participation = kante.django_field(queries.output_participation, description="Get an output participation edge by composite graph ID")
    output_participations = kante.django_field(queries.output_participations, description="List output participation edges in a graph")
    assertion = kante.django_field(queries.assertion, description="Get an assertion edge by composite graph ID")
    assertions = kante.django_field(queries.assertions, description="List assertion edges in a graph")
    relation = kante.django_field(queries.relation, description="Get a relation by composite graph ID")
    relations = kante.django_field(queries.relations, description="List relations for a relation category")
    structure_relation = kante.django_field(queries.structure_relation, description="Get a structure relation by composite graph ID")
    structure_relations = kante.django_field(queries.structure_relations, description="List structure relations for a structure relation category")
    metric = kante.django_field(queries.metric, description="Get a metric by ID")
    metrics = kante.django_field(queries.metrics, description="List metrics for a metric category")
    metrics_for_structure = kante.django_field(queries.metrics_for_structure, description="List every un-retracted metric describing a structure")
    measurements_for_assertion = kante.django_field(queries.measurements_for_assertion, description="List every metric recorded under one assertion")
    activity = kante.django_field(queries.activity, description="Get an activity node by composite graph ID")
    activities = kante.django_field(queries.activities, description="List activities in a graph with optional filters, ordering, and pagination")

    # =========================
    # Schema Section
    # =========================
    graph: types.Graph = kante.django_field(description="Get a graph by ID")
    graphs: list[types.Graph] = kante.django_field(description="List all graphs in the graph engine")

    category_tags: list[types.CategoryTag] = kante.django_field(description="List all category tags")
    entity_categories: list[types.EntityCategory] = kante.django_field(description="List all entity categories/schemas")
    entity_category: types.EntityCategory = kante.django_field(description="Get a single entity category/schema by ID")
    # Explicit resolvers: kinds have no graph, so `CategoryFilter.graph` — which
    # was the only thing scoping these before — no longer exists to fence them.
    structure_kinds = kante.django_field(queries.structure_kinds, description="List the organization's structure kinds")
    structure_kind = kante.django_field(queries.structure_kind, description="Get one structure kind by ID")
    metric_kinds = kante.django_field(queries.metric_kinds, description="List the organization's metric kinds")
    metric_kind = kante.django_field(queries.metric_kind, description="Get one metric kind by ID")
    measurement_categories: list[types.MeasurementCategory] = kante.django_field(description="List all measurement categories/schemas")
    measurement_category: types.MeasurementCategory = kante.django_field(description="Get a single measurement category/schema by ID")
    relation_categories: list[types.RelationCategory] = kante.django_field(description="List all relation categories/schemas")
    relation_category: types.RelationCategory = kante.django_field(description="Get a single relation category/schema by ID")
    structure_relation_categories: list[types.StructureRelationCategory] = kante.django_field(description="List all structure relation categories/schemas")
    structure_relation_category: types.StructureRelationCategory = kante.django_field(description="Get a single structure relation category/schema by ID")
    natural_event_categories: list[types.NaturalEventCategory] = kante.django_field(description="List all natural event categories/schemas")
    natural_event_category: types.NaturalEventCategory = kante.django_field(description="Get a single natural event category/schema by ID")
    protocol_event_categories: list[types.ProtocolEventCategory] = kante.django_field(description="List all protocol event categories/schemas")
    protocol_event_category: types.ProtocolEventCategory = kante.django_field(description="Get a single protocol event category/schema by ID")

    materialized_edges: list[types.MaterializedEdge] = kante.django_field(description="List all materialized edges in the graph")
    materialized_edge: types.MaterializedEdge = kante.django_field(description="Get a single materialized edge by ID")
    materialized_structure_relation_edges: list[types.MaterializedStructureRelationEdge] = kante.django_field(description="List all materialized structure relation edges in the graph")
    materialized_structure_relation_edge: types.MaterializedStructureRelationEdge = kante.django_field(description="Get a single materialized structure relation edge by ID")
    materialized_relation_edges: list[types.MaterializedRelationEdge] = kante.django_field(description="List all materialized relation edges in the graph")
    materialized_relation_edge: types.MaterializedRelationEdge = kante.django_field(description="Get a single materialized relation edge by ID")
    materialized_measurement_edges: list[types.MaterializedMeasurementEdge] = kante.django_field(description="List all materialized measurement edges in the graph")
    materialized_measurement_edge: types.MaterializedMeasurementEdge = kante.django_field(description="Get a single materialized measurement edge by ID")

    graph_stats: types.GraphStats = kante.django_field(description="Get aggregated graph stats with optional filters", resolver=types.GraphStatsResolver)
    category_tag_stats: types.CategoryTagStats = kante.django_field(description="Get aggregated category-tag stats with optional filters", resolver=types.CategoryTagStatsResolver)
    entity_category_stats: types.EntityCategoryStats = kante.django_field(description="Get aggregated entity-category stats with optional filters", resolver=types.EntityCategoryStatsResolver)
    structure_kind_stats: types.StructureKindStats = kante.django_field(description="Aggregated structure-kind stats", resolver=types.StructureKindStatsResolver)
    metric_kind_stats: types.MetricKindStats = kante.django_field(description="Aggregated metric-kind stats", resolver=types.MetricKindStatsResolver)
    measurement_category_stats: types.MeasurementCategoryStats = kante.django_field(description="Get aggregated measurement-category stats with optional filters", resolver=types.MeasurementCategoryStatsResolver)
    relation_category_stats: types.RelationCategoryStats = kante.django_field(description="Get aggregated relation-category stats with optional filters", resolver=types.RelationCategoryStatsResolver)
    structure_relation_category_stats: types.StructureRelationCategoryStats = kante.django_field(description="Get aggregated structure-relation-category stats with optional filters", resolver=types.StructureRelationCategoryStatsResolver)
    protocol_event_category_stats: types.ProtocolEventCategoryStats = kante.django_field(description="Get aggregated protocol-event-category stats with optional filters", resolver=types.ProtocolEventCategoryStatsResolver)
    natural_event_category_stats: types.NaturalEventCategoryStats = kante.django_field(description="Get aggregated natural-event-category stats with optional filters", resolver=types.NaturalEventCategoryStatsResolver)

    # =========================
    # Insights Section
    # =========================
    graph_queries: list[types.GraphQuery] = kante.django_field(description="Show all saved graph queries")
    graph_query: types.GraphQuery = kante.django_field(description="Show a single saved graph query by ID")
    graph_table_queries: list[types.GraphTableQuery] = kante.django_field(description="Show all saved graph table queries")
    graph_table_query: types.GraphTableQuery = kante.django_field(description="Show a single saved graph table query by ID")
    graph_nodes_queries: list[types.GraphNodesQuery] = kante.django_field(description="Show all saved graph nodes queries")
    graph_node_query: types.GraphNodesQuery = kante.django_field(description="Show a single saved graph node query by ID")
    graph_pairs_queries: list[types.GraphPairsQuery] = kante.django_field(description="Show all saved graph pairs queries")
    graph_pairs_query: types.GraphPairsQuery = kante.django_field(description="Show a single saved graph pairs query by ID")

    node_queries: list[types.NodeQuery] = kante.django_field(description="Show all saved node queries")
    node_query: types.NodeQuery = kante.django_field(description="Show a single saved node query by ID")
    node_table_queries: list[types.NodeTableQuery] = kante.django_field(description="Show all saved node table queries")
    node_table_query: types.NodeTableQuery = kante.django_field(description="Show a single saved node table query by ID")
    node_pairs_queries: list[types.NodePairsQuery] = kante.django_field(description="Show all saved node pairs queries")
    node_pairs_query: types.NodePairsQuery = kante.django_field(description="Show a single saved node pairs query by ID")
    node_path_queries: list[types.NodePathQuery] = kante.django_field(description="Show all saved node path queries")
    node_path_query: types.NodePathQuery = kante.django_field(description="Show a single saved node path query by ID")

    edge_queries: list[types.EdgeQuery] = kante.django_field(description="Show all saved edge queries")
    edge_query: types.EdgeQuery = kante.django_field(description="Show a single saved edge query by ID")
    edge_table_queries: list[types.EdgeTableQuery] = kante.django_field(description="Show all saved edge table queries")
    edge_table_query: types.EdgeTableQuery = kante.django_field(description="Show a single saved edge table query by ID")
    edge_pairs_queries: list[types.EdgePairsQuery] = kante.django_field(description="Show all saved edge pairs queries")
    edge_pairs_query: types.EdgePairsQuery = kante.django_field(description="Show a single saved edge pairs query by ID")
    edge_path_queries: list[types.EdgePathQuery] = kante.django_field(description="Show all saved edge path queries")
    edge_path_query: types.EdgePathQuery = kante.django_field(description="Show a single saved edge path query by ID")

    render_graph_table = kante.django_field(queries.render_graph_table, description="Render results for a graph table query")

    scatter_plots: list[types.ScatterPlot] = kante.django_field(description="Show all saved scatter plots")
    scatter_plot: types.ScatterPlot = kante.django_field(description="Show a single saved scatter plot by ID")


@strawberry.type(description="Graph Engine Mutations")
class Mutation:
    """Root mutation type, grouped by domain sections: Entity Type, Schema, and Insights."""

    # =========================
    # Entity Type Section
    # =========================
    pin_node = kante.django_mutation(
        description="Pin a node in the UI for a user",
        resolver=mutations.pin_node,
    )

    # =========================

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
    ensure_structure = kante.django_mutation(
        description="Ensure a structure exists in the graph, creating it if it does not exist",
        resolver=mutations.ensure_structure,
    )
    delete_structure = kante.django_mutation(
        description="Delete a structure from the graph",
        resolver=mutations.delete_structure,
    )
    archive_structure = kante.django_mutation(
        description="Archive a structure in the graph (soft delete)",
        resolver=mutations.archive_structure,
    )
    link_structure_to_entity = kante.django_mutation(
        description="Assert that a structure is evidence for an entity",
        resolver=mutations.link_structure_to_entity,
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
    delete_measurement = kante.django_mutation(
        description="Delete a measurement from the graph",
        resolver=mutations.delete_measurement,
    )
    archive_measurement = kante.django_mutation(
        description="Archive a measurement in the graph (soft delete)",
        resolver=mutations.archive_measurement,
    )
    delete_relation = kante.django_mutation(
        description="Delete a relation from the graph",
        resolver=mutations.delete_relation,
    )
    archive_relation = kante.django_mutation(
        description="Archive a relation in the graph (soft delete)",
        resolver=mutations.archive_relation,
    )
    create_structure_relation = kante.django_mutation(
        description="Create a new structure relation in the graph",
        resolver=mutations.create_structure_relation,
    )
    update_structure_relation = kante.django_mutation(
        description="Update an existing structure relation in the graph",
        resolver=mutations.update_structure_relation,
    )
    delete_structure_relation = kante.django_mutation(
        description="Delete a structure relation from the graph",
        resolver=mutations.delete_structure_relation,
    )
    archive_structure_relation = kante.django_mutation(
        description="Archive a structure relation in the graph (soft delete)",
        resolver=mutations.archive_structure_relation,
    )
    create_natural_event = kante.django_mutation(
        description="Create a new natural event in the graph",
        resolver=mutations.create_natural_event,
    )
    update_natural_event = kante.django_mutation(
        description="Update an existing natural event in the graph",
        resolver=mutations.update_natural_event,
    )
    delete_natural_event = kante.django_mutation(
        description="Delete a natural event from the graph",
        resolver=mutations.delete_natural_event,
    )
    archive_natural_event = kante.django_mutation(
        description="Archive a natural event in the graph (soft delete)",
        resolver=mutations.archive_natural_event,
    )
    create_protocol_event = kante.django_mutation(
        description="Create a new protocol event in the graph",
        resolver=mutations.create_protocol_event,
    )
    update_protocol_event = kante.django_mutation(
        description="Update an existing protocol event in the graph",
        resolver=mutations.update_protocol_event,
    )
    delete_protocol_event = kante.django_mutation(
        description="Delete a protocol event from the graph",
        resolver=mutations.delete_protocol_event,
    )
    archive_protocol_event = kante.django_mutation(
        description="Archive a protocol event in the graph (soft delete)",
        resolver=mutations.archive_protocol_event,
    )

    request_media_upload = kante.django_mutation(
        description="Upload media and return a URL for access",
        resolver=datalayer_mutations.request_media_upload,
    )
    finish_media_upload = kante.django_mutation(
        description="Finalize a media upload after the client has written the object",
        resolver=datalayer_mutations.finish_media_upload,
    )
    request_bigfile_upload = kante.django_mutation(
        description="Request an upload grant for a big file store",
        resolver=datalayer_mutations.request_bigfile_upload,
    )
    finish_bigfile_upload = kante.django_mutation(
        description="Finalize a big file upload after the client has written the object",
        resolver=datalayer_mutations.finish_bigfile_upload,
    )
    request_zarr_upload = kante.django_mutation(
        description="Request an upload grant for a Zarr store",
        resolver=datalayer_mutations.request_zarr_upload,
    )
    finish_zarr_upload = kante.django_mutation(
        description="Finalize a Zarr upload after the client has written the object",
        resolver=datalayer_mutations.finish_zarr_upload,
    )

    # =========================
    # Insights Section
    # =========================
    create_graph = kante.django_mutation(
        description="Create a new graph in the graph engine",
        resolver=mutations.create_graph,
    )
    update_graph = kante.django_mutation(
        description="Update an existing graph in the graph engine",
        resolver=mutations.update_graph,
    )
    update_graph_visual = kante.django_mutation(
        description="Update the visual configuration of a graph in the graph engine",
        resolver=mutations.update_graph_visual,
    )

    create_graph_table_query = kante.django_mutation(
        description="Create a new graph table query",
        resolver=mutations.create_graph_table_query,
    )
    create_graph_table_query_through_builder = kante.django_mutation(
        description="Create or update a graph table query using builder arguments",
        resolver=mutations.create_graph_table_query_through_builder,
    )
    create_graph_table_query = kante.django_mutation(
        description="Create a graph table query",
        resolver=mutations.create_graph_table_query,
    )
    update_graph_table_query = kante.django_mutation(
        description="Update a graph table query",
        resolver=mutations.update_graph_table_query,
    )
    delete_graph_table_query = kante.django_mutation(
        description="Delete a graph table query",
        resolver=mutations.delete_graph_table_query,
    )
    archive_graph_table_query = kante.django_mutation(
        description="Archive a graph table query",
        resolver=mutations.archive_graph_table_query,
    )

    create_graph_pairs_query = kante.django_mutation(
        description="Create a graph pairs query",
        resolver=mutations.create_graph_pairs_query,
    )
    update_graph_pairs_query = kante.django_mutation(
        description="Update a graph pairs query",
        resolver=mutations.update_graph_pairs_query,
    )
    delete_graph_pairs_query = kante.django_mutation(
        description="Delete a graph pairs query",
        resolver=mutations.delete_graph_pairs_query,
    )
    archive_graph_pairs_query = kante.django_mutation(
        description="Archive a graph pairs query",
        resolver=mutations.archive_graph_pairs_query,
    )

    create_graph_path_query = kante.django_mutation(
        description="Create a graph path query",
        resolver=mutations.create_graph_path_query,
    )
    update_graph_path_query = kante.django_mutation(
        description="Update a graph path query",
        resolver=mutations.update_graph_path_query,
    )
    delete_graph_path_query = kante.django_mutation(
        description="Delete a graph path query",
        resolver=mutations.delete_graph_path_query,
    )
    archive_graph_path_query = kante.django_mutation(
        description="Archive a graph path query",
        resolver=mutations.archive_graph_path_query,
    )

    create_node_table_query = kante.django_mutation(
        description="Create a node table query",
        resolver=mutations.create_node_table_query,
    )
    update_node_table_query = kante.django_mutation(
        description="Update a node table query",
        resolver=mutations.update_node_table_query,
    )
    delete_node_table_query = kante.django_mutation(
        description="Delete a node table query",
        resolver=mutations.delete_node_table_query,
    )
    archive_node_table_query = kante.django_mutation(
        description="Archive a node table query",
        resolver=mutations.archive_node_table_query,
    )

    create_node_pairs_query = kante.django_mutation(
        description="Create a node pairs query",
        resolver=mutations.create_node_pairs_query,
    )
    update_node_pairs_query = kante.django_mutation(
        description="Update a node pairs query",
        resolver=mutations.update_node_pairs_query,
    )
    delete_node_pairs_query = kante.django_mutation(
        description="Delete a node pairs query",
        resolver=mutations.delete_node_pairs_query,
    )
    archive_node_pairs_query = kante.django_mutation(
        description="Archive a node pairs query",
        resolver=mutations.archive_node_pairs_query,
    )

    create_node_path_query = kante.django_mutation(
        description="Create a node path query",
        resolver=mutations.create_node_path_query,
    )
    update_node_path_query = kante.django_mutation(
        description="Update a node path query",
        resolver=mutations.update_node_path_query,
    )
    delete_node_path_query = kante.django_mutation(
        description="Delete a node path query",
        resolver=mutations.delete_node_path_query,
    )
    archive_node_path_query = kante.django_mutation(
        description="Archive a node path query",
        resolver=mutations.archive_node_path_query,
    )

    create_edge_table_query = kante.django_mutation(
        description="Create an edge table query",
        resolver=mutations.create_edge_table_query,
    )
    update_edge_table_query = kante.django_mutation(
        description="Update an edge table query",
        resolver=mutations.update_edge_table_query,
    )
    delete_edge_table_query = kante.django_mutation(
        description="Delete an edge table query",
        resolver=mutations.delete_edge_table_query,
    )
    archive_edge_table_query = kante.django_mutation(
        description="Archive an edge table query",
        resolver=mutations.archive_edge_table_query,
    )

    create_edge_pairs_query = kante.django_mutation(
        description="Create an edge pairs query",
        resolver=mutations.create_edge_pairs_query,
    )
    update_edge_pairs_query = kante.django_mutation(
        description="Update an edge pairs query",
        resolver=mutations.update_edge_pairs_query,
    )
    delete_edge_pairs_query = kante.django_mutation(
        description="Delete an edge pairs query",
        resolver=mutations.delete_edge_pairs_query,
    )
    archive_edge_pairs_query = kante.django_mutation(
        description="Archive an edge pairs query",
        resolver=mutations.archive_edge_pairs_query,
    )

    create_edge_path_query = kante.django_mutation(
        description="Create an edge path query",
        resolver=mutations.create_edge_path_query,
    )
    update_edge_path_query = kante.django_mutation(
        description="Update an edge path query",
        resolver=mutations.update_edge_path_query,
    )
    delete_edge_path_query = kante.django_mutation(
        description="Delete an edge path query",
        resolver=mutations.delete_edge_path_query,
    )
    archive_edge_path_query = kante.django_mutation(
        description="Archive an edge path query",
        resolver=mutations.archive_edge_path_query,
    )

    create_scatter_plot = kante.django_mutation(
        description="Create a scatter plot",
        resolver=mutations.create_scatter_plot,
    )
    update_scatter_plot = kante.django_mutation(
        description="Update a scatter plot",
        resolver=mutations.update_scatter_plot,
    )
    delete_scatter_plot = kante.django_mutation(
        description="Delete a scatter plot",
        resolver=mutations.delete_scatter_plot,
    )
    archive_scatter_plot = kante.django_mutation(
        description="Archive a scatter plot",
        resolver=mutations.archive_scatter_plot,
    )

    delete_graph = kante.django_mutation(
        description="Delete a graph from the graph engine",
        resolver=mutations.delete_graph,
    )
    archive_graph = kante.django_mutation(
        description="Archive a graph in the graph engine (soft delete)",
        resolver=mutations.archive_graph,
    )

    # =========================
    # Schema Section
    # =========================
    create_entity_category = kante.django_mutation(
        description="Create a new entity category/schema in the graph",
        resolver=mutations.create_entity_category,
    )
    create_category_tag = kante.django_mutation(
        description="Create a new category tag in the graph",
        resolver=mutations.create_category_tag,
    )
    update_category_tag = kante.django_mutation(
        description="Update an existing category tag in the graph",
        resolver=mutations.update_category_tag,
    )
    archive_category_tag = kante.django_mutation(
        description="Archive an existing category tag in the graph",
        resolver=mutations.archive_category_tag,
    )
    delete_category_tag = kante.django_mutation(
        description="Delete an existing category tag from the graph",
        resolver=mutations.delete_category_tag,
    )
    delete_entity_category = kante.django_mutation(
        description="Delete an entity category/schema from the graph",
        resolver=mutations.delete_entity_category,
    )
    update_entity_category = kante.django_mutation(
        description="Update an existing entity category/schema in the graph",
        resolver=mutations.update_entity_category,
    )
    # No `create`: structure kinds are minted lazily by `ensure_structure_kind`
    # the first time a measurement names an identifier.
    delete_structure_kind = kante.django_mutation(
        description="Retire a structure kind and the evidence recorded under it",
        resolver=mutations.delete_structure_kind,
    )
    update_structure_kind = kante.django_mutation(
        description="Update a structure kind's label, description or colour",
        resolver=mutations.update_structure_kind,
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
    # No `create`: metric kinds are minted by the write that first records one,
    # because that write is what knows the value kind.
    delete_metric_kind = kante.django_mutation(
        description="Retire a metric kind and the measurements recorded under it",
        resolver=mutations.delete_metric_kind,
    )
    update_metric_kind = kante.django_mutation(
        description="Update a metric kind's label, description or colour",
        resolver=mutations.update_metric_kind,
    )
    create_measurement_category = kante.django_mutation(
        description="Create a new measurement category/schema in the graph",
        resolver=mutations.create_measurement_category,
    )
    delete_measurement_category = kante.django_mutation(
        description="Delete a measurement category/schema from the graph",
        resolver=mutations.delete_measurement_category,
    )
    update_measurement_category = kante.django_mutation(
        description="Update an existing measurement category/schema in the graph",
        resolver=mutations.update_measurement_category,
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
        # Loaders are per-operation. Left as module-level instances they became a
        # process-lifetime cache shared across every tenant.
        LoaderExtension(),
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
                types.Activity,
                types.NaturalEvent,
                types.ProtocolEvent,
                # Shadow Types
                types.RelationShadowLink,
                types.StructureRelationShadowLink,
                types.MeasurementShadowLink,
                # Edge Types
                types.Measurement,
                types.Description,
                types.Assertion,
                types.Relation,
                types.StructureRelation,
            ],
            config=StrawberryConfig(
                scalar_map={
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
