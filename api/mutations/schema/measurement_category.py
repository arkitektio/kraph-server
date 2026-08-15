from typing import cast

import strawberry
from kante.types import Info

from api import inputs, types
from core import models
from graph_engine import input_models, materialize
from ._guards import delete_or_explain, refuse_edge_properties
from .._scoped import accessible_graph, scoped


def create_measurement_category(
    info: Info,
    input: inputs.CreateMeasurementDefinitionInput,
) -> types.MeasurementCategory:
    """GraphQL mutation wrapper for creating measurement categories."""

    model = input.to_pydantic()  # Validate input with Pydantic models

    # A measurement is an edge, and is not even drawn as one — it is read back
    # from its `Link` row. See `refuse_edge_properties`.
    refuse_edge_properties(model.key, getattr(model, "properties", None))

    graph = accessible_graph(info, model.graph)

    ent = models.MeasurementCategory.objects.create_from_measurement_definition(
        graph,
        definition=model,
    )

    materialize.re_materialize_measurement_relation_category(graph, ent)

    return cast(types.MeasurementCategory, ent)


def update_measurement_category(info: Info, input: inputs.UpdateMeasurementDefinitionInput) -> types.MeasurementCategory:
    """GraphQL mutation wrapper for updating measurement categories."""
    model = input.to_pydantic()

    item = scoped(info, models.MeasurementCategory, model.id, what="measurement category")

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
    item = scoped(info, models.MeasurementCategory, model.id, what="measurement category")
    delete_or_explain(item, what=f"measurement category '{item.key}'", instead="Archive the measurements asserted under it first.")
    materialize.re_materialize_measurement_relation_category(item.graph, item)
    return model.id
