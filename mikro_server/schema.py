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

    path = strawberry_django.field(
        resolver=queries.path,
        description="Retrieves the complete knowledge graph starting from an entity",
    )
    pairs = strawberry_django.field(
        resolver=queries.pairs,
        description="Retrieves paired entities",
    )

    render_graph = strawberry_django.field(
        resolver=queries.render_graph,
        description="Renders a graph query",
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
    pairs = strawberry_django.field(
        resolver=queries.pairs, description="Retrieves paired entities"
    )

    structure = strawberry_django.field(
        resolver=queries.structure,
        description="Gets a specific structure e.g an image, video, or 3D model",
    )

    
    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def expression(self, info: Info, id: ID) -> types.Expression:
        return models.Expression.objects.get(id=id)
    
      
    
    
    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def expressions(self, info: Info,
        filters: filters.ExpressionFilter | None = strawberry.UNSET,
        pagination: OffsetPaginationInput | None = strawberry.UNSET,
    ) -> list[types.Expression]:
        if types is strawberry.UNSET:
            view_relations = [
                "label_accessors",
                "image_accessors",
            ]
        else:
            view_relations = [kind.value for kind in types]

        results = []

        base = models.Table.objects.get(id=self._table_id)

        for relation in view_relations:
            qs = (
                getattr(base, relation)
                .filter(keys__contains=[self._duckdb_column[0]])
                .all()
            )

            # apply filters if defined
            if filters is not strawberry.UNSET:
                qs = strawberry_django.filters.apply(filters, qs, info)

            results.append(qs)

        return list(chain(*results))
    
    
    

    @strawberry.django.field(permission_classes=[IsAuthenticated])
    def reagent(self, info: Info, id: ID) -> types.Reagent:
        print(id)
        return models.Reagent.objects.get(id=id)

    @strawberry.django.field(permission_classes=[])
    def node(self, info: Info, id: ID) -> types.Node:

        return types.Node(
            _value=age.get_age_entity(age.to_graph_id(id), age.to_entity_id(id))
        )

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
    
    
    

    create_expression = strawberry_django.mutation(
        resolver=mutations.create_expression, description="Create a new expression"
    )
    update_expression = strawberry_django.mutation(
        resolver=mutations.update_expression,
        description="Update an existing expression",
    )
    delete_expression = strawberry_django.mutation(
        resolver=mutations.delete_expression,
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
