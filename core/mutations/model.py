from kante.types import Info
import strawberry
from core import types, models,age, scalars



@strawberry.input
class CreateModelInput:
    name: str
    model: scalars.RemoteUpload
    view: strawberry.ID | None = None


def create_model(
    info: Info,
    input: CreateModelInput,
) -> types.Model:
    store = models.MediaStore.objects.get(id=input.model)
    store.fill_info()

    table = models.Model.objects.create(
        name=input.name,
        store=store,
    )

    return table

