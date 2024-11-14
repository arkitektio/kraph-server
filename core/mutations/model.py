from kante.types import Info
import strawberry
from core import types, models, age, scalars


@strawberry.input(description="Input type for creating a new model")
class CreateModelInput:
    name: str = strawberry.field(description="The name of the model")
    model: scalars.RemoteUpload = strawberry.field(
        description="The uploaded model file (e.g. .h5, .onnx, .pt)"
    )
    view: strawberry.ID | None = strawberry.field(
        description="Optional view ID to associate with the model", default=None
    )


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
