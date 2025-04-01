from itertools import chain
from kante.types import Info
from typing import Annotated, AsyncGenerator
import strawberry
from strawberry_django.optimizer import DjangoOptimizerExtension
from core.datalayer import DatalayerExtension
from strawberry import ID
from kante.directives import upper, replace, relation
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
from authentikate.strawberry.permissions import IsAuthenticated
from core import age, scalars
from strawberry_django.pagination import OffsetPaginationInput


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
        Most methods require authentication through IsAuthenticated permission class,
        except for entity and entity_relation queries which are publicly accessible.
    """

    graphs: list[types.Graph] = strawberry_django.field(
        description="List of all knowledge graphs"
    )

    graph_queries: list[types.GraphQuery] = strawberry_django.field(
        description="List of all graph queries"
    )
    node_queries: list[types.NodeQuery] = strawberry_django.field(
        description="List of all node queries"
    )

    # Node Categories
    entity_categories: list[types.EntityCategory] = strawberry_django.field(
        description="List of all generic categories"
    )
    structure_categories: list[types.StructureCategory] = strawberry_django.field(
        description="List of all structure categories"
    )
    natural_event_categories: list[types.NaturalEventCategory] = (
        strawberry_django.field(description="List of all natural event categories")
    )
    protocol_event_categories: list[types.ProtocolEventCategory] = (
        strawberry_django.field(description="List of all protocol event categories")
    )
    metric_categories: list[types.MetricCategory] = strawberry_django.field(
        description="List of all metric categories"
    )
    reagent_categories: list[types.ReagentCategory] = strawberry_django.field(
        description="List of all reagent categories"
    )

    # Edge Categories
    relation_categories: list[types.RelationCategory] = strawberry_django.field(
        description="List of all relation categories"
    )
    measurement_categories: list[types.MeasurementCategory] = strawberry_django.field(
        description="List of all measurement categories"
    )

    scatter_plots: list[types.ScatterPlot] = strawberry_django.field(
        description="List of all scatter plots"
    )

    structure = strawberry_django.field(
        resolver=queries.structure,
        description="Gets a specific structure e.g an image, video, or 3D model",
    )

    models: list[types.Model] = strawberry_django.field(
        description="List of all deep learning models (e.g. neural networks)"
    )

    nodes: list[types.Entity] = strawberry_django.field(
        resolver=queries.nodes, description="List of all entities in the system"
    )
    edges: list[types.Edge] = strawberry_django.field(
        resolver=queries.edges,
        description="List of all relationships between entities",
    )
    
    tags: list[types.Tag] = strawberry_django.field(
        description="List of all tags in the system"
    )
    
    render_node_query = strawberry_django.field(
        resolver=queries.render_node_query,
        description="Render a node query",
    )

    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def scatter_plot(self, info: Info, id: ID) -> types.ScatterPlot:
        return models.ScatterPlot.objects.get(id=id)

    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def entity_category(self, info: Info, id: ID) -> types.EntityCategory:
        return models.EntityCategory.objects.get(id=id)

    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def metric_category(self, info: Info, id: ID) -> types.MetricCategory:
        return models.MetricCategory.objects.get(id=id)

    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def structure_category(self, info: Info, id: ID) -> types.StructureCategory:
        return models.StructureCategory.objects.get(id=id)

    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def natural_event_category(self, info: Info, id: ID) -> types.NaturalEventCategory:
        return models.NaturalEventCategory.objects.get(id=id)

    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def protocol_event_category(
        self, info: Info, id: ID
    ) -> types.ProtocolEventCategory:
        return models.ProtocolEventCategory.objects.get(id=id)

    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def reagent_category(self, info: Info, id: ID) -> types.ReagentCategory:
        return models.ReagentCategory.objects.get(id=id)

    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def relation_category(self, info: Info, id: ID) -> types.RelationCategory:
        return models.RelationCategory.objects.get(id=id)

    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def measurement_category(self, info: Info, id: ID) -> types.MeasurementCategory:
        return models.MeasurementCategory.objects.get(id=id)

    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def node_categories(
        self,
        info: Info,
        input: OffsetPaginationInput | None = None,
        filters: filters.EdgeCategoryFilter | None = None,
    ) -> list[types.NodeCategory]:
        raise NotImplementedError(
            "This resolver is a placeholder and should be implemented by the developer"
        )

    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def edge_categories(
        self,
        info: Info,
        input: OffsetPaginationInput | None = None,
        filters: filters.NodeCategoryFilter | None = None,
    ) -> list[types.EdgeCategory]:
        raise NotImplementedError(
            "This resolver is a placeholder and should be implemented by the developer"
        )

    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def node_query(self, info: Info, id: ID) -> types.NodeQuery:
        return models.NodeQuery.objects.get(id=id)

    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def graph_query(self, info: Info, id: ID) -> types.GraphQuery:
        return models.GraphQuery.objects.get(id=id)

    @strawberry.django.field(permission_classes=[])
    def node(self, info: Info, id: ID) -> types.Node:

        return types.entity_to_node_subtype(
            age.get_age_entity(age.to_graph_id(id), age.to_entity_id(id))
        )

    @strawberry.django.field(permission_classes=[])
    def edge(self, info: Info, id: ID) -> types.Edge:
        return types.Edge(
            _value=age.get_age_entity_relation(
                age.to_graph_id(id), age.to_entity_id(id)
            )
        )

    # SPecial Types
    @strawberry.django.field(permission_classes=[])
    def structure(
        self,
        info: Info,
        id: ID,
    ) -> types.Structure:

        return types.entity_to_node_subtype(
            age.get_age_entity(age.to_graph_id(id), age.to_entity_id(id))
        )
        
    @strawberry.django.field(permission_classes=[])
    def structure_by_identifier(
        self,
        info: Info,
        graph: strawberry.ID,
        identifier: scalars.StructureIdentifier,
        object: strawberry.ID,
    ) -> types.Structure:
        
        structure = models.StructureCategory.objects.get_or_create(identifier=identifier, graph_id=graph)

        return age.get_age_structure_by_object(structure, object)

    @strawberry.django.field(permission_classes=[])
    def structures(
        self,
        info: Info,
        filters: filters.StructureFilter | None = None,
        pagination: pagination.GraphPaginationInput | None = None,
    ) -> list[types.Structure]:
        return []

    @strawberry.django.field(permission_classes=[])
    def entity(
        self,
        info: Info,
        id: ID,
    ) -> types.Entity:

        return types.entity_to_node_subtype(
            age.get_age_entity(age.to_graph_id(id), age.to_entity_id(id))
        )

    @strawberry.django.field(permission_classes=[])
    def entities(
        self,
        info: Info,
        filters: filters.EntityFilter | None = None,
        pagination: pagination.GraphPaginationInput | None = None,
    ) -> list[types.Entity]:
        return [types.entity_to_node_subtype(i) for i in age.get_entities(
            filters=filters,
            pagination=pagination,
        )]

    @strawberry.django.field(permission_classes=[])
    def reagent(self, info: Info, id: ID) -> types.Reagent:

        return types.entity_to_node_subtype(
            age.get_age_entity(age.to_graph_id(id), age.to_entity_id(id))
        )

    @strawberry.django.field(permission_classes=[])
    def reagents(
        self,
        info: Info,
        filters: filters.ReagentFilter | None = None,
        pagination: pagination.GraphPaginationInput | None = None,
    ) -> list[types.Reagent]:
        return [types.entity_to_node_subtype(i) for i in age.get_reagents(
            filters=filters,
            pagination=pagination,
        )]

    @strawberry.django.field(permission_classes=[])
    def protocol_event(self, info: Info, id: ID) -> types.ProtocolEvent:

        return types.entity_to_node_subtype(
            age.get_age_entity(age.to_graph_id(id), age.to_entity_id(id))
        )

    @strawberry.django.field(permission_classes=[])
    def protocol_events(
        self,
        info: Info,
        filters: filters.ProtocolEventFilter | None = None,
        pagination: pagination.GraphPaginationInput | None = None,
    ) -> list[types.ProtocolEvent]:
        return []

    @strawberry.django.field(permission_classes=[])
    def natural_event(self, info: Info, id: ID) -> types.NaturalEvent:

        return types.entity_to_node_subtype(
            age.get_age_entity(age.to_graph_id(id), age.to_entity_id(id))
        )

    @strawberry.django.field(permission_classes=[])
    def natural_events(
        self,
        info: Info,
        filters: filters.NaturalEventFilter | None = None,
        pagination: pagination.GraphPaginationInput | None = None,
    ) -> list[types.ProtocolEvent]:
        return []

    @strawberry.django.field(permission_classes=[])
    def metric(self, info: Info, id: ID) -> types.Metric:

        return types.entity_to_node_subtype(
            age.get_age_entity(age.to_graph_id(id), age.to_entity_id(id))
        )

    @strawberry.django.field(permission_classes=[])
    def metrics(
        self,
        info: Info,
        filters: filters.MetricFilter | None = None,
        pagination: pagination.GraphPaginationInput | None = None,
    ) -> list[types.Metric]:
        return []

    @strawberry.django.field(permission_classes=[])
    def measurement(self, info: Info, id: ID) -> types.Measurement:
        return types.relation_to_edge_subtype(
            age.get_age_entity(age.to_graph_id(id), age.to_entity_id(id))
        )

    @strawberry.django.field(permission_classes=[])
    def measurements(
        self,
        info: Info,
        filters: filters.MeasurementFilter | None = None,
        pagination: pagination.GraphPaginationInput | None = None,
    ) -> list[types.Measurement]:
        return []

    @strawberry.django.field(permission_classes=[])
    def relation(self, info: Info, id: ID) -> types.Relation:
        return types.relation_to_edge_subtype(
            age.get_age_entity(age.to_graph_id(id), age.to_entity_id(id))
        )

    @strawberry.django.field(permission_classes=[])
    def relations(
        self,
        info: Info,
        filters: filters.RelationFilter | None = None,
        pagination: pagination.GraphPaginationInput | None = None,
    ) -> list[types.Relation]:
        return []

    @strawberry.django.field(permission_classes=[])
    def participant(self, info: Info, id: ID) -> types.Participant:
        return types.relation_to_edge_subtype(
            age.get_age_entity(age.to_graph_id(id), age.to_entity_id(id))
        )

    @strawberry.django.field(permission_classes=[])
    def participants(
        self,
        info: Info,
        filters: filters.ParticipantFilter | None = None,
        pagination: pagination.GraphPaginationInput | None = None,
    ) -> list[types.Participant]:
        return []

    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def graph(self, info: Info, id: ID) -> types.Graph:
        return models.Graph.objects.get(id=id)

    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def model(self, info: Info, id: ID) -> types.Model:
        return models.Model.objects.get(id=id)

    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def my_active_graph(self, info: Info) -> types.Graph:
        return models.Graph.objects.filter(user=info.context.request.user).first()


@strawberry.type
class Mutation:
    create_graph = strawberry_django.mutation(
        resolver=mutations.create_graph, description="Create a new graph"
    )
    update_graph = strawberry_django.mutation(
        resolver=mutations.update_graph, description="Update an existing graph"
    )

    delete_graph = strawberry_django.mutation(
        resolver=mutations.delete_graph, description="Delete an existing graph"
    )

    pin_graph = strawberry_django.mutation(
        resolver=mutations.pin_graph, description="Pin or unpin a graph"
    )

    # Create a new Metric Category (Always attached to a structure)
    create_metric_category = strawberry_django.mutation(
        resolver=mutations.create_metric_category, description="Create a new expression"
    )
    update_metric_category = strawberry_django.mutation(
        resolver=mutations.update_metric_category,
        description="Update an existing expression",
    )
    delete_metric_category = strawberry_django.mutation(
        resolver=mutations.delete_metric_category,
        description="Delete an existing expression",
    )

    # Create a new Measureement Category (Relation from a structure to an entity, ie. delineates, )
    create_measurement_category = strawberry_django.mutation(
        resolver=mutations.create_measurement_category,
        description="Create a new expression",
    )
    update_measurement_category = strawberry_django.mutation(
        resolver=mutations.update_measurement_category,
        description="Update an existing expression",
    )
    delete_measurement_category = strawberry_django.mutation(
        resolver=mutations.delete_measurement_category,
        description="Delete an existing expression",
    )

    # Create a new Structure Category (Always attached to a structure)
    create_structure_category = strawberry_django.mutation(
        resolver=mutations.create_structure_category,
        description="Create a new expression",
    )
    update_structure_category = strawberry_django.mutation(
        resolver=mutations.update_structure_category,
        description="Update an existing expression",
    )
    delete_structure_category = strawberry_django.mutation(
        resolver=mutations.delete_structure_category,
        description="Delete an existing expression",
    )

    # Create a new Relation Category (Entity to Entity Relations)
    create_relation_category = strawberry_django.mutation(
        resolver=mutations.create_relation_category,
        description="Create a new expression",
    )
    update_relation_category = strawberry_django.mutation(
        resolver=mutations.update_relation_category,
        description="Update an existing expression",
    )
    delete_relation_category = strawberry_django.mutation(
        resolver=mutations.delete_relation_category,
        description="Delete an existing expression",
    )

    # Create a new Entity Category (a cell, an organelle, a structure, etc)
    create_entity_category = strawberry_django.mutation(
        resolver=mutations.create_entity_category, description="Create a new expression"
    )
    update_entity_category = strawberry_django.mutation(
        resolver=mutations.update_entity_category,
        description="Update an existing expression",
    )
    delete_entity_category = strawberry_django.mutation(
        resolver=mutations.delete_entity_category,
        description="Delete an existing expression",
    )

    # Create a new Reagent Category (4% PFA, 1% BSA, etc)
    create_reagent_category = strawberry_django.mutation(
        resolver=mutations.create_reagent_category,
        description="Create a new expression",
    )
    update_reagent_category = strawberry_django.mutation(
        resolver=mutations.update_reagent_category,
        description="Update an existing expression",
    )
    delete_reagent_category = strawberry_django.mutation(
        resolver=mutations.delete_reagent_category,
        description="Delete an existing expression",
    )

    # Natural Event Categories (external events that were measured)
    create_natural_event_category = strawberry_django.mutation(
        resolver=mutations.create_natural_event_category,
        description="Create a new natural event category",
    )
    update_natural_event_category = strawberry_django.mutation(
        resolver=mutations.update_natural_event_category,
        description="Update an existing natural event category",
    )
    delete_natural_event_category = strawberry_django.mutation(
        resolver=mutations.delete_natural_event_category,
        description="Delete an existing natural event category",
    )

    # Protocol Event Categories (external events that are forced upon a participant)
    create_protocol_event_category = strawberry_django.mutation(
        resolver=mutations.create_protocol_event_category,
        description="Create a new protocol event category",
    )
    update_protocol_event_category = strawberry_django.mutation(
        resolver=mutations.update_protocol_event_category,
        description="Update an existing protocol event category",
    )
    delete_protocol_event_category = strawberry_django.mutation(
        resolver=mutations.delete_protocol_event_category,
        description="Delete an existing protocol event category",
    )

    # Scatter Plot
    create_scatter_plot = strawberry_django.mutation(
        resolver=mutations.create_scatter_plot, description="Create a new scatter plot"
    )
    delete_scatter_plot = strawberry_django.mutation(
        resolver=mutations.delete_scatter_plot,
        description="Delete an existing scatter plot",
    )

    record_natural_event = strawberry_django.mutation(
        resolver=mutations.record_natural_event,
        description="Record a new natural event",
    )

    record_protocol_event = strawberry_django.mutation(
        resolver=mutations.record_protocol_event,
        description="Record a new protocol event",
    )

    create_toldyouso = strawberry_django.mutation(
        resolver=mutations.create_toldyouso,
        description="Create a new 'told you so' supporting structure",
    )
    delete_toldyouso = strawberry_django.mutation(
        resolver=mutations.delete_toldyouso,
        description="Delete a 'told you so' supporting structure",
    )

    create_measurement = strawberry_django.mutation(
        resolver=mutations.create_measurement,
        description="Create a new measurement edge",
    )

    create_relation = strawberry_django.mutation(
        resolver=mutations.create_relation,
        description="Create a new relation between entities",
    )

    create_metric = strawberry_django.mutation(
        resolver=mutations.create_metric,
        description="Create a new metric for an entity",
    )

    create_structure = strawberry_django.mutation(
        resolver=mutations.create_structure,
        description="Create a new structure",
    )

    create_model = strawberry_django.mutation(
        resolver=mutations.create_model, description="Create a new model"
    )

    request_upload = strawberry_django.mutation(
        resolver=mutations.request_upload, description="Request a new file upload"
    )

    create_entity = strawberry_django.mutation(
        resolver=mutations.create_entity, description="Create a new entity"
    )
    delete_entity = strawberry_django.mutation(
        resolver=mutations.delete_entity, description="Delete an existing entity"
    )

    create_reagent = strawberry_django.mutation(
        resolver=mutations.create_reagent, description="Create a new entity"
    )
    delete_reagent = strawberry_django.mutation(
        resolver=mutations.delete_reagent, description="Delete an existing entity"
    )

    create_graph_query = strawberry_django.mutation(
        resolver=mutations.create_graph_query, description="Create a new graph query"
    )

    pin_graph_query = strawberry_django.mutation(
        resolver=mutations.pin_graph_query, description="Pin or unpin a graph query"
    )

    create_node_query = strawberry_django.mutation(
        resolver=mutations.create_node_query, description="Create a new node query"
    )

    pin_node_query = strawberry_django.mutation(
        resolver=mutations.pin_node_query, description="Pin or unpin a node query"
    )


@strawberry.type
class Subscription:

    @strawberry.subscription
    async def history_events(
        self,
        info: Info,
        user: Annotated[
            str, strawberry.argument(description="The user to get history events for")
        ],
    ) -> AsyncGenerator[types.Entity, None]:
        """Join and subscribe to message sent to the given rooms."""
        raise NotImplementedError(
            "This resolver is a placeholder and should be implemented by the developer"
        )


schema = strawberry.Schema(
    query=Query,
    subscription=Subscription,
    mutation=Mutation,
    directives=[upper, replace, relation],
    extensions=[
        DjangoOptimizerExtension,
        KoherentExtension,
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
    ],
)
