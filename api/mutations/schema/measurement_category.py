from typing import cast

import strawberry
from kante.types import Info

from api import inputs, types
from core import models
from datalayer import models as dl_models
from graph_engine import input_models, materialize
from ._guards import delete_or_explain, refuse_bad_color, refuse_edge_properties
from .._scoped import accessible_graph, schema_graph, schema_scoped, scoped


def create_measurement_category(
    info: Info,
    input: inputs.CreateMeasurementCategoryInput,
) -> types.MeasurementCategory:
    """GraphQL mutation wrapper for creating measurement categories."""

    model = input.to_pydantic()  # Validate input with Pydantic models

    # A measurement is an edge, and is not even drawn as one — it is read back
    # from its `Link` row. See `refuse_edge_properties`.
    refuse_edge_properties(model.key, getattr(model, "properties", None))

    graph = schema_graph(info, model.graph)

    ent = models.MeasurementCategory.objects.create_from_measurement_definition(
        graph,
        definition=model,
    )

    return cast(types.MeasurementCategory, ent)


def update_measurement_category(info: Info, input: inputs.UpdateMeasurementCategoryInput) -> types.MeasurementCategory:
    """GraphQL mutation wrapper for updating measurement categories."""
    model = input.to_pydantic()

    item = schema_scoped(info, models.MeasurementCategory, model.id, what="measurement category")

    refuse_bad_color(model.color)

    if model.image:
        media_store = dl_models.MediaStore.objects.get(id=model.image)
    else:
        media_store = None


    # The category's rule (RFC 0012): replaced whole, cleared to primitive, or
    # left alone — the input refuses both at once.
    meaning_before = dict(item.definition or {})
    if getattr(model, "clear_definition", False):
        item.definition = {}
    elif getattr(model, "definition", None) is not None:
        item.definition = model.definition.to_stored()

    item.label = model.label if model.label else item.label
    item.description = model.description if model.description else item.description
    item.color = model.color if model.color else item.color
    item.image = media_store if media_store else item.image

    if model.pin is not None:
        if model.pin:
            item.pinned_by.add(info.context.request.user)
        else:
            item.pinned_by.remove(info.context.request.user)

    item.save()

    # No rebuild on a rule change: nothing is drawn for this category — the
    # claim lists read the rules live (`links_for_category`), and the
    # vocabulary index follows via the category-save signal.
    del meaning_before

    return item


def delete_measurement_category(
    info: Info,
    input: inputs.DeleteMeasurementCategoryInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = schema_scoped(info, models.MeasurementCategory, model.id, what="measurement category")
    delete_or_explain(item, what=f"measurement category '{item.key}'", instead="Archive the measurements asserted under it first.")
    return model.id
