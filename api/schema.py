"""
GraphQL Schema for the API.

This module assembles the complete GraphQL schema from its queries and
mutations.
"""

from strawberry.schema.config import StrawberryConfig
from strawberry.extensions import QueryDepthLimiter
from typing import Optional
from authentikate.strawberry.extension import AuthentikateExtension

from .extensions.projection import ProjectionExtension
from .loaders import LoaderExtension
import kante
from graph_engine.projection import Projector, TableProjector


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

    # The claims themselves
    # =========================
    # `node(id:, graph:)` answers with a drawing — how the named view holds the
    # thing. These answer with the recorded statement, which is what a write
    # returns and what exists whether or not any view draws it.
    instance = kante.django_field(queries.instance, description="Get one claimed individual by ID, as the log has it")
    link = kante.django_field(queries.link, description="Get one claim relating two things by ID, as the log has it")
    standings = kante.django_field(queries.standings, description="Every position anyone has taken on one claim, newest first")
    comment = kante.django_field(queries.comment, description="Get one remark by ID, as the log has it")
    comments_for = kante.django_field(queries.comments_for, description="Every remark about one external datum, addressed by (identifier, object), newest first — resolved ones included")
    my_mentions = kante.django_field(queries.my_mentions, description="Every remark that mentions the caller, newest first")

    # Entity Type Section
    # =========================
    node = kante.django_field(queries.node, description="Get a node by ID, as the named view holds it. Refused when that view does not admit the node; the claim itself is `instance(id:)`")
    nodes = kante.django_field(queries.nodes, description="List nodes with optional filters, ordering, and pagination")

    entity = kante.django_field(queries.entity, description="Get an entity by ID, as the named view holds it — see `node`")
    entities = kante.django_field(queries.entities, description="List entities with optional filters, ordering, and pagination")
    structure = kante.django_field(queries.structure, description="Get a structure by ID — a bare uuid, its evidence primary key")
    structures = kante.django_field(queries.structures, description="List structures with optional filters, ordering, and pagination")
    structure_by_identifier = kante.django_field(queries.structure_by_identifier, description="Get a structure by identifier and object. No graph: a structure belongs to the organization and has no vertex in any projection")
    informing_structures = kante.django_field(queries.informing_structures, description="List the structures that are evidence for an entity")
    natural_event = kante.django_field(queries.natural_event, description="Get a natural event by ID, as the named view holds it — see `node`")
    natural_events = kante.django_field(queries.natural_events, description="List natural events for a natural event category")
    protocol_event = kante.django_field(queries.protocol_event, description="Get a protocol event by ID, as the named view holds it — see `node`")
    protocol_events = kante.django_field(queries.protocol_events, description="List protocol events for a protocol event category")
    measurement = kante.django_field(queries.measurement, description="Get a measurement claim by ID — a bare uuid, its `Link` primary key")
    measurements = kante.django_field(queries.measurements, description="List measurements for a measurement category")
    description = kante.django_field(queries.description, description="Get an INFORMS claim by ID — a bare uuid, its `Link` primary key")
    input_participation = kante.django_field(queries.input_participation, description="Get an input participation claim by ID — a bare uuid, its `Link` primary key")
    input_participations = kante.django_field(queries.input_participations, description="List input participation edges in a graph")
    output_participation = kante.django_field(queries.output_participation, description="Get an output participation claim by ID — a bare uuid, its `Link` primary key")
    output_participations = kante.django_field(queries.output_participations, description="List output participation edges in a graph")
    # `assertion` / `assertions` are gone. They ran Cypher for an AGE `Assertion`
    # edge that nothing has ever written, so they could only return empty. An
    # assertion is an evidence row; it is reachable through the write results and
    # through `richProperties { contributingAssertions }`.
    relation = kante.django_field(queries.relation, description="Get a relation claim by ID — a bare uuid, its `Link` primary key")
    relations = kante.django_field(queries.relations, description="List relations for a relation category")
    structure_relation = kante.django_field(queries.structure_relation, description="Get a structure relation claim by ID — a bare uuid, its `Link` primary key")
    structure_relations = kante.django_field(queries.structure_relations, description="List structure relations for a structure relation category")
    metric = kante.django_field(queries.metric, description="Get a metric by ID")
    metrics = kante.django_field(queries.metrics, description="List every un-retracted metric recorded under one metric kind")
    metrics_for_structure = kante.django_field(queries.metrics_for_structure, description="List every un-retracted metric describing a structure")
    metrics_for_assertion = kante.django_field(queries.metrics_for_assertion, description="List every metric recorded under one assertion")

    # =========================
    # Schema Section
    # =========================
    graph: types.Graph = kante.django_field(description="Get a graph by ID")
    graphs: list[types.Graph] = kante.django_field(description="List all graphs in the graph engine")

    entity_categories: list[types.EntityCategory] = kante.django_field(description="List all entity categories")
    entity_category: types.EntityCategory = kante.django_field(description="Get a single entity category by ID")
    # Explicit resolvers: kinds have no graph, so `CategoryFilter.graph` — which
    # was the only thing scoping these before — no longer exists to fence them.
    terms = kante.django_field(queries.terms, description="List the organization's words — its vocabulary, independent of any graph")
    term = kante.django_field(queries.term, description="Get one of the organization's words by ID")
    structure_kinds = kante.django_field(queries.structure_kinds, description="List the organization's structure kinds")
    structure_kind = kante.django_field(queries.structure_kind, description="Get one structure kind by ID")
    metric_kinds = kante.django_field(queries.metric_kinds, description="List the organization's metric kinds")
    metric_kind = kante.django_field(queries.metric_kind, description="Get one metric kind by ID")
    measurement_categories: list[types.MeasurementCategory] = kante.django_field(description="List all measurement categories")
    measurement_category: types.MeasurementCategory = kante.django_field(description="Get a single measurement category by ID")
    relation_categories: list[types.RelationCategory] = kante.django_field(description="List all relation categories")
    relation_category: types.RelationCategory = kante.django_field(description="Get a single relation category by ID")
    structure_relation_categories: list[types.StructureRelationCategory] = kante.django_field(description="List all structure relation categories")
    structure_relation_category: types.StructureRelationCategory = kante.django_field(description="Get a single structure relation category by ID")
    natural_event_categories: list[types.NaturalEventCategory] = kante.django_field(description="List all natural event categories")
    natural_event_category: types.NaturalEventCategory = kante.django_field(description="Get a single natural event category by ID")
    protocol_event_categories: list[types.ProtocolEventCategory] = kante.django_field(description="List all protocol event categories")
    protocol_event_category: types.ProtocolEventCategory = kante.django_field(description="Get a single protocol event category by ID")

    # The eight `materialized*` fields are gone. They read `MaterializedEdge` — a
    # stored cross-product of the category pairs an edge category permits — which
    # was populated only at graph creation and never invalidated afterwards: the
    # function that would refresh it when a new entity category widened a
    # predicate had no callers, and `createRelationCategory` never populated it at
    # all. A read surface over a cache that stops being maintained is worse than
    # no read surface. See RFC 0001 §6.

    graph_stats: types.GraphStats = kante.django_field(description="Get aggregated graph stats with optional filters", resolver=types.GraphStatsResolver)
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
    # `GraphPathQuery` had a type, a dataloader and all four mutations, and no way
    # to read one back — the only member of the family missing its root fields.



    render_graph_table = kante.django_field(queries.render_graph_table, description="Render results for a graph table query")

    scatter_plots: list[types.ScatterPlot] = kante.django_field(description="Show all saved scatter plots")
    scatter_plot: types.ScatterPlot = kante.django_field(description="Show a single saved scatter plot by ID")


@strawberry.type(description="Graph Engine Mutations")
class Mutation:
    """Root mutation type, grouped by domain sections: Entity Type, Schema, and Insights."""

    # =========================
    # Instance writes
    #
    # Every one of these is an act of claiming, named for the act, returning the
    # assertion it recorded plus every view that draws the claim afterwards. See
    # `graph_engine/results.py` and `docs/rfcs/0003-undrawn-nodes.md`.
    #
    # `pinNode` used to sit here. Its resolver was `raise NotImplementedError`.
    # =========================

    assert_entity_exists = kante.django_mutation(
        description="Claim that an entity exists, under one of the organization's words. Returns the assertion and every view that draws it — empty when no view declares the word, which is an ordinary outcome",
        resolver=mutations.assert_entity_exists,
    )
    retract_entity = kante.django_mutation(
        description="Claim that an entity no longer stands. It leaves every projection that counts the claim; the evidence stays.",
        resolver=mutations.retract_entity,
    )
    attest_entity = kante.django_mutation(
        description="Claim that an entity exists, returning it to every projection whose rules admit it",
        resolver=mutations.attest_entity,
    )

    assert_structure_exists = kante.django_mutation(
        description="Claim that an external datum exists and is worth pointing at. Idempotent by (identifier, object)",
        resolver=mutations.assert_structure_exists,
    )
    attest_structure = kante.django_mutation(
        description="Claim that a structure still stands, after somebody retracted it. New evidence, not an undo — both positions stay on the record",
        resolver=mutations.attest_structure,
    )
    attest_metric = kante.django_mutation(
        description="Claim that a measurement still stands. The derived values that dropped it are refolded",
        resolver=mutations.attest_metric,
    )
    attest_link = kante.django_mutation(
        description="Claim that a link claim still stands — a relation, a classification, a participation, a measurement. One act for every kind, as `retractLinks` is",
        resolver=mutations.attest_link,
    )
    ensure_structure = kante.django_mutation(
        description="Get the structure for an external datum, creating it if this is the first sight of it",
        resolver=mutations.ensure_structure,
    )
    retract_structure = kante.django_mutation(
        description="Claim that a structure should no longer be pointed at. The row and its metrics survive",
        resolver=mutations.retract_structure,
    )
    link_structure_to_entity = kante.django_mutation(
        description="Assert that a structure is evidence for an entity",
        resolver=mutations.link_structure_to_entity,
    )
    update_structure = kante.django_mutation(
        description="Append metrics to an existing structure. Its (identifier, object) is immutable",
        resolver=mutations.update_structure,
    )
    comment_on_structure = kante.django_mutation(
        description="Record a remark about an external datum, minting its structure if this is the first sight of it. A reply names its parent and stays on the parent's thread",
        resolver=mutations.comment_on_structure,
    )
    retract_comment = kante.django_mutation(
        description="Claim a remark no longer stands — resolved by a reviewer or withdrawn by its author; the assertion records whose position it is. The row survives",
        resolver=mutations.retract_comment,
    )
    attest_comment = kante.django_mutation(
        description="Claim a remark stands again — reopening, as new evidence rather than an undo",
        resolver=mutations.attest_comment,
    )
    assert_metric_value = kante.django_mutation(
        description="Record a measurement, creating the structure it describes if this is its first sight. One assertion covers both",
        resolver=mutations.assert_metric_value,
    )
    assert_metric_value_for_structure = kante.django_mutation(
        description="Record a measurement against a structure that already exists, named by its evidence id",
        resolver=mutations.assert_metric_value_for_structure,
    )
    retract_metric = kante.django_mutation(
        description="Retract a measurement without destroying it. It stays readable, because a derived value that dropped it still has to be explainable",
        resolver=mutations.retract_metric,
    )
    supersede_metric_value = kante.django_mutation(
        description="Correct a measurement by retracting it and asserting a new one. The returned metric has a new id: it is a new row, not an edited one",
        resolver=mutations.supersede_metric_value,
    )
    assert_measurement_exists = kante.django_mutation(
        description="Assert that a structure measures an entity, under one of the organization's words. Drawings are always empty: a measurement has no AGE edge",
        resolver=mutations.assert_measurement_exists,
    )
    retract_measurement = kante.django_mutation(
        description="Retract a measurement assertion without destroying it",
        resolver=mutations.retract_measurement,
    )
    assert_relation_exists = kante.django_mutation(
        description="Assert a relation between two entities, under one of the organization's words",
        resolver=mutations.assert_relation_exists,
    )
    update_relation = kante.django_mutation(
        description="Replace a relation with a new assertion, retracting the old one. Two assertions are recorded; the result reports the one that made the relation now standing",
        resolver=mutations.update_relation,
    )
    retract_relation = kante.django_mutation(
        description="Retract a relation assertion without destroying it. The edge survives wherever another live assertion still states the same proposition",
        resolver=mutations.retract_relation,
    )
    assert_structure_relation_exists = kante.django_mutation(
        description="Assert a relation between two structures. Drawings are always empty: neither endpoint has a vertex",
        resolver=mutations.assert_structure_relation_exists,
    )
    update_structure_relation = kante.django_mutation(
        description="Replace a structure relation, keeping the old assertion on the record",
        resolver=mutations.update_structure_relation,
    )
    retract_structure_relation = kante.django_mutation(
        description="Retract a structure relation assertion without destroying it",
        resolver=mutations.retract_structure_relation,
    )
    assert_natural_event_exists = kante.django_mutation(
        description="Claim that a natural event happened, under one of the organization's words",
        resolver=mutations.assert_natural_event_exists,
    )
    retract_natural_event = kante.django_mutation(
        description="Claim that a natural event no longer stands",
        resolver=mutations.retract_natural_event,
    )
    attest_natural_event = kante.django_mutation(
        description="Claim that a natural event exists",
        resolver=mutations.attest_natural_event,
    )
    assert_protocol_event_exists = kante.django_mutation(
        description="Claim that a protocol step happened, under one of the organization's words",
        resolver=mutations.assert_protocol_event_exists,
    )
    retract_protocol_event = kante.django_mutation(
        description="Claim that a protocol event no longer stands",
        resolver=mutations.retract_protocol_event,
    )
    attest_protocol_event = kante.django_mutation(
        description="Claim that a protocol event exists",
        resolver=mutations.attest_protocol_event,
    )
    assert_participation = kante.django_mutation(
        description="Claim that an entity took part in an event, without displacing anyone else's claim",
        resolver=mutations.assert_participation,
    )
    assert_participations = kante.django_mutation(
        description="Claim that several entities took part in one event, as one act and one assertion",
        resolver=mutations.assert_participations,
    )
    retract_participation = kante.django_mutation(
        description="Retract one claim that an entity took part in an event. The edge survives while another claim still states it",
        resolver=mutations.retract_participation,
    )
    classify_nodes = kante.django_mutation(
        description="Claim that several nodes are of a word, without displacing anyone else's claim. One act, one assertion",
        resolver=mutations.classify_nodes,
    )
    retract_links = kante.django_mutation(
        description="Retract several link claims as one act, by their `Link` ids — a relation, a classification, a participation, a measurement",
        resolver=mutations.retract_links,
    )
    assert_same_instance = kante.django_mutation(
        description="Claim that several already-recorded instances are one thing. An equivalence with no primary — the order of the ids carries no meaning",
        resolver=mutations.assert_same_instance,
    )
    retract_same_instance = kante.django_mutation(
        description="Withdraw one sameness claim. The component it held together is rebuilt from the claims that survive, which may split it",
        resolver=mutations.retract_same_instance,
    )
    assert_different_instance = kante.django_mutation(
        description="Claim that several already-recorded instances are distinct things (RFC 0019). A standing, trusted difference vetoes every direct sameness between its two ends; a disagreement through a third instance is reported as a conflict, not resolved",
        resolver=mutations.assert_different_instance,
    )
    retract_different_instance = kante.django_mutation(
        description="Withdraw one difference claim. The sameness it vetoed counts again, and the component is rebuilt",
        resolver=mutations.retract_different_instance,
    )

    request_media_upload = kante.django_mutation(
        description="Upload media and return a URL for access",
        resolver=datalayer_mutations.request_media_upload,
    )
    finish_media_upload = kante.django_mutation(
        description="Finalize a media upload after the client has written the object",
        resolver=datalayer_mutations.finish_media_upload,
    )
    request_big_file_upload = kante.django_mutation(
        description="Request an upload grant for a big file store",
        resolver=datalayer_mutations.request_bigfile_upload,
    )
    finish_big_file_upload = kante.django_mutation(
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
        description="Create a new entity category in the graph",
        resolver=mutations.create_entity_category,
    )
    delete_entity_category = kante.django_mutation(
        description="Delete an entity category from the graph",
        resolver=mutations.delete_entity_category,
    )
    update_entity_category = kante.django_mutation(
        description="Update an existing entity category in the graph",
        resolver=mutations.update_entity_category,
    )
    # The organization's vocabulary — the words the evidence log names. A word's
    # meaning *in one graph* is a `Category`, edited through the category
    # mutations above; these edit the word itself.
    create_term = kante.django_mutation(
        description="Declare one of the organization's words, or describe one an ingest minted bare",
        resolver=mutations.create_term,
    )
    update_term = kante.django_mutation(
        description="Update a term's label, description, PURL or colour. Its kind and key are its identity and cannot change.",
        resolver=mutations.update_term,
    )
    delete_term = kante.django_mutation(
        description="Retire a word nothing has been claimed under",
        resolver=mutations.delete_term,
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
        description="Create a new structure relation category in the graph",
        resolver=mutations.create_structure_relation_category,
    )
    delete_structure_relation_category = kante.django_mutation(
        description="Delete a structure relation category from the graph",
        resolver=mutations.delete_structure_relation_category,
    )
    update_structure_relation_category = kante.django_mutation(
        description="Update an existing structure relation category in the graph",
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
        description="Create a new measurement category in the graph",
        resolver=mutations.create_measurement_category,
    )
    delete_measurement_category = kante.django_mutation(
        description="Delete a measurement category from the graph",
        resolver=mutations.delete_measurement_category,
    )
    update_measurement_category = kante.django_mutation(
        description="Update an existing measurement category in the graph",
        resolver=mutations.update_measurement_category,
    )
    create_relation_category = kante.django_mutation(
        description="Create a new relation category in the graph",
        resolver=mutations.create_relation_category,
    )
    delete_relation_category = kante.django_mutation(
        description="Delete a relation category from the graph",
        resolver=mutations.delete_relation_category,
    )
    update_relation_category = kante.django_mutation(
        description="Update an existing relation category in the graph",
        resolver=mutations.update_relation_category,
    )
    create_natural_event_category = kante.django_mutation(
        description="Create a new natural event category in the graph",
        resolver=mutations.create_natural_event_category,
    )
    delete_natural_event_category = kante.django_mutation(
        description="Delete a natural event category from the graph",
        resolver=mutations.delete_natural_event_category,
    )
    update_natural_event_category = kante.django_mutation(
        description="Update an existing natural event category in the graph",
        resolver=mutations.update_natural_event_category,
    )
    create_protocol_event_category = kante.django_mutation(
        description="Create a new protocol event category in the graph",
        resolver=mutations.create_protocol_event_category,
    )
    delete_protocol_event_category = kante.django_mutation(
        description="Delete a protocol event category from the graph",
        resolver=mutations.delete_protocol_event_category,
    )
    update_protocol_event_category = kante.django_mutation(
        description="Update an existing protocol event category in the graph",
        resolver=mutations.update_protocol_event_category,
    )

    # Add more mutations as needed


# There was a `Subscription` type here with one field, `graphUpdated`, whose body
# was `yield None` — on a generator declared to yield a non-null `Graph`. It
# notified nobody: nothing anywhere publishes to it. A subscription that cannot
# emit is worse than an absent one, because a client can open it and wait.


def create_schema(
    max_depth: int = 10,
    debug: bool = False,
    projector: Optional[Projector] = None,
) -> kante.Schema:
    """Build the served GraphQL schema.

    One construction, not two. There used to be an `include_subscriptions` flag
    and an `else` branch that built a `kante.Schema` with **neither** the explicit
    `types=[...]` list nor the `scalar_map` — a second, quietly different schema
    that would have failed at runtime on any query producing a type reachable only
    through an interface. Nothing ever passed `False`, so it was never built; it
    was a divergence waiting for its first caller.

    Args:
        max_depth: Maximum query depth (default 10)
        debug: Enable debug mode
        projector: The projection kind every operation draws through. One per process.

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

    if projector is not None:
        extensions.append(ProjectionExtension(projector=projector))

    return kante.Schema(
        query=Query,
        mutation=Mutation,
        extensions=extensions,
        types=[
            # Explicitly include all types that are not directly referenced in the Query/Mutation root types
            # Node Types
            types.Entity,
            types.Structure,
            types.Metric,
            types.NaturalEvent,
            types.ProtocolEvent,
            # Edge Types
            types.Measurement,
            types.Description,
            types.Assertion,
            types.Relation,
            types.StructureRelation,
            # Reachable only through the `Edge` interface — `connections` and
            # `retractLinks` both return it — so nothing names them
            # concretely and strawberry would not otherwise register them.
            # An unregistered type is not a schema-build error: it fails at
            # *runtime*, as "Abstract type 'Edge' was resolved to a type that
            # does not exist inside the schema", on the one query that
            # produces it.
            types.Classification,
            types.Sameness,
            types.Difference,
            types.Derivation,
            types.InputParticipation,
            types.OutputParticipation,
            # The claims. `Instance` and `Link` are named by the write payloads and
            # by their own root fields, but the members of `ClaimEndpoint` are
            # reachable only through that union — same runtime failure as the `Edge`
            # subtypes above if one is left out.
            types.Instance,
            types.Link,
            # A comment's rich body is served through the `Descendant` interface,
            # so its concrete kinds are reachable only through it — same runtime
            # failure as the `Edge` subtypes above if one is left out.
            types.LeafDescendant,
            types.MentionDescendant,
            types.ParagraphDescendant,
            types.Standing,
            types.Term,
        ],
        config=StrawberryConfig(
            scalar_map={
                scalars.UnixMilliseconds: strawberry.scalar(
                    name="UnixMilliseconds",
                    serialize=lambda v: v,  # Implement your serialization logic here
                    parse_value=lambda v: v,  # Implement your parsing logic here
                ),
                # No `GraphID` scalar. It was a pass-through `NewType` over `str`
                # (`serialize=lambda v: v`), so it validated nothing, and its own
                # definition admitted the name was historical: "It is not a graph's
                # id and has no graph component." It typed roughly half the id
                # arguments — including organization-scoped claim keys like
                # `structure(id:)` and `metric(metricId:)` — while `standings(id:)`,
                # `term(id:)` and every category fetcher used plain `ID`, and every
                # id the schema *returns* is `ID`. One value, two spellings, one of
                # them naming a thing it had no part of. It is `ID` now.
                scalars.StructureObject: strawberry.scalar(
                    name="StructureObject",
                    description="The `StructureObject` scalar type represents a structure object (e.g 1) on a specific identifier)",
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
                    serialize=lambda v: v,
                    parse_value=lambda v: v,
                ),
            }
        ),
    )


# Schema introspection helpers
def get_schema_sdl() -> str:
    """Get the GraphQL Schema Definition Language (SDL) for this schema."""
    return str(schema)


def print_schema() -> None:
    """Print the schema SDL to stdout."""
    print(get_schema_sdl())


schema = create_schema(
    max_depth=10,
    debug=True,
    # The one place the projection kind is chosen. A second kind would be a
    # second `Projector` here — and a registry keyed by `Projection.kind` once
    # two exist.
    projector=TableProjector(),
)
