from kante.types import Info
import strawberry
from core import types, models, scalars
from strawberry import ID
import strawberry_django


def linked_expression_by_agename(
    info: Info,
    age_name: str,
    graph_id: ID,
) -> types.LinkedExpression:
    view = models.LinkedExpression.objects.get(age_name=age_name, graph_id=graph_id)
    return view