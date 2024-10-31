from kante.types import Info
import strawberry
from core import types, models
import uuid




@strawberry.input
class ExperimentInput:
    name: str
    description: str | None = None



@strawberry.input
class DeleteExperimentInput:
    id: strawberry.ID

@strawberry.input
class UpdateExperimentInput:
    id: strawberry.ID
    name: str
    description: str | None = None


def create_experiment(
    info: Info,
    input: ExperimentInput,
) -> types.Experiment:
    
    item, _ = models.Experiment.objects.get_or_create(
        name=input.name,
        defaults=dict(description=input.description)
    )

    return item


def delete_experiment(
    info: Info,
    input: DeleteExperimentInput,
) -> strawberry.ID:
    item = models.Experiment.objects.get(id=input.id)
    item.delete()
    return input.id

def update_experiment(
    info: Info,
    input: UpdateExperimentInput,
) -> types.Experiment:
    item = models.Experiment.objects.get(id=input.id)
    item.name = input.name
    item.description = input.description
    item.save()
    return item



