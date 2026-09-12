"""Declaring, changing and removing a natural event category — a view's rule for
an event that arises in the system itself (mitosis, apoptosis).

Everything that is not specific to *this* kind lives in `._category`; what an
event category *is* lives in `core.managers.EventCategoryManager`, which
`materialize` uses too. This module is the part that only natural events know:
which proxy, which words the refusals use.

History: this module and `protocol_event_category.py` were 115 diff lines apart
over 136 lines, and the differences were slips rather than kinds — most seriously,
this one built its `defaults` by hand and left `definition` out, so a natural
event category declared with a rule stored none and folded as primitive forever
after. Neither module could see the other. Both are the same five lines now.
"""

from typing import cast

import strawberry
from kante.types import Info

from api import inputs, types
from core import models
from ._category import create_category, delete_category, update_category


def create_natural_event_category(
    info: Info,
    input: inputs.CreateNaturalEventCategoryInput,
) -> types.NaturalEventCategory:
    """Declare a natural event category in a view."""
    model = input.to_pydantic()
    category = create_category(
        info,
        model,
        models.NaturalEventCategory,
        models.NaturalEventCategory.objects.create_from_event_definition,
        node=True,
    )
    return cast(types.NaturalEventCategory, category)


def update_natural_event_category(info: Info, input: inputs.UpdateNaturalEventCategoryInput) -> types.NaturalEventCategory:
    """Change a natural event category's label, colour, image, pin or rule."""
    model = input.to_pydantic()
    item = update_category(
        info,
        model,
        models.NaturalEventCategory,
        what="natural event category",
        node=True,
        rebuild_on_rule_change=True,
    )
    return cast(types.NaturalEventCategory, item)


def delete_natural_event_category(
    info: Info,
    input: inputs.DeleteNaturalEventCategoryInput,
) -> strawberry.ID:
    """Remove a natural event category, if no evidence still names it."""
    model = input.to_pydantic()
    return delete_category(
        info,
        model,
        models.NaturalEventCategory,
        what="natural event category",
        instead="Archive the events recorded under it first.",
    )
