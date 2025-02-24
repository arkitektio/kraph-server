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
from core import age
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
    node_views: list[types.NodeView] = strawberry_django.field(
        description="List of all node views"
    )
    graph_views: list[types.GraphView] = strawberry_django.field(
        description="List of all graph views"
    )
    
    
    graph_queries: list[types.GraphQuery] = strawberry_django.field(
        description="List of all graph queries"
    )
    node_queries: list[types.NodeQuery] = strawberry_django.field(
        description="List of all node queries"
    )
    
    # Node Categories
    generic_categories: list[types.GenericCategory] = strawberry_django.field(
        description="List of all generic categories"
    )
    
    structure_categories: list[types.StructureCategory] = strawberry_django.field(
        description="List of all structure categories"
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

    plot_views: list[types.PlotView] = strawberry_django.field(
        description="List of all plot views"
    )
    
    
    
    models: list[types.Model] = strawberry_django.field(
        description="List of all deep learning models (e.g. neural networks)"
    )
    reagents: list[types.Reagent] = strawberry_django.field(
        description="List of all reagents used in protocols"
    )
    protocols: list[types.Protocol] = strawberry_django.field(
        description="List of all protocols"
    )
    expressions: list[types.Expression] = strawberry_django.field(
        description="List of all expressions in the system"
    )
    ontologies: list[types.Ontology] = strawberry_django.field(
        description="List of all ontologies"
    )
    


    protocol_steps: list[types.ProtocolStep] = strawberry_django.field(
        description="List of all protocol steps"
    )
    protocol_step_templates: list[types.ProtocolStepTemplate] = strawberry_django.field(
        description="List of all protocol step templates"
    )

    nodes: list[types.Entity] = strawberry_django.field(
        resolver=queries.nodes, description="List of all entities in the system"
    )
    edges: list[types.Edge] = strawberry_django.field(
        resolver=queries.edges,
        description="List of all relationships between entities",
    )

    structure = strawberry_django.field(
        resolver=queries.structure,
        description="Gets a specific structure e.g an image, video, or 3D model",
    )

    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def plot_view(self, info: Info, id: ID) -> types.PlotView:
        return models.PlotView.objects.get(id=id)
    
    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def node_category(self, info: Info, id: ID) -> types.NodeCategory:
        return models.NodeCategory.objects.get(id=id)
    
    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def edge_category(self, info: Info, id: ID) -> types.EdgeCategory:
        return models.EdgeCategory.objects.get(id=id)
    
    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def scatter_plot(self, info: Info, id: ID) -> types.ScatterPlot:
        return models.ScatterPlot.objects.get(id=id )
    
    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def generic_category(self, info: Info, id: ID) -> types.GenericCategory:
        return models.GenericCategory.objects.get(id=id)
    
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
    def expression(self, info: Info, id: ID) -> types.Expression:
        return models.Expression.objects.get(id=id)
    
    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def graph_view(self, info: Info, id: ID) -> types.GraphView:
        return models.GraphView.objects.get(id=id)
    
    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def node_view(self, info: Info, id: ID) -> types.NodeView:
        return models.NodeView.objects.get(id=id)
    
    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def node_query(self, info: Info, id: ID) -> types.NodeQuery:
        return models.NodeQuery.objects.get(id=id)
    
    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def graph_query(self, info: Info, id: ID) -> types.GraphQuery:
        return models.GraphQuery.objects.get(id=id)
    
    

    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def reagent(self, info: Info, id: ID) -> types.Reagent:
        print(id)
        return models.Reagent.objects.get(id=id)

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
    def ontology(self, info: Info, id: ID) -> types.Ontology:
        return models.Ontology.objects.get(id=id)

    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def protocol(self, info: Info, id: ID) -> types.Protocol:
        return models.Protocol.objects.get(id=id)

    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def protocol_step(self, info: Info, id: ID) -> types.ProtocolStep:
        return models.ProtocolStep.objects.get(id=id)

    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def expression(self, info: Info, id: ID) -> types.Expression:
        return models.Expression.objects.get(id=id)

    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def protocol_step_template(self, info: Info, id: ID) -> types.ProtocolStepTemplate:
        return models.ProtocolStepTemplate.objects.get(id=id)

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
    
    
    create_graph_view = strawberry_django.mutation(
        resolver=mutations.create_graph_view, description="Create a new graph view"
    )
    
    create_node_view = strawberry_django.mutation(
        resolver=mutations.create_node_view, description="Create a new node view"
    )



    # Scatter Plot
    create_scatter_plot = strawberry_django.mutation(
        resolver=mutations.create_scatter_plot, description="Create a new scatter plot"
    )
    delete_scatter_plot = strawberry_django.mutation(
        resolver=mutations.delete_scatter_plot, description="Delete an existing scatter plot"
    )
    

    # Plot View
    create_plot_view = strawberry_django.mutation(
        resolver=mutations.create_plot_view, description="Create a new plot view"
    )

    create_relation = strawberry_django.mutation(
        resolver=mutations.create_relation,
        description="Create a new relation between entities",
    )
    

    create_measurement = strawberry_django.mutation(
        resolver=mutations.create_measurement,
        description="Create a new metric for an entity",
    )

    create_structure = strawberry_django.mutation(
        resolver=mutations.create_structure,
        description="Create a new structure",
    )

    create_reagent = strawberry_django.mutation(
        resolver=mutations.create_reagent, description="Create a new reagent"
    )


    create_protocol_step = strawberry_django.mutation(
        resolver=mutations.create_protocol_step,
        description="Create a new protocol step",
    )
    delete_protocol_step = strawberry_django.mutation(
        resolver=mutations.delete_protocol_step,
        description="Delete an existing protocol step",
    )
    update_protocol_step = strawberry_django.mutation(
        resolver=mutations.update_protocol_step,
        description="Update an existing protocol step",
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

    create_ontology = strawberry_django.mutation(
        resolver=mutations.create_ontology, description="Create a new ontology"
    )
    delete_ontology = strawberry_django.mutation(
        resolver=mutations.delete_ontology, description="Delete an existing ontology"
    )
    update_ontology = strawberry_django.mutation(
        resolver=mutations.update_ontology, description="Update an existing ontology"
    )
    
    
    create_graph_query = strawberry_django.mutation(
        resolver=mutations.create_graph_query, description="Create a new graph query"
    )
    
    create_node_query = strawberry_django.mutation(
        resolver=mutations.create_node_query, description="Create a new node query"
    )
    
    
    

    create_measurement_category = strawberry_django.mutation(
        resolver=mutations.create_measurement_category, description="Create a new expression"
    )
    update_measurement_category = strawberry_django.mutation(
        resolver=mutations.update_measurement_category,
        description="Update an existing expression",
    )
    delete_measurement_category = strawberry_django.mutation(
        resolver=mutations.delete_measurement_category,
        description="Delete an existing expression",
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
    
    create_generic_category = strawberry_django.mutation(
        resolver=mutations.create_generic_category, description="Create a new expression"
    )
    update_generic_category = strawberry_django.mutation(
        resolver=mutations.update_generic_category,
        description="Update an existing expression",
    )
    delete_generic_category = strawberry_django.mutation(
        resolver=mutations.delete_generic_category,
        description="Delete an existing expression",
    )
    


    create_protocol = strawberry_django.mutation(
        resolver=mutations.create_protocol, description="Create a new protocol"
    )
    delete_protocol = strawberry_django.mutation(
        resolver=mutations.delete_protocol, description="Delete an existing protocol"
    )

    create_protocol_step_template = strawberry_django.mutation(
        resolver=mutations.create_protocol_step_template,
        description="Create a new protocol step template",
    )
    update_protocol_step_template = strawberry_django.mutation(
        resolver=mutations.update_protocol_step_template,
        description="Update an existing protocol step template",
    )
    delete_protocol_step_template = strawberry_django.mutation(
        resolver=mutations.delete_protocol_step_template,
        description="Delete an existing protocol step template",
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
    types=[types.Entity, types.Edge, types.Node, types.Relation, types.Structure, types.Measurement, types.ComputedMeasurement],
)
