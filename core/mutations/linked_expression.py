from kante.types import Info
import strawberry
from core import types, models, enums
from core import age


@strawberry.input
class LinkExpressionInput:
    expression: strawberry.ID
    graph: strawberry.ID
    color: list[int] | None = None


@strawberry.input
class DeleteLinkedExpressionInput:
    id: strawberry.ID



def link_expression(
    info: Info,
    input: LinkExpressionInput,
) -> types.LinkedExpression:
    
    expression = models.Expression.objects.get(id=input.expression)
    graph = models.Graph.objects.get(id=input.graph)

    if input.color:
        assert len(input.color) == 3 or len(input.color) == 4, "Color must be a list of 3 or 4 values RGBA"


    item, _ = models.LinkedExpression.objects.update_or_create(
        expression=expression,
        graph=graph,
        age_name=expression.age_name,
        defaults=dict(      
            kind=expression.kind,
            color=input.color or expression.color,
            metric_kind=expression.metric_kind,
        )
    )

    if item.kind == enums.ExpressionKind.ENTITY:
        age.create_age_entity_kind(graph.age_name, item.age_name)

    elif item.kind == enums.ExpressionKind.RELATION:
        age.create_age_relation_kind(graph.age_name, item.age_name)

    elif item.kind == enums.ExpressionKind.METRIC:
        pass

    elif item.kind == enums.ExpressionKind.RELATION_METRIC:
        pass

    else:
        raise ValueError("Invalid kind")

   
    

    return item


def unlink_expression(
    info: Info,
    input: DeleteLinkedExpressionInput,
) -> strawberry.ID:
    item = models.LinkedExpression.objects.get(id=input.id)
    item.delete()
    raise NotImplementedError("Not implemented yet")
    return input.id



@strawberry.input
class PinLinkedExpressionInput:
    id: strawberry.ID
    pin: bool | None = None


def pin_linked_expression(
    info: Info,
    input: PinLinkedExpressionInput,
) -> types.LinkedExpression:
    
    if input.pin is not None:

        if input.pin:
            item = models.LinkedExpression.objects.get(id=input.id)
            item.pinned_by.add(info.context.request.user)
            item.save()

        else:
            item = models.LinkedExpression.objects.get(id=input.id)
            item.pinned_by.remove(info.context.request.user)
            item.save()

    else:
        # toggle pin
        item = models.LinkedExpression.objects.get(id=input.id)
        if info.context.request.user in item.pinned_by.all():
            item.pinned_by.remove(info.context.request.user)
        else:
            item.pinned_by.add(info.context.request.user)
        item.save()

    return item



