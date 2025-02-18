


from kante.types import Info
import strawberry
from core import types, models, age, enums


@strawberry.input
class GraphViewInput:
    graph: strawberry.ID
    kind: enums.GraphViewKind
    name: str
    description: str | None = None
    

@strawberry.input
class DeleteGraphViewInput:
    id: strawberry.ID


def create_graph_view(
    info: Info,
    input: GraphViewInput,
) -> types.GraphView:

    item, created = models.Graph.objects.update_or_create(
        age_name=f"{input.name.replace(' ', '_').lower()}",
        defaults=dict(
            experiment=(
                models.Experiment.objects.get(id=input.experiment)
                if input.experiment
                else None
            ),
            name=input.name,
            user=info.context.request.user,
            description=input.description,
        ),
    )
    if created:
        try:
            age.create_age_graph(item.age_name)
        except Exception as e:
            item.delete()
            raise e

    return item


def update_graph(info: Info, input: UpdateGraphInput) -> types.Graph:
    item = models.Graph.objects.get(id=input.id)

    item.description = input.description if input.description else item.description
    item.name = input.name if input.name else item.name

    item.save()
    return item


def delete_graph(
    info: Info,
    input: DeleteGraphInput,
) -> strawberry.ID:
    item = models.Graph.objects.get(id=input.id)

    try:
        age.delete_age_graph(item.age_name)
    except Exception as e:
        pass

    item.delete()
    return input.id
