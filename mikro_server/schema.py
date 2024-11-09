from kante.types import Info
from typing import AsyncGenerator
import strawberry
from strawberry_django.optimizer import DjangoOptimizerExtension
from core.datalayer import DatalayerExtension
from strawberry import ID
from kante.directives import upper, replace, relation
from strawberry.permission import BasePermission
from typing import Any, Type
from core import types, models
from core import mutations
from core import queries
from core import subscriptions
from strawberry.field_extensions import InputMutationExtension
import strawberry_django
from koherent.strawberry.extension import KoherentExtension
from authentikate.strawberry.permissions import IsAuthenticated
from core import age

@strawberry.type
class Query:
    

    entities: list[types.Entity] = strawberry_django.field()
    linked_expressions: list[types.LinkedExpression] = strawberry_django.field()
    graphs: list[types.Graph] = strawberry_django.field()
    expressions: list[types.Expression] = strawberry_django.field()
    ontologies: list[types.Ontology] = strawberry_django.field()

    knowledge_graph = strawberry_django.field(resolver=queries.knowledge_graph)
    entity_graph = strawberry_django.field(resolver=queries.entity_graph)
    linked_expression_by_agename = strawberry_django.field(
        resolver=queries.linked_expression_by_agename
    )



    entities: list[types.Entity] = strawberry_django.field(resolver=queries.entities)
    entity_relations: list[types.EntityRelation] = strawberry_django.field(resolver=queries.entity_relations)


  
    @strawberry.django.field(
        permission_classes=[IsAuthenticated]
    )
    def reagent(self, info: Info, id: ID) -> types.Reagent:
        print(id)
        return models.Reagent.objects.get(id=id)
    

    @strawberry.django.field(
        permission_classes=[]
    )
    def entity(self, info: Info, id: ID) -> types.Entity:
        

        return types.Entity(_value=age.get_age_entity(age.to_graph_id(id), age.to_entity_id(id)))
    


    @strawberry.django.field(
        permission_classes=[]
    )
    def entity_relation(self, info: Info, id: ID) -> types.EntityRelation:
        return types.EntityRelation(_value=age.get_age_entity_relation(age.to_graph_id(id), age.to_entity_id(id)))
    
    
    @strawberry.django.field(
        permission_classes=[IsAuthenticated]
    )
    def linked_expression(self, info: Info, id: ID) -> types.LinkedExpression:
        return models.LinkedExpression.objects.get(id=id)
    
    @strawberry.django.field(
        permission_classes=[IsAuthenticated]
    )
    def graph(self, info: Info, id: ID) -> types.Graph:
        return models.Graph.objects.get(id=id)
    
    
    @strawberry.django.field(
        permission_classes=[IsAuthenticated]
    )
    def ontology(self, info: Info, id: ID) -> types.Ontology:
        return models.Ontology.objects.get(id=id)
    
    
    @strawberry.django.field(
        permission_classes=[IsAuthenticated]
    )
    def protocol(self, info: Info, id: ID) -> types.Protocol:
        return models.Protocol.objects.get(id=id)
    
    @strawberry.django.field(
        permission_classes=[IsAuthenticated]
    )
    def protocol_step(self, info: Info, id: ID) -> types.ProtocolStep:
        return models.ProtocolStep.objects.get(id=id)
    
    @strawberry.django.field(
        permission_classes=[IsAuthenticated]
    )
    def expression(self, info: Info, id: ID) -> types.Expression:
        return models.Expression.objects.get(id=id)
    
    @strawberry.django.field(
        permission_classes=[IsAuthenticated]
    )
    def protocol_step_template(self, info: Info, id: ID) -> types.ProtocolStepTemplate:
        return models.ProtocolStepTemplate.objects.get(id=id)
    
    @strawberry.django.field(
        permission_classes=[IsAuthenticated]
    )
    def my_active_graph(self, info: Info) -> types.Graph:
        return models.Graph.objects.filter(user=info.context.request.user).first()


@strawberry.type
class Mutation:
    create_graph = strawberry_django.mutation(
        resolver=mutations.create_graph,
    )
    update_graph = strawberry_django.mutation(
        resolver=mutations.update_graph,
    )

    delete_graph = strawberry_django.mutation(
        resolver=mutations.delete_graph,
    )

    create_entity_relation = strawberry_django.mutation(
        resolver=mutations.create_entity_relation,
    )

    create_entity_metric = strawberry_django.mutation(
        resolver=mutations.create_entity_metric,
    )
    create_relation_metric = strawberry_django.mutation(
        resolver=mutations.create_relation_metric,
    )


    attach_metrics_to_entities = strawberry_django.mutation(
        resolver=mutations.attach_metrics_to_entities,
    )

    create_reagent = strawberry_django.mutation(
        resolver=mutations.create_reagent,
    )




    pin_linked_expression = strawberry_django.mutation(
        resolver=mutations.pin_linked_expression,
    )

    # Protocol Step
    create_protocol_step = strawberry_django.mutation(
        resolver=mutations.create_protocol_step,
    )
    delete_protocol_step = strawberry_django.mutation(
        resolver=mutations.delete_protocol_step,
    )
    update_protocol_step = strawberry_django.mutation(
        resolver=mutations.update_protocol_step,
    )




    # Entity
    create_entity = strawberry_django.mutation(
        resolver=mutations.create_entity,
    )
    delete_entity = strawberry_django.mutation(
        resolver=mutations.delete_entity,
    )

    # EntityKind
    link_expression = strawberry_django.mutation(
        resolver=mutations.link_expression,
    )
    unlink_expression = strawberry_django.mutation(
        resolver=mutations.unlink_expression,
    )


    # Ontology
    create_ontology = strawberry_django.mutation(
        resolver=mutations.create_ontology,
    )
    delete_ontology = strawberry_django.mutation(
        resolver=mutations.delete_ontology,
    )
    update_ontology = strawberry_django.mutation(
        resolver=mutations.update_ontology,
    )

    # Ontology
    create_expression = strawberry_django.mutation(
        resolver=mutations.create_expression,
    )
    update_expression = strawberry_django.mutation(
        resolver=mutations.update_expression,
    )


    delete_expression= strawberry_django.mutation(
        resolver=mutations.delete_expression,
    )

    # Protocol
    create_protocol = strawberry_django.mutation(
        resolver=mutations.create_protocol,
    )
    delete_protocol = strawberry_django.mutation(
        resolver=mutations.delete_protocol,
    )

    #Protocol Step Template
    create_protocol_step_template = strawberry_django.mutation(
        resolver=mutations.create_protocol_step_template,
    )
    update_protocol_step_template = strawberry_django.mutation(
        resolver=mutations.update_protocol_step_template,
    )
    delete_protocol_step_template = strawberry_django.mutation(
        resolver=mutations.delete_protocol_step_template,
    )












@strawberry.type
class Subscription:
    
    @strawberry.subscription
    async def history_events(
        self,
        info: Info,
        user: str,
    ) -> AsyncGenerator[types.Entity, None]:
        """Join and subscribe to message sent to the given rooms."""
        raise NotImplementedError("This resolver is a placeholder and should be implemented by the developer")


    


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
)
