from kante.types import Info
import strawberry
from api import types, inputs, scalars
from core import models


def create_model(
    info: Info,
    input: inputs.CreateModelInput,
) -> types.Model:
    store = models.MediaStore.objects.get(id=input.model)
    store.fill_info()

    table = models.Model.objects.create(
        name=input.name,
        store=store,
    )

    return table
