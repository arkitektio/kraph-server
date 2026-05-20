from typing import cast

import strawberry
from kante.types import Info

from api import inputs, types
from core import models
from graph_engine import input_models, materialize


def create_measurement_category(
    info: Info,
    input: inputs.CreateMeasurementDefinitionInput,
) -> types.MeasurementCategory:
    """GraphQL mutation wrapper for creating measurement categories."""

    model = input.to_pydantic()  # Validate input with Pydantic models

    graph = models.Graph.objects.get(id=model.graph)

    ent = models.MeasurementCategory.objects.create_from_measurement_definition(
        graph,
        definition=model,
    )

    materialize.re_materialize_measurement_relation_category(graph, ent)

    return cast(types.MeasurementCategory, ent)


def update_measurement_category(info: Info, input: inputs.UpdateMeasurementDefinitionInput) -> types.MeasurementCategory:
    """GraphQL mutation wrapper for updating measurement categories."""
    model = input.to_pydantic()

    item = models.MeasurementCategory.objects.get(id=model.id)

    if model.color:
        assert len(model.color) == 3 or len(model.color) == 4, "Color must be a list of 3 or 4 values RGBA"

    if model.image:
        media_store = models.MediaStore.objects.get(id=model.image)
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

    materialize.re_materialize_measurement_relation_category(item.graph, item)

    return item


def delete_measurement_category(
    info: Info,
    input: inputs.DeleteMeasurementDefinitionInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = models.MeasurementCategory.objects.get(id=model.id)
    item.delete()
    materialize.re_materialize_measurement_relation_category(item.graph, item)
    return model.id
