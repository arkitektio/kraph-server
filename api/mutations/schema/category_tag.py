from typing import cast

import strawberry
from kante.types import Info

from api import inputs, types
from core import models


def create_category_tag(
    info: Info,
    input: inputs.CreateCategoryTagInput,
) -> types.CategoryTag:
    model = input.to_pydantic()

    item, _ = models.CategoryTag.objects.update_or_create(
        graph_id=model.graph,
        value=model.value,
        defaults={
            "name": model.name,
            "description": model.description,
        },
    )

    return cast(types.CategoryTag, item)


def update_category_tag(
    info: Info,
    input: inputs.UpdateCategoryTagInput,
) -> types.CategoryTag:
    model = input.to_pydantic()
    item = models.CategoryTag.objects.get(id=model.id)

    if model.value is not None:
        item.value = model.value
    if model.name is not None:
        item.name = model.name
    if model.description is not None:
        item.description = model.description

    item.save()

    return cast(types.CategoryTag, item)


def archive_category_tag(
    info: Info,
    input: inputs.ArchiveCategoryTagInput,
) -> types.CategoryTag:
    model = input.to_pydantic()
    item = models.CategoryTag.objects.get(id=model.id)
    item.delete()
    return cast(types.CategoryTag, item)


def delete_category_tag(
    info: Info,
    input: inputs.DeleteCategoryTagInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = models.CategoryTag.objects.get(id=model.id)
    item.delete()
    return strawberry.ID(str(model.id))
