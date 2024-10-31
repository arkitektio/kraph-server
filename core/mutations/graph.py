from kante.types import Info
import strawberry
from core import types, models,age


@strawberry.input
class GraphInput:
    name: str
    experiment: strawberry.ID | None = None
    description: str | None = None

@strawberry.input
class UpdateGraphInput:
    id: str
    name: str | None = None
    description: str | None = None
    experiment: strawberry.ID | None = None

@strawberry.input
class DeleteGraphInput:
    id: strawberry.ID



def create_graph(
    info: Info,
    input: GraphInput,
) -> types.Graph:
    item, created = models.Graph.objects.update_or_create(
        age_name=f"{input.name.replace(' ', '_').lower()}",
        defaults=dict(
            experiment=models.Experiment.objects.get(id=input.experiment) if input.experiment else None,
            name=input.name,
            user=info.context.request.user,
            description=input.description,
        )
    )
    if created:
        age.create_age_graph(item.age_name)

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

    age.delete_age_graph(item.age_name)
    item.delete()
    return input.id

