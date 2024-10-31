from kante.types import Info
import strawberry
from core import types, models, enums, scalars, age
import datetime

@strawberry.input
class RelationMetricInput:
    kind: strawberry.ID
    data_kind: enums.MetricDataType


@strawberry.input
class DeleteRelationMetricInput:
    id: strawberry.ID


@strawberry.input
class CreateRelationMetricInput:
    value: scalars.Metric 
    relation: strawberry.ID
    metric: strawberry.ID | None = None
    timepoint: datetime.datetime | None  = None


def create_relation_metric(
        info: Info,
        input: CreateRelationMetricInput,
) -> types.EntityRelation:
    metric = models.LinkedExpression.objects.get(id=input.metric)
    assert metric.kind == enums.ExpressionKind.RELATION_METRIC, "Expression needs to be of metric"


    relation_graph, edge_id = input.relation.split(":")

    id = age.create_age_relation_metric(metric.graph.age_name, metric.age_name, edge_id, input.value, timepoint=input.timepoint)

    print("RETURNED ID", id)

    return types.EntityRelation(_value=id)



