from itertools import chain
from kante.types import Info
from typing import Annotated, AsyncGenerator, List
import strawberry
from strawberry_django.optimizer import DjangoOptimizerExtension
from core.datalayer import DatalayerExtension
from strawberry import ID
from strawberry.permission import BasePermission
from typing import Any, Type
from core import types, models
from core import mutations
from core import filters
from core import queries
from core import subscriptions
from core import pagination
from strawberry.field_extensions import InputMutationExtension
import strawberry_django
from koherent.strawberry.extension import KoherentExtension
from authentikate.strawberry.extension import AuthentikateExtension
from authentikate.strawberry import AuthExtension, AuthSubscribeExtension
from core import age, scalars, manager
from strawberry_django.pagination import OffsetPaginationInput


def field(permission_classes=None, **kwargs):
    "A wrapper for field that adds default permission classes and extensions."
    if permission_classes:
        pass
    else:
        permission_classes = []
    return strawberry_django.field(extensions=[AuthExtension()], **kwargs)


def mutation(roles: list[str] | None = None, **kwargs) -> strawberry.mutation:
    """A wrapper for mutation that adds default permission classes and extensions."""

    return strawberry_django.mutation(extensions=[AuthExtension(roles=roles or ["admin"])], **kwargs)


def subscription(**kwargs) -> strawberry.subscription:
    """A wrapper for subscription that adds default permission classes and extensions."""
    return strawberry.subscription(extensions=[AuthSubscribeExtension()], **kwargs)


@strawberry.type
class Query:
    """Query class for the GraphQL API.
    This class defines the root query fields for the GraphQL schema, providing access to various
    entities and operations in the knowledge graph system.
    Fields:
        entities (list[Entity]): List of all entities
        linked_expressions (list[LinkedExpression]): List of all linked expressions
        graphs (list[Graph]): List of all graphs
        models (list[Model]): List of all models
        reagents (list[Reagent]): List of all reagents
        protocols (list[Protocol]): List of all protocols
        expressions (list[Expression]): List of all expressions
        ontologies (list[Ontology]): List of all ontologies
        protocol_steps (list[ProtocolStep]): List of all protocol steps
        protocol_step_templates (list[ProtocolStepTemplate]): List of protocol step templates
        entity_relations (list[EntityRelation]): List of entity relations
    Methods:
        knowledge_graph: Retrieves the knowledge graph
        entity_graph: Retrieves the entity graph
        linked_expression_by_agename: Gets linked expression by AGE name
        paired_entities: Retrieves paired entities
        structure: Gets the structure
        reagent(id): Gets a specific reagent by ID
        entity(id): Gets a specific entity by ID
        entity_relation(id): Gets a specific entity relation by ID
        linked_expression(id): Gets a specific linked expression by ID
        graph(id): Gets a specific graph by ID
        model(id): Gets a specific model by ID
        ontology(id): Gets a specific ontology by ID
        protocol(id): Gets a specific protocol by ID
        protocol_step(id): Gets a specific protocol step by ID
        expression(id): Gets a specific expression by ID
        protocol_step_template(id): Gets a specific protocol step template by ID
        my_active_graph(): Gets the active graph for the current user
    Note:
        Most methods require authentication through  permission class,
        except for entity and entity_relation queries which are publicly accessible.
    """

    graphs: list[types.Graph] = field(description="List of all knowledge graphs")
    graph_sequences: list[types.GraphSequence] = field(description="List of all graph sequences")

    graph_queries: list[types.GraphQuery] = field(description="List of all graph queries")
    node_queries: list[types.NodeQuery] = field(description="List of all node queries")

    # Node Categories
    entity_categories: list[types.EntityCategory] = field(description="List of all generic categories")
    structure_categories: list[types.StructureCategory] = field(description="List of all structure categories")
    natural_event_categories: list[types.NaturalEventCategory] = field(description="List of all natural event categories")
    protocol_event_categories: list[types.ProtocolEventCategory] = field(description="List of all protocol event categories")
    metric_categories: list[types.MetricCategory] = field(description="List of all metric categories")
    reagent_categories: list[types.ReagentCategory] = field(description="List of all reagent categories")

    # Edge Categories
    relation_categories: list[types.RelationCategory] = field(description="List of all relation categories")
    measurement_categories: list[types.MeasurementCategory] = field(description="List of all measurement categories")
    structure_relation_categories: list[types.StructureRelationCategory] = field(description="List of all structure relation categories")

    scatter_plots: list[types.ScatterPlot] = field(description="List of all scatter plots")

    structure = field(
        resolver=queries.structure,
        description="Gets a specific structure e.g an image, video, or 3D model",
    )

    models: list[types.Model] = field(description="List of all deep learning models (e.g. neural networks)")

    nodes: list[types.Entity] = field(resolver=queries.nodes, description="List of all entities in the system")
    edges: list[types.Edge] = field(
        resolver=queries.edges,
        description="List of all relationships between entities",
    )

    tags: list[types.Tag] = field(description="List of all tags in the system")

    render_node_query = field(
        resolver=queries.render_node_query,
        description="Render a node query",
    )

    @field(permission_classes=[])
    def knowledge_views(self, info: Info, identifier: scalars.StructureIdentifier, object: strawberry.ID) -> List[types.KnowledgeView]:
        # filtered StructureCategory
        structure_category = models.StructureCategory.objects.filter(identifier=identifier, graph__pinned_by=info.context.request.user)

        retrieved_views = []

        for scat in structure_category:
            try:
                # get all structures with the same identifier
                retrieved_entitiy = age.get_age_structure_by_object(scat, object)
                retrieved_views.append(
                    types.KnowledgeView(
                        _scat=scat,
                        _structure=retrieved_entitiy,
                    )
                )
            except Exception as e:
                retrieved_views.append(
                    types.KnowledgeView(
                        _scat=scat,
                        _structure=None,
                    )
                )

        return retrieved_views

    @field(description="The best view of the node given the current context")
    def node_view(self, info: Info, query: strawberry.ID, node_id: strawberry.ID) -> types.NodeQueryView:
        from core.renderers.node.render import render_node_view

        best_query = models.NodeQuery.objects.get(id=query)

        if not best_query:
            return None

        return types.NodeQueryView(_query=best_query, _node_id=node_id)

    @field(permission_classes=[])
    def scatter_plot(self, info: Info, id: ID) -> types.ScatterPlot:
        return models.ScatterPlot.objects.get(id=id)

    @field(permission_classes=[])
    def graph_sequence(self, info: Info, id: ID) -> types.GraphSequence:
        return models.GraphSequence.objects.get(id=id)

    @field(permission_classes=[])
    def entity_category(self, info: Info, id: ID) -> types.EntityCategory:
        return models.EntityCategory.objects.get(id=id)

    @field(permission_classes=[])
    def get_entity_by_category_and_external_id(self, info: Info, category: ID, external_id: str) -> types.Entity:
        entity_category = models.EntityCategory.objects.get(id=category)

        return types.entity_to_node_subtype(age.get_age_entity_by_category_and_external_id(entity_category, external_id))

    @field(permission_classes=[])
    def structure_relation_category(self, info: Info, id: ID) -> types.StructureRelationCategory:
        return models.StructureRelationCategory.objects.get(id=id)

    @field(permission_classes=[])
    def metric_category(self, info: Info, id: ID) -> types.MetricCategory:
        return models.MetricCategory.objects.get(id=id)

    @field(permission_classes=[])
    def structure_category(self, info: Info, id: ID) -> types.StructureCategory:
        return models.StructureCategory.objects.get(id=id)

    @field(permission_classes=[])
    def natural_event_category(self, info: Info, id: ID) -> types.NaturalEventCategory:
        return models.NaturalEventCategory.objects.get(id=id)

    @field(permission_classes=[])
    def protocol_event_category(self, info: Info, id: ID) -> types.ProtocolEventCategory:
        return models.ProtocolEventCategory.objects.get(id=id)

    @field(permission_classes=[])
    def reagent_category(self, info: Info, id: ID) -> types.ReagentCategory:
        return models.ReagentCategory.objects.get(id=id)

    @field(permission_classes=[])
    def relation_category(self, info: Info, id: ID) -> types.RelationCategory:
        return models.RelationCategory.objects.get(id=id)

    @field(permission_classes=[])
    def measurement_category(self, info: Info, id: ID) -> types.MeasurementCategory:
        return models.MeasurementCategory.objects.get(id=id)

    @field(permission_classes=[])
    def node_categories(
        self,
        info: Info,
        input: OffsetPaginationInput | None = None,
        filters: filters.NodeCategoryFilter | None = None,
    ) -> list[types.NodeCategory]:
        raise NotImplementedError("This resolver is a dplaceholder and should be implemented by the developer")

    @field(permission_classes=[])
    def edge_categories(
        self,
        info: Info,
        input: OffsetPaginationInput | None = None,
        filters: filters.NodeCategoryFilter | None = None,
    ) -> list[types.EdgeCategory]:
        raise NotImplementedError("This resolver is a placeholder and should be implemented by the developer")

    @field(permission_classes=[])
    def node_query(self, info: Info, id: ID) -> types.NodeQuery:
        return models.NodeQuery.objects.get(id=id)

    @field(permission_classes=[])
    def graph_query(self, info: Info, id: ID) -> types.GraphQuery:
        return models.GraphQuery.objects.get(id=id)

    @field(permission_classes=[])
    def node(self, info: Info, id: ID) -> types.Node:
        return types.entity_to_node_subtype(age.get_age_entity(age.to_graph_id(id), age.to_entity_id(id)))

    @field(permission_classes=[])
    def edge(self, info: Info, id: ID) -> types.Edge:
        return types.Edge(_value=age.get_age_entity_relation(age.to_graph_id(id), age.to_entity_id(id)))

    # SPecial Types
    @field(permission_classes=[])
    def structure(
        self,
        info: Info,
        id: ID,
    ) -> types.Structure:
        return types.entity_to_node_subtype(age.get_age_entity(age.to_graph_id(id), age.to_entity_id(id)))

    @field(permission_classes=[])
    def structure_by_identifier(
        self,
        info: Info,
        graph: strawberry.ID,
        identifier: scalars.StructureIdentifier,
        object: strawberry.ID,
    ) -> types.Structure:
        structure = models.StructureCategory.objects.get(age_name=manager.build_structure_age_name(identifier), graph_id=graph)

        return types.entity_to_node_subtype(age.get_age_structure_by_object(structure, object))

    @field(permission_classes=[])
    def structures(
        self,
        info: Info,
        filters: filters.StructureFilter | None = None,
        pagination: pagination.GraphPaginationInput | None = None,
    ) -> list[types.Structure]:
        return []

    @field(permission_classes=[])
    def entity(
        self,
        info: Info,
        id: ID,
    ) -> types.Entity:
        return types.entity_to_node_subtype(age.get_age_entity(age.to_graph_id(id), age.to_entity_id(id)))

    @field(permission_classes=[])
    def entities(
        self,
        info: Info,
        filters: filters.EntityFilter | None = None,
        pagination: pagination.GraphPaginationInput | None = None,
    ) -> list[types.Entity]:
        return [
            types.entity_to_node_subtype(i)
            for i in age.get_entities(
                filters=filters,
                pagination=pagination,
            )
        ]

    @field(permission_classes=[])
    def reagent(self, info: Info, id: ID) -> types.Reagent:
        return types.entity_to_node_subtype(age.get_age_entity(age.to_graph_id(id), age.to_entity_id(id)))

    @field(permission_classes=[])
    def reagents(
        self,
        info: Info,
        filters: filters.ReagentFilter | None = None,
        pagination: pagination.GraphPaginationInput | None = None,
    ) -> list[types.Reagent]:
        return [
            types.entity_to_node_subtype(i)
            for i in age.get_reagents(
                filters=filters,
                pagination=pagination,
            )
        ]

    @field(permission_classes=[])
    def protocol_event(self, info: Info, id: ID) -> types.ProtocolEvent:
        return types.entity_to_node_subtype(age.get_age_entity(age.to_graph_id(id), age.to_entity_id(id)))

    @field(permission_classes=[])
    def protocol_events(
        self,
        info: Info,
        filters: filters.ProtocolEventFilter | None = None,
        pagination: pagination.GraphPaginationInput | None = None,
    ) -> list[types.ProtocolEvent]:
        return []

    @field(permission_classes=[])
    def natural_event(self, info: Info, id: ID) -> types.NaturalEvent:
        return types.entity_to_node_subtype(age.get_age_entity(age.to_graph_id(id), age.to_entity_id(id)))

    @field(permission_classes=[])
    def natural_events(
        self,
        info: Info,
        filters: filters.NaturalEventFilter | None = None,
        pagination: pagination.GraphPaginationInput | None = None,
    ) -> list[types.ProtocolEvent]:
        return []

    @field(permission_classes=[])
    def metric(self, info: Info, id: ID) -> types.Metric:
        return types.entity_to_node_subtype(age.get_age_entity(age.to_graph_id(id), age.to_entity_id(id)))

    @field(permission_classes=[])
    def metrics(
        self,
        info: Info,
        filters: filters.MetricFilter | None = None,
        pagination: pagination.GraphPaginationInput | None = None,
    ) -> list[types.Metric]:
        return []

    @field(permission_classes=[])
    def measurement(self, info: Info, id: ID) -> types.Measurement:
        return types.relation_to_edge_subtype(age.get_age_entity(age.to_graph_id(id), age.to_entity_id(id)))

    @field(permission_classes=[])
    def measurements(
        self,
        info: Info,
        filters: filters.MeasurementFilter | None = None,
        pagination: pagination.GraphPaginationInput | None = None,
    ) -> list[types.Measurement]:
        return []

    @field(permission_classes=[])
    def relation(self, info: Info, id: ID) -> types.Relation:
        return types.relation_to_edge_subtype(age.get_age_entity(age.to_graph_id(id), age.to_entity_id(id)))

    @field(permission_classes=[])
    def relations(
        self,
        info: Info,
        filters: filters.RelationFilter | None = None,
        pagination: pagination.GraphPaginationInput | None = None,
    ) -> list[types.Relation]:
        return []

    @field(permission_classes=[])
    def participant(self, info: Info, id: ID) -> types.Participant:
        return types.relation_to_edge_subtype(age.get_age_entity(age.to_graph_id(id), age.to_entity_id(id)))

    @field(permission_classes=[])
    def participants(
        self,
        info: Info,
        filters: filters.ParticipantFilter | None = None,
        pagination: pagination.GraphPaginationInput | None = None,
    ) -> list[types.Participant]:
        return []

    @field(permission_classes=[])
    def graph(self, info: Info, id: ID) -> types.Graph:
        return models.Graph.objects.get(id=id)

    @field(permission_classes=[])
    def model(self, info: Info, id: ID) -> types.Model:
        return models.Model.objects.get(id=id)

    @field(permission_classes=[])
    def my_active_graph(self, info: Info) -> types.Graph:
        return models.Graph.objects.filter(user=info.context.request.user).first()


@strawberry.type
class Mutation:
    create_graph = mutation(resolver=mutations.create_graph, description="Create a new graph")
    update_graph = mutation(resolver=mutations.update_graph, description="Update an existing graph")

    delete_graph = mutation(resolver=mutations.delete_graph, description="Delete an existing graph")

    pin_graph = mutation(resolver=mutations.pin_graph, description="Pin or unpin a graph")

    # Create a new Metric Category (Always attached to a structure)
    create_metric_category = mutation(resolver=mutations.create_metric_category, description="Create a new expression")
    update_metric_category = mutation(
        resolver=mutations.update_metric_category,
        description="Update an existing expression",
    )
    delete_metric_category = mutation(
        resolver=mutations.delete_metric_category,
        description="Delete an existing expression",
    )

    # Create a new Measureement Category (Relation from a structure to an entity, ie. delineates, )
    create_measurement_category = mutation(
        resolver=mutations.create_measurement_category,
        description="Create a new expression",
    )
    update_measurement_category = mutation(
        resolver=mutations.update_measurement_category,
        description="Update an existing expression",
    )
    delete_measurement_category = mutation(
        resolver=mutations.delete_measurement_category,
        description="Delete an existing expression",
    )

    # Create a new Structure Category (Always attached to a structure)
    create_structure_category = mutation(
        resolver=mutations.create_structure_category,
        description="Create a new expression",
    )
    update_structure_category = mutation(
        resolver=mutations.update_structure_category,
        description="Update an existing expression",
    )
    delete_structure_category = mutation(
        resolver=mutations.delete_structure_category,
        description="Delete an existing expression",
    )

    # Create a new Relation Category (Entity to Entity Relations)
    create_relation_category = mutation(
        resolver=mutations.create_relation_category,
        description="Create a new expression",
    )
    update_relation_category = mutation(
        resolver=mutations.update_relation_category,
        description="Update an existing expression",
    )
    delete_relation_category = mutation(
        resolver=mutations.delete_relation_category,
        description="Delete an existing expression",
    )

    # Create a new Relation Category (Entity to Entity Relations)
    create_structure_relation_category = mutation(
        resolver=mutations.create_structure_relation_category,
        description="Create a new expression",
    )
    update_structure_relation_category = mutation(
        resolver=mutations.update_structure_relation_category,
        description="Update an existing expression",
    )
    delete_structure_relation_category = mutation(
        resolver=mutations.delete_structure_relation_category,
        description="Delete an existing expression",
    )

    # Create a new Entity Category (a cell, an organelle, a structure, etc)
    create_entity_category = mutation(resolver=mutations.create_entity_category, description="Create a new expression")
    update_entity_category = mutation(
        resolver=mutations.update_entity_category,
        description="Update an existing expression",
    )
    delete_entity_category = mutation(
        resolver=mutations.delete_entity_category,
        description="Delete an existing expression",
    )

    create_structure_metric = mutation(
        resolver=mutations.create_structure_metric,
        description="Create a new structure metric",
    )

    # Create a new Reagent Category (4% PFA, 1% BSA, etc)
    create_reagent_category = mutation(
        resolver=mutations.create_reagent_category,
        description="Create a new expression",
    )
    update_reagent_category = mutation(
        resolver=mutations.update_reagent_category,
        description="Update an existing expression",
    )
    delete_reagent_category = mutation(
        resolver=mutations.delete_reagent_category,
        description="Delete an existing expression",
    )

    # Natural Event Categories (external events that were measured)
    create_natural_event_category = mutation(
        resolver=mutations.create_natural_event_category,
        description="Create a new natural event category",
    )
    update_natural_event_category = mutation(
        resolver=mutations.update_natural_event_category,
        description="Update an existing natural event category",
    )
    delete_natural_event_category = mutation(
        resolver=mutations.delete_natural_event_category,
        description="Delete an existing natural event category",
    )

    # Protocol Event Categories (external events that are forced upon a participant)
    create_protocol_event_category = mutation(
        resolver=mutations.create_protocol_event_category,
        description="Create a new protocol event category",
    )
    update_protocol_event_category = mutation(
        resolver=mutations.update_protocol_event_category,
        description="Update an existing protocol event category",
    )
    delete_protocol_event_category = mutation(
        resolver=mutations.delete_protocol_event_category,
        description="Delete an existing protocol event category",
    )

    # Scatter Plot
    create_scatter_plot = mutation(resolver=mutations.create_scatter_plot, description="Create a new scatter plot")
    delete_scatter_plot = mutation(
        resolver=mutations.delete_scatter_plot,
        description="Delete an existing scatter plot",
    )

    record_natural_event = mutation(
        resolver=mutations.record_natural_event,
        description="Record a new natural event",
    )

    record_protocol_event = mutation(
        resolver=mutations.record_protocol_event,
        description="Record a new protocol event",
    )

    create_toldyouso = mutation(
        resolver=mutations.create_toldyouso,
        description="Create a new 'told you so' supporting structure",
    )
    delete_toldyouso = mutation(
        resolver=mutations.delete_toldyouso,
        description="Delete a 'told you so' supporting structure",
    )

    create_measurement = mutation(
        resolver=mutations.create_measurement,
        description="Create a new measurement edge",
    )

    create_relation = mutation(
        resolver=mutations.create_relation,
        description="Create a new relation between entities",
    )

    create_structure_relation = mutation(
        resolver=mutations.create_structure_relation,
        description="Create a new relation between entities",
    )

    create_metric = mutation(
        resolver=mutations.create_metric,
        description="Create a new metric for an entity",
    )

    create_structure = mutation(
        resolver=mutations.create_structure,
        description="Create a new structure",
    )

    create_model = mutation(resolver=mutations.create_model, description="Create a new model")

    request_upload = mutation(resolver=mutations.request_upload, description="Request a new file upload")

    create_entity = mutation(resolver=mutations.create_entity, description="Create a new entity")
    delete_entity = mutation(resolver=mutations.delete_entity, description="Delete an existing entity")

    create_reagent = mutation(resolver=mutations.create_reagent, description="Create a new entity")
    delete_reagent = mutation(resolver=mutations.delete_reagent, description="Delete an existing entity")

    create_graph_query = mutation(resolver=mutations.create_graph_query, description="Create a new graph query")

    pin_graph_query = mutation(resolver=mutations.pin_graph_query, description="Pin or unpin a graph query")

    create_node_query = mutation(resolver=mutations.create_node_query, description="Create a new node query")

    pin_node_query = mutation(resolver=mutations.pin_node_query, description="Pin or unpin a node query")


@strawberry.type
class Subscription:
    @strawberry.subscription
    async def history_events(
        self,
        info: Info,
        user: Annotated[str, strawberry.argument(description="The user to get history events for")],
    ) -> AsyncGenerator[types.Entity, None]:
        """Join and subscribe to message sent to the given rooms."""
        raise NotImplementedError("This resolver is a placeholder and should be implemented by the developer")


schema = strawberry.Schema(
    query=Query,
    subscription=Subscription,
    mutation=Mutation,
    extensions=[
        DjangoOptimizerExtension,
        KoherentExtension,
        AuthentikateExtension,
        DatalayerExtension,
    ],
    types=[
        types.Entity,
        types.Edge,
        types.Node,
        types.Structure,
        types.Metric,
        types.ProtocolEvent,
        types.NaturalEvent,
        types.Measurement,
        types.Relation,
        types.Participant,
        types.Reagent,
        types.Description,
    ],
)
