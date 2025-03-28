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
    natural_event_categories: list[types.NaturalEventCategory] = strawberry_django.field(
        description="List of all natural event categories"
    )
    protocol_event_categories: list[types.ProtocolEventCategory] = strawberry_django.field(
        description="List of all protocol event categories"
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


    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def scatter_plot(self, info: Info, id: ID) -> types.ScatterPlot:
        return models.ScatterPlot.objects.get(id=id )
    
    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def entity_category(self, info: Info, id: ID) -> types.EntityCategory:
        return models.EntityCategory.objects.get(id=id)
    
    
    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def structure_category(self, info: Info, id: ID) -> types.StructureCategory:
        return models.StructureCategory.objects.get(id=id)
    
    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def relation_category(self, info: Info, id: ID) -> types.RelationCategory:
        return models.RelationCategory.objects.get(id=id)
    
    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def measurement_category(self, info: Info, id: ID) -> types.MeasurementCategory:
        return models.MeasurementCategory.objects.get(id=id)
    
    
    
    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def node_categories(self, info: Info, input: OffsetPaginationInput) -> list[types.NodeCategory]:
        raise NotImplementedError("This resolver is a placeholder and should be implemented by the developer")
    
    
    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def edge_categories(self, info: Info, input: OffsetPaginationInput) -> list[types.EdgeCategory]:
        raise NotImplementedError("This resolver is a placeholder and should be implemented by the developer")
    
    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def categories(self, info: Info, input: OffsetPaginationInput) -> list[types.Category]:
        raise NotImplementedError("This resolver is a placeholder and should be implemented by the developer")
    
    
    
    
    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def node_query(self, info: Info, id: ID) -> types.NodeQuery:
        return models.NodeQuery.objects.get(id=id)
    
    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def graph_query(self, info: Info, id: ID) -> types.GraphQuery:
        return models.GraphQuery.objects.get(id=id)
    


    @strawberry.django.field(permission_classes=[])
    def node(self, info: Info, id: ID) -> types.Node:

        return types.entity_to_node_subtype(age.get_age_entity(age.to_graph_id(id), age.to_entity_id(id)))

    @strawberry.django.field(permission_classes=[])
    def edge(self, info: Info, id: ID) -> types.Edge:
        return types.Edge(
            _value=age.get_age_entity_relation(
                age.to_graph_id(id), age.to_entity_id(id)
            )
        )

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




    # Scatter Plot
    create_scatter_plot = strawberry_django.mutation(
        resolver=mutations.create_scatter_plot, description="Create a new scatter plot"
    )
    delete_scatter_plot = strawberry_django.mutation(
        resolver=mutations.delete_scatter_plot, description="Delete an existing scatter plot"
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
    
    
    
    create_structure_category = strawberry_django.mutation(
        resolver=mutations.create_structure_category, description="Create a new expression"
    )
    update_structure_category = strawberry_django.mutation(
        resolver=mutations.update_structure_category,
        description="Update an existing expression",
    )
    delete_structure_category = strawberry_django.mutation(
        resolver=mutations.delete_structure_category,
        description="Delete an existing expression",
    )
    
    create_relation_category = strawberry_django.mutation(
        resolver=mutations.create_relation_category, description="Create a new expression"
    )
    update_relation_category = strawberry_django.mutation(
        resolver=mutations.update_relation_category,
        description="Update an existing expression",
    )
    delete_relation_category = strawberry_django.mutation(
        resolver=mutations.delete_relation_category,
        description="Delete an existing expression",
    )
    
    create_entity_category = strawberry_django.mutation(
        resolver=mutations.create_entity_category, description="Create a new expression"
    )
    update_entitiy_category = strawberry_django.mutation(
        resolver=mutations.update_entity_category,
        description="Update an existing expression",
    )
    delete_entity_category = strawberry_django.mutation(
        resolver=mutations.delete_entity_category,
        description="Delete an existing expression",
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
    types=[types.Entity, types.Edge, types.Node,types.Structure, types.Metric, types.ProtocolEvent, types.NaturalEvent,  types.Measurement, types.Relation, types.Participant],
)
