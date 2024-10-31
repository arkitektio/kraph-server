from kante.types import Info
import strawberry
from core import types, models, enums, scalars, age
import datetime


@strawberry.input
class CreateEntityMetricInput:
    value: scalars.Metric 
    entity: strawberry.ID
    metric: strawberry.ID
    timepoint: datetime.datetime | None  = None

@strawberry.input
class EntityValuePairInput:
    entity: strawberry.ID
    value: scalars.Metric



@strawberry.input
class AttachMetricsToEntitiesMetricInput:
    metric: strawberry.ID 
    pairs: list[EntityValuePairInput]

@strawberry.input
class DeleteEntityMetricInput:
    entity: strawberry.ID
    metric: strawberry.ID



def create_entity_metric(
        info: Info,
        input: CreateEntityMetricInput,
) -> types.Entity:

    metric = models.LinkedExpression.objects.get(id=input.metric)




    entity_graph, entity_id = input.entity.split(":")
        
        
    entity = age.create_age_metric(metric.graph.age_name, metric.age_name, entity_id, input.value, input.timepoint)



    return types.Entity(_value=entity)







def attach_metrics_to_entities(info: Info, input: AttachMetricsToEntitiesMetricInput) -> list[types.Entity]:
    metric = models.LinkedExpression.objects.get(id=input.metric)

    returned_entities = []

    for pair in input.pairs:


        entity_id = age.create_age_metric(metric.graph.age_name, metric.age_name, pair.entity, pair.value)
        returned_entities.append(types.Entity(_value=entity_id))

    return returned_entities
        

    
        
def delete_entity_metric(
    info: Info,
    input: DeleteEntityMetricInput,
) -> strawberry.ID:
    raise NotImplementedError("Not implemented yet")
    return input.id

