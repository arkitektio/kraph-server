"""Declaring, changing and removing a measurement category — a view's rule for the
edge from a structure to the entity it measures.

Like a structure relation, a measurement category draws nothing, so a rule change
owes no rebuild: the claim lists read the rules live and the vocabulary index
follows the category-save signal.
"""

from typing import cast

import strawberry
from kante.types import Info

from api import inputs, types
from core import models
from ._category import create_category, delete_category, update_category
from ._guards import refuse_edge_properties


def create_measurement_category(
    info: Info,
    input: inputs.CreateMeasurementCategoryInput,
) -> types.MeasurementCategory:
    """Declare a measurement category in a view."""
    model = input.to_pydantic()

    # A measurement is an edge, and is not even drawn as one — it is read back
    # from its `Link` row. See `refuse_edge_properties`.
    refuse_edge_properties(model.key, getattr(model, "properties", None))

    category = create_category(
        info,
        model,
        models.MeasurementCategory,
        models.MeasurementCategory.objects.create_from_measurement_definition,
        node=False,
    )
    return cast(types.MeasurementCategory, category)


def update_measurement_category(info: Info, input: inputs.UpdateMeasurementCategoryInput) -> types.MeasurementCategory:
    """Change a measurement category's label, colour, image, pin or rule."""
    model = input.to_pydantic()
    item = update_category(
        info,
        model,
        models.MeasurementCategory,
        what="measurement category",
        node=False,
        rebuild_on_rule_change=False,
    )
    return cast(types.MeasurementCategory, item)


def delete_measurement_category(
    info: Info,
    input: inputs.DeleteMeasurementCategoryInput,
) -> strawberry.ID:
    """Remove a measurement category, if no evidence still names it."""
    model = input.to_pydantic()
    return delete_category(
        info,
        model,
        models.MeasurementCategory,
        what="measurement category",
        instead="Archive the measurements asserted under it first.",
    )
