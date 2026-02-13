from typing import cast

import strawberry
from kante.types import Info

from api import inputs, types
from core import models


def create_structure_category(
    info: Info,
    input: inputs.CreateStructureDefinitionInput,
) -> types.StructureCategory:
    """GraphQL mutation wrapper for creating structure categories."""

    model = input.to_pydantic()  # Validate input with Pydantic models

    graph = models.Graph.objects.get(id=model.graph)

    ent = models.StructureCategory.objects.create_from_structure_definition(
        graph,
        definition=model,
    )

    return cast(types.StructureCategory, ent)


def update_structure_category(info: Info, input: inputs.UpdateStructureDefinitionInput) -> types.StructureCategory:
    """GraphQL mutation wrapper for updating structure categories."""
    model = input.to_pydantic()  # Validate input with Pydantic models

    item = models.StructureCategory.objects.get(id=model.id)

    if model.color:
        assert len(model.color) == 3 or len(model.color) == 4, "Color must be a list of 3 or 4 values RGBA"

    if model.image:
        media_store = models.MediaStore.objects.get(
            id=model.image,
        )
    else:
        media_store = None

    item.label = model.label if model.label else item.label
    item.description = model.description if model.description else item.description
    item.color = model.color if model.color else item.color
    item.store = media_store if media_store else item.store

    if model.tags:
        item.tags.clear()
        for tag in model.tags:
            tag_obj, _ = models.CategoryTag.objects.get_or_create(value=tag, graph=item.graph.id)
            item.tags.add(tag_obj)

    if model.pin is not None:
        if model.pin:
            item.pinned_by.add(info.context.request.user)
        else:
            item.pinned_by.remove(info.context.request.user)

    item.save()

    # TODO: Rematerialize all entities of this category if properties were updated
    # We should do this asynchronously in the background and notify the user when it's done, since it could take a while for large graphs with many entities in this category

    return item


def delete_structure_category(
    info: Info,
    input: inputs.DeleteStructureDefinitionInput,
) -> strawberry.ID:
    model = input.to_pydantic()  # Validate input with Pydantic models
    item = models.StructureCategory.objects.get(id=model.id)
    item.delete()
    return model.id
