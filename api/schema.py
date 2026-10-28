"""
GraphQL Schema for the API.

This module assembles the complete GraphQL schema from its queries and
mutations.
"""

from strawberry.schema.config import StrawberryConfig
from kraph_server.logs import QuietErrorsSchema
from strawberry.extensions import QueryDepthLimiter
from collections.abc import Callable
from typing import Optional
from authentikate.strawberry.extension import AuthentikateExtension

from .extensions.projection import ProjectionExtension
from .loaders import LoaderExtension
import kante
from graph_engine.projection import Projector, TableProjector


import strawberry


from api import queries, types, mutations
from api.subscriptions import Subscription
from arkitekt_datalayer import mutations as datalayer_mutations
from arkitekt_datalayer import scalars as datalayer_scalars
from arkitekt_datalayer.datalayer import load_config
from authentikate.catch_alls import declare_catch_alls
from authentikate.strawberry.directives import AuthExtension
from graph_engine import scalars
from kraph_server.contract import CURATOR, EDITOR, contract


def field(resolver: Callable[..., object] | None = None, *, scope: str = "kraph_read", **kwargs):  # noqa: ANN003, ANN201
    """A field an app needs ``scope`` for (``kraph_read``, unless it says otherwise)."""
    return kante.django_field(resolver, extensions=[AuthExtension(scopes=[scope])], **kwargs)


def mutation(scope: str = "kraph_assert", roles: list[str] | None = None, **kwargs) -> strawberry.mutation:  # noqa: ANN003
    """A write: an app needs ``scope`` for it, a member one of ``roles`` (``kraph_editor`` unless it says
    otherwise; ``kraph_admin`` holds every role). Tenancy is still the resolver's own check."""
    return kante.django_mutation(extensions=[AuthExtension(scopes=[scope], any_role_of=roles or [EDITOR])], **kwargs)


def schema_mutation(**kwargs) -> strawberry.mutation:  # noqa: ANN003
    """A change to the vocabulary: ``kraph_schema`` for the app, ``kraph_curator`` for the member."""
    return mutation(scope="kraph_schema", roles=[CURATOR], **kwargs)


def access_mutation(**kwargs) -> strawberry.mutation:  # noqa: ANN003
    """A mutation that hands out read credentials: a read, for whoever may see what it reads."""
    return kante.django_mutation(extensions=[AuthExtension(scopes=["kraph_read"])], **kwargs)


@strawberry.type(description="Graph Engine Queries")
class Query:
    """Root query type, grouped by domain sections: Entity Type, Schema, and Insights."""

    # The claims themselves
    # =========================
    # `node(id:, graph:)` answers with a drawing — how the named view holds the
    # thing. These answer with the recorded statement, which is what a write
    # returns and what exists whether or not any view draws it.
    instance = field(queries.instance, description="Get one claimed individual by ID, as the log has it")
    link = field(queries.link, description="Get one claim relating two things by ID, as the log has it")
    standings = field(queries.standings, description="Every position anyone has taken on one claim, newest first")
    comment = field(queries.comment, description="Get one remark by ID, as the log has it")
    comments_for = field(queries.comments_for, description="Every remark about one external datum, addressed by (identifier, object), newest first — resolved ones included")
    my_mentions = field(queries.my_mentions, description="Every remark that mentions the caller, newest first")

    # Entity Type Section
    # =========================
    node = field(queries.node, description="Get a node by ID, as the named view holds it. Refused when that view does not admit the node; the claim itself is `instance(id:)`")
    nodes = field(queries.nodes, description="List the individuals a view holds, as it draws them — view grain: one row per individual, membership from the view's rule, properties as of the view's cursor")

    entity = field(queries.entity, description="Get an entity by ID, as the named view holds it — see `node`")
    entities = field(queries.entities, description="List the entities a category's view holds, as it draws them — view grain: one row per individual")
    structure = field(queries.structure, description="Get a structure by ID — a bare uuid, its evidence primary key")
    structures = field(queries.structures, description="List structures with optional filters, ordering, and pagination")
    structure_by_identifier = field(queries.structure_by_identifier, description="Get a structure by identifier and object. No graph: a structure belongs to the organization and has no vertex in any projection")
    informing_structures = field(queries.informing_structures, description="List the structures that are evidence for an entity")
    natural_event = field(queries.natural_event, description="Get a natural event by ID, as the named view holds it — see `node`")
    natural_events = field(queries.natural_events, description="List the natural events a category's view holds — view grain: one row per individual")
    protocol_event = field(queries.protocol_event, description="Get a protocol event by ID, as the named view holds it — see `node`")
    protocol_events = field(queries.protocol_events, description="List the protocol events a category's view holds — view grain: one row per individual")
    measurement = field(queries.measurement, description="Get a measurement claim by ID — a bare uuid, its `Link` primary key")
    measurements = field(queries.measurements, description="List the measurement claims a category's rule admits — log grain")
    description = field(queries.description, description="Get an INFORMS claim by ID — a bare uuid, its `Link` primary key")
    input_participation = field(queries.input_participation, description="Get an input participation claim by ID — a bare uuid, its `Link` primary key")
    input_participations = field(queries.input_participations, description="List the input participation claims a view admits — log grain, under the view's event categories' rules")
    output_participation = field(queries.output_participation, description="Get an output participation claim by ID — a bare uuid, its `Link` primary key")
    output_participations = field(queries.output_participations, description="List the output participation claims a view admits — log grain, under the view's event categories' rules")
    # The log itself (RFC 0020). `assertion` / `assertions` existed once before,
    # running Cypher for an AGE `Assertion` edge nothing had ever written, and
    # were removed for it. These read `evidence.Assertion`.
    assertions = field(queries.assertions, description="The acts of claiming, newest first, by who made them, with what tool and when")
    assertion = field(queries.assertion, description="One act of claiming, with every claim it recorded")
    changes = field(queries.changes, description="The log forward from a seq, ascending, cut at the committed horizon — the read a consumer polls without ever skipping a late-committing act")
    relation = field(queries.relation, description="Get a relation claim by ID — a bare uuid, its `Link` primary key")
    relations = field(queries.relations, description="List the relation claims a category's rule admits — log grain: every claim, standings folded under the category's rule, however the view draws them")
    structure_relation = field(queries.structure_relation, description="Get a structure relation claim by ID — a bare uuid, its `Link` primary key")
    structure_relations = field(queries.structure_relations, description="List the structure relation claims a category's rule admits — log grain")
    metric = field(queries.metric, description="Get a metric by ID")
    metrics = field(queries.metrics, description="List every un-retracted metric recorded under one metric kind")
    metrics_for_structure = field(queries.metrics_for_structure, description="List every un-retracted metric describing a structure")
    metrics_for_assertion = field(queries.metrics_for_assertion, description="List every metric recorded under one assertion")

    # =========================
    # Schema Section
    # =========================
    graph: types.Graph = field(description="Get a graph by ID")
    graphs: list[types.Graph] = field(description="List all graphs in the graph engine")

    entity_categories: list[types.EntityCategory] = field(description="List all entity categories")
    entity_category: types.EntityCategory = field(description="Get a single entity category by ID")
    # Explicit resolvers: kinds have no graph, so `CategoryFilter.graph` — which
    # was the only thing scoping these before — no longer exists to fence them.
    terms = field(queries.terms, description="List the organization's words — its vocabulary, independent of any graph")
    term = field(queries.term, description="Get one of the organization's words by ID")
    structure_kinds = field(queries.structure_kinds, description="List the organization's structure kinds")
    structure_kind = field(queries.structure_kind, description="Get one structure kind by ID")
    metric_kinds = field(queries.metric_kinds, description="List the organization's metric kinds")
    metric_kind = field(queries.metric_kind, description="Get one metric kind by ID")
    measurement_categories: list[types.MeasurementCategory] = field(description="List all measurement categories")
    measurement_category: types.MeasurementCategory = field(description="Get a single measurement category by ID")
    relation_categories: list[types.RelationCategory] = field(description="List all relation categories")
    relation_category: types.RelationCategory = field(description="Get a single relation category by ID")
    structure_relation_categories: list[types.StructureRelationCategory] = field(description="List all structure relation categories")
    structure_relation_category: types.StructureRelationCategory = field(description="Get a single structure relation category by ID")
    natural_event_categories: list[types.NaturalEventCategory] = field(description="List all natural event categories")
    natural_event_category: types.NaturalEventCategory = field(description="Get a single natural event category by ID")
    protocol_event_categories: list[types.ProtocolEventCategory] = field(description="List all protocol event categories")
    protocol_event_category: types.ProtocolEventCategory = field(description="Get a single protocol event category by ID")

    # The eight `materialized*` fields are gone. They read `MaterializedEdge` — a
    # stored cross-product of the category pairs an edge category permits — which
    # was populated only at graph creation and never invalidated afterwards: the
    # function that would refresh it when a new entity category widened a
    # predicate had no callers, and `createRelationCategory` never populated it at
    # all. A read surface over a cache that stops being maintained is worse than
    # no read surface. See RFC 0001 §6.

    # ------------------------------------------------------------------
    # Product surface, not the model. Aggregate counts over schema rows,
    # saved analyses, pins and mentions answer neither from the log nor
    # from a drawing (RFC 0025).
    # ------------------------------------------------------------------
    graph_stats: types.GraphStats = field(description="Get aggregated graph stats with optional filters", resolver=types.GraphStatsResolver)
    entity_category_stats: types.EntityCategoryStats = field(description="Get aggregated entity-category stats with optional filters", resolver=types.EntityCategoryStatsResolver)
    structure_kind_stats: types.StructureKindStats = field(description="Aggregated structure-kind stats", resolver=types.StructureKindStatsResolver)
    metric_kind_stats: types.MetricKindStats = field(description="Aggregated metric-kind stats", resolver=types.MetricKindStatsResolver)
    measurement_category_stats: types.MeasurementCategoryStats = field(description="Get aggregated measurement-category stats with optional filters", resolver=types.MeasurementCategoryStatsResolver)
    relation_category_stats: types.RelationCategoryStats = field(description="Get aggregated relation-category stats with optional filters", resolver=types.RelationCategoryStatsResolver)
    structure_relation_category_stats: types.StructureRelationCategoryStats = field(description="Get aggregated structure-relation-category stats with optional filters", resolver=types.StructureRelationCategoryStatsResolver)
    protocol_event_category_stats: types.ProtocolEventCategoryStats = field(description="Get aggregated protocol-event-category stats with optional filters", resolver=types.ProtocolEventCategoryStatsResolver)
    natural_event_category_stats: types.NaturalEventCategoryStats = field(description="Get aggregated natural-event-category stats with optional filters", resolver=types.NaturalEventCategoryStatsResolver)

    # =========================
    # Insights Section
    # =========================
    graph_queries: list[types.GraphQuery] = field(description="Show all saved graph queries")
    graph_query: types.GraphQuery = field(description="Show a single saved graph query by ID")
    graph_table_queries: list[types.GraphTableQuery] = field(description="Show all saved graph table queries")
    graph_table_query: types.GraphTableQuery = field(description="Show a single saved graph table query by ID")
    # `GraphPathQuery` had a type, a dataloader and all four mutations, and no way
    # to read one back — the only member of the family missing its root fields.

    render_graph_table = field(
        queries.render_graph_table, description="Render a saved table query. Answers from the **drawing**: a page of the view's property graph as of its cursor, filtered, ordered and paged there — the one read with no log path. `Graph.projection { lag }` says how far behind the log it is"
    )

    render_table_plan = field(
        queries.render_table_plan,
        description="Render a table plan **without saving it** — the plan a client is still writing, against one view. Same compile path as `renderGraphTable`: answers from the drawing, labels resolved against the view's namespace, filtered, ordered and paged there. Nothing is written; the plan comes back as compiled",
    )

    scatter_plots: list[types.ScatterPlot] = field(description="Show all saved scatter plots")
    scatter_plot: types.ScatterPlot = field(description="Show a single saved scatter plot by ID")


def upload_mutation(**kwargs) -> strawberry.mutation:  # noqa: ANN003
    """A mutation that hands out or finishes upload credentials: gated by ``datalayer.upload_roles``,
    ``kraph_editor`` when it names none.

    Holding any one of the configured roles is enough. Read once, at schema build. The images it
    uploads illustrate graphs, categories, terms and kinds, so an app needs ``kraph_insights``, the
    scope of the editors who make graphs.
    """
    roles = load_config().upload_roles or [EDITOR]
    return kante.django_mutation(extensions=[AuthExtension(scopes=["kraph_insights"], any_role_of=roles)], **kwargs)


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

    assert_entity_exists = mutation(
        description="Claim that an entity exists, under one of the organization's words. Returns the assertion and every view that draws it — empty when no view declares the word, which is an ordinary outcome",
        resolver=mutations.assert_entity_exists,
    )
    retract_entity = mutation(
        description="Claim that an entity no longer stands. It leaves every projection that counts the claim; the evidence stays.",
        resolver=mutations.retract_entity,
    )
    attest_entity = mutation(
        description="Claim that an entity exists, returning it to every projection whose rules admit it",
        resolver=mutations.attest_entity,
    )

    assert_structure_exists = mutation(
        description="Claim that an external datum exists. Idempotent by (identifier, object): a second claim about a datum already on the record is agreement, recorded as a standing under this act (RFC 0023)",
        resolver=mutations.assert_structure_exists,
    )
    attest_structure = mutation(
        description="Claim that a structure still stands, after somebody retracted it. New evidence, not an undo — both positions stay on the record",
        resolver=mutations.attest_structure,
    )
    attest_metric = mutation(
        description="Claim that a measurement still stands. The derived values that dropped it are refolded",
        resolver=mutations.attest_metric,
    )
    attest_link = mutation(
        description="Claim that a link claim still stands — a relation, a classification, a participation, a measurement. One act for every kind, as `retractLinks` is",
        resolver=mutations.attest_link,
    )
    retract_structure = mutation(
        description="Retract a datum: a Standing(stands=false) against it. Its metrics and INFORMS claims stay on the record, but stop counting for every node it informs until somebody attests it again (RFC 0023)",
        resolver=mutations.retract_structure,
    )
    assert_informs = mutation(
        description="Claim that a datum is evidence for an entity — an INFORMS claim",
        resolver=mutations.assert_informs,
    )
    record_metrics = mutation(
        description="Record measurements against a datum already on the record, as one act (was `updateStructure`)",
        resolver=mutations.record_metrics,
    )
    comment_on_structure = mutation(
        description="Record a remark about an external datum, minting its structure if this is the first sight of it. A reply names its parent and stays on the parent's thread",
        resolver=mutations.comment_on_structure,
    )
    retract_comment = mutation(
        description="Claim a remark no longer stands — resolved by a reviewer or withdrawn by its author; the assertion records whose position it is. The row survives",
        resolver=mutations.retract_comment,
    )
    attest_comment = mutation(
        description="Claim a remark stands again — reopening, as new evidence rather than an undo",
        resolver=mutations.attest_comment,
    )
    assert_metric_value = mutation(
        description="Record a measurement, creating the structure it describes if this is its first sight. One assertion covers both",
        resolver=mutations.assert_metric_value,
    )
    assert_metric_value_for_structure = mutation(
        description="Record a measurement against a structure that already exists, named by its evidence id",
        resolver=mutations.assert_metric_value_for_structure,
    )
    retract_metric = mutation(
        description="Retract a measurement without destroying it. It stays readable, because a derived value that dropped it still has to be explainable",
        resolver=mutations.retract_metric,
    )
    supersede_metric_value = mutation(
        description="Correct a measurement by retracting it and asserting a new one. The returned metric has a new id: it is a new row, not an edited one",
        resolver=mutations.supersede_metric_value,
    )
    assert_measurement_exists = mutation(
        description="Assert that a structure measures an entity, under one of the organization's words. Drawings are always empty: a measurement has no AGE edge",
        resolver=mutations.assert_measurement_exists,
    )
    retract_measurement = mutation(
        description="Retract a measurement assertion without destroying it",
        resolver=mutations.retract_measurement,
    )
    assert_relation_exists = mutation(
        description="Assert a relation between two entities, under one of the organization's words",
        resolver=mutations.assert_relation_exists,
    )
    supersede_relation = mutation(
        description="Replace a relation with a new assertion, retracting the old one. Two assertions are recorded; the result reports the one that made the relation now standing",
        resolver=mutations.supersede_relation,
    )
    retract_relation = mutation(
        description="Retract a relation assertion without destroying it. The edge survives wherever another live assertion still states the same proposition",
        resolver=mutations.retract_relation,
    )
    assert_structure_relation_exists = mutation(
        description="Assert a relation between two structures. Drawings are always empty: neither endpoint has a vertex",
        resolver=mutations.assert_structure_relation_exists,
    )
    supersede_structure_relation = mutation(
        description="Replace a structure relation, keeping the old assertion on the record",
        resolver=mutations.supersede_structure_relation,
    )
    retract_structure_relation = mutation(
        description="Retract a structure relation assertion without destroying it",
        resolver=mutations.retract_structure_relation,
    )
    assert_natural_event_exists = mutation(
        description="Claim that a natural event happened, under one of the organization's words",
        resolver=mutations.assert_natural_event_exists,
    )
    retract_natural_event = mutation(
        description="Claim that a natural event no longer stands",
        resolver=mutations.retract_natural_event,
    )
    attest_natural_event = mutation(
        description="Claim that a natural event exists",
        resolver=mutations.attest_natural_event,
    )
    assert_protocol_event_exists = mutation(
        description="Claim that a protocol step happened, under one of the organization's words",
        resolver=mutations.assert_protocol_event_exists,
    )
    retract_protocol_event = mutation(
        description="Claim that a protocol event no longer stands",
        resolver=mutations.retract_protocol_event,
    )
    attest_protocol_event = mutation(
        description="Claim that a protocol event exists",
        resolver=mutations.attest_protocol_event,
    )
    assert_participation = mutation(
        description="Claim that an entity took part in an event, without displacing anyone else's claim",
        resolver=mutations.assert_participation,
    )
    assert_participations = mutation(
        description="Claim that several entities took part in one event, as one act and one assertion",
        resolver=mutations.assert_participations,
    )
    retract_participation = mutation(
        description="Retract one claim that an entity took part in an event. The edge survives while another claim still states it",
        resolver=mutations.retract_participation,
    )
    classify_nodes = mutation(
        description="Claim that several nodes are of a word, without displacing anyone else's claim. One act, one assertion",
        resolver=mutations.classify_nodes,
    )
    retract_links = mutation(
        description="Retract several link claims as one act, by their `Link` ids — a relation, a classification, a participation, a measurement",
        resolver=mutations.retract_links,
    )
    assert_same_instance = mutation(
        description="Claim that several already-recorded instances are one thing. An equivalence with no primary — the order of the ids carries no meaning",
        resolver=mutations.assert_same_instance,
    )
    retract_same_instance = mutation(
        description="Withdraw one sameness claim. The component it held together is rebuilt from the claims that survive, which may split it",
        resolver=mutations.retract_same_instance,
    )
    assert_different_instance = mutation(
        description="Claim that several already-recorded instances are distinct things (RFC 0019). A standing, trusted difference vetoes every direct sameness between its two ends; a disagreement through a third instance is reported as a conflict, not resolved",
        resolver=mutations.assert_different_instance,
    )
    retract_different_instance = mutation(
        description="Withdraw one difference claim. The sameness it vetoed counts again, and the component is rebuilt",
        resolver=mutations.retract_different_instance,
    )

    # ------------------------------------------------------------------
    # Product surface, not the model. Object-store upload grants: nothing
    # below records a claim or reads a view (RFC 0025).
    # ------------------------------------------------------------------
    request_media_upload = upload_mutation(
        description="Upload media and return a URL for access",
        resolver=datalayer_mutations.request_media_upload,
    )
    finish_media_upload = upload_mutation(
        description="Finalize a media upload after the client has written the object",
        resolver=datalayer_mutations.finish_media_upload,
    )
    refresh_media_upload = upload_mutation(
        description="Reissue upload credentials for a media upload still in flight, to the same key, so a write that outlives its credentials carries on. Only the uploader may, never for a finished store, and never past the upload's time limit",
        resolver=datalayer_mutations.refresh_media_upload,
    )
    request_media_access = access_mutation(
        description="Request temporary S3 read credentials for a media file",
        resolver=datalayer_mutations.request_media_access,
    )
    request_general_media_access = access_mutation(
        description="Request temporary S3 read credentials for media files in the organization",
        resolver=datalayer_mutations.request_general_media_access,
    )

    # =========================
    # Insights Section
    # =========================
    create_graph = mutation(
        scope="kraph_insights",
        description="Create a new graph in the graph engine",
        resolver=mutations.create_graph,
    )
    update_graph = mutation(
        scope="kraph_insights",
        description="Update an existing graph in the graph engine",
        resolver=mutations.update_graph,
    )
    update_graph_visual = mutation(
        scope="kraph_insights",
        description="Update the visual configuration of a graph in the graph engine",
        resolver=mutations.update_graph_visual,
    )

    create_graph_table_query_through_builder = mutation(
        scope="kraph_insights",
        description="Create or update a graph table query using builder arguments",
        resolver=mutations.create_graph_table_query_through_builder,
    )
    create_graph_table_query = mutation(
        scope="kraph_insights",
        description="Create a graph table query",
        resolver=mutations.create_graph_table_query,
    )
    update_graph_table_query = mutation(
        scope="kraph_insights",
        description="Update a graph table query",
        resolver=mutations.update_graph_table_query,
    )
    delete_graph_table_query = mutation(
        scope="kraph_insights",
        description="Delete a graph table query",
        resolver=mutations.delete_graph_table_query,
    )
    archive_graph_table_query = mutation(
        scope="kraph_insights",
        description="Archive a graph table query",
        resolver=mutations.archive_graph_table_query,
    )

    create_scatter_plot = mutation(
        scope="kraph_insights",
        description="Create a scatter plot",
        resolver=mutations.create_scatter_plot,
    )
    update_scatter_plot = mutation(
        scope="kraph_insights",
        description="Update a scatter plot",
        resolver=mutations.update_scatter_plot,
    )
    delete_scatter_plot = mutation(
        scope="kraph_insights",
        description="Delete a scatter plot",
        resolver=mutations.delete_scatter_plot,
    )

    delete_graph = mutation(
        scope="kraph_insights",
        description="Delete a graph from the graph engine",
        resolver=mutations.delete_graph,
    )
    archive_graph = mutation(
        scope="kraph_insights",
        description="Archive a graph in the graph engine (soft delete)",
        resolver=mutations.archive_graph,
    )

    # =========================
    # Schema Section
    # =========================
    create_entity_category = schema_mutation(
        description="Create a new entity category in the graph",
        resolver=mutations.create_entity_category,
    )
    delete_entity_category = schema_mutation(
        description="Delete an entity category from the graph",
        resolver=mutations.delete_entity_category,
    )
    update_entity_category = schema_mutation(
        description="Update an existing entity category in the graph",
        resolver=mutations.update_entity_category,
    )
    # The organization's vocabulary — the words the evidence log names. A word's
    # meaning *in one graph* is a `Category`, edited through the category
    # mutations above; these edit the word itself.
    create_term = schema_mutation(
        description="Declare one of the organization's words, or describe one an ingest minted bare",
        resolver=mutations.create_term,
    )
    update_term = schema_mutation(
        description="Update a term's label, description, PURL or colour, or hide it. Its kind and key are its identity and cannot change, and a term is never deleted — hiding is how a word is put away.",
        resolver=mutations.update_term,
    )
    # No `create`: structure kinds are minted lazily by `ensure_structure_kind`
    # the first time a measurement names an identifier.
    delete_structure_kind = schema_mutation(
        description="Retire a structure kind. Refused while any structure is recorded under it — evidence is never deleted; retract the structures first",
        resolver=mutations.delete_structure_kind,
    )
    update_structure_kind = schema_mutation(
        description="Update a structure kind's label, description or colour",
        resolver=mutations.update_structure_kind,
    )
    create_structure_relation_category = schema_mutation(
        description="Create a new structure relation category in the graph",
        resolver=mutations.create_structure_relation_category,
    )
    delete_structure_relation_category = schema_mutation(
        description="Delete a structure relation category from the graph",
        resolver=mutations.delete_structure_relation_category,
    )
    update_structure_relation_category = schema_mutation(
        description="Update an existing structure relation category in the graph",
        resolver=mutations.update_structure_relation_category,
    )
    # No `create`: metric kinds are minted by the write that first records one,
    # because that write is what knows the value kind.
    delete_metric_kind = schema_mutation(
        description="Retire a metric kind. Refused while any metric is recorded under it — evidence is never deleted; retract the metrics first",
        resolver=mutations.delete_metric_kind,
    )
    update_metric_kind = schema_mutation(
        description="Update a metric kind's label, description or colour",
        resolver=mutations.update_metric_kind,
    )
    create_measurement_category = schema_mutation(
        description="Create a new measurement category in the graph",
        resolver=mutations.create_measurement_category,
    )
    delete_measurement_category = schema_mutation(
        description="Delete a measurement category from the graph",
        resolver=mutations.delete_measurement_category,
    )
    update_measurement_category = schema_mutation(
        description="Update an existing measurement category in the graph",
        resolver=mutations.update_measurement_category,
    )
    create_relation_category = schema_mutation(
        description="Create a new relation category in the graph",
        resolver=mutations.create_relation_category,
    )
    delete_relation_category = schema_mutation(
        description="Delete a relation category from the graph",
        resolver=mutations.delete_relation_category,
    )
    update_relation_category = schema_mutation(
        description="Update an existing relation category in the graph",
        resolver=mutations.update_relation_category,
    )
    create_natural_event_category = schema_mutation(
        description="Create a new natural event category in the graph",
        resolver=mutations.create_natural_event_category,
    )
    delete_natural_event_category = schema_mutation(
        description="Delete a natural event category from the graph",
        resolver=mutations.delete_natural_event_category,
    )
    update_natural_event_category = schema_mutation(
        description="Update an existing natural event category in the graph",
        resolver=mutations.update_natural_event_category,
    )
    create_protocol_event_category = schema_mutation(
        description="Create a new protocol event category in the graph",
        resolver=mutations.create_protocol_event_category,
    )
    delete_protocol_event_category = schema_mutation(
        description="Delete a protocol event category from the graph",
        resolver=mutations.delete_protocol_event_category,
    )
    update_protocol_event_category = schema_mutation(
        description="Update an existing protocol event category in the graph",
        resolver=mutations.update_protocol_event_category,
    )

    # Add more mutations as needed


# The subscription root is `api/subscriptions/`. There was one here once, with a
# single field `graphUpdated` whose body was `yield None` — on a generator declared
# to yield a non-null `Graph` — and which nothing ever published to. It was
# removed for that; `assertionRecorded` (RFC 0020) is published to by every
# write, on commit.


class Schema(QuietErrorsSchema, kante.Schema):
    """kante.Schema, logging expected resolver errors as one line and bugs with a traceback (see logs.py)."""


def create_schema(
    max_depth: int = 10,
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

    # `kraph_all` passes every scope check here and `kraph_admin` every role check (authentikate's
    # catch-alls). kraph serves no hosted structures, so this is all `annotate_schema` would do.
    declare_catch_alls(scope=contract.description.all_scope, role=contract.description.admin_role)

    return Schema(
        query=Query,
        mutation=Mutation,
        subscription=Subscription,
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
            # A member of `StandingTarget` (RFC 0020) reachable through that union
            # and `Assertion.comments` alone.
            types.Comment,
        ],
        config=StrawberryConfig(
            scalar_map={
                **datalayer_scalars.SCALAR_MAP,
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


schema = create_schema(
    max_depth=10,
    # The one place the projection kind is chosen. A second kind would be a
    # second `Projector` here — and a registry keyed by `Projection.kind` once
    # two exist.
    projector=TableProjector(),
)
