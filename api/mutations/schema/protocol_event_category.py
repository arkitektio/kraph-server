"""Declaring, changing and removing a protocol event category — a view's rule for
an event applied from outside (a staining step, a protocol run).

The twin of `natural_event_category.py`, and deliberately identical to it below
the names: the two differ in what an event *is*, not in how a category for one is
written. That is enforced rather than hoped for —
`tests/view/test_a_category_declares_its_rule_on_creation.py` asserts both kinds
store a declared rule, because when these were two hand-written copies a field
could go missing from one and nothing would notice.
"""

from typing import cast

import strawberry
from kante.types import Info

from api import inputs, types
from core import models
from ._category import create_category, delete_category, update_category


def create_protocol_event_category(
    info: Info,
    input: inputs.CreateProtocolEventCategoryInput,
) -> types.ProtocolEventCategory:
    """Declare a protocol event category in a view."""
    model = input.to_pydantic()
    category = create_category(
        info,
        model,
        models.ProtocolEventCategory,
        models.ProtocolEventCategory.objects.create_from_event_definition,
        node=True,
    )
    return cast(types.ProtocolEventCategory, category)


def update_protocol_event_category(info: Info, input: inputs.UpdateProtocolEventCategoryInput) -> types.ProtocolEventCategory:
    """Change a protocol event category's label, colour, image, pin or rule."""
    model = input.to_pydantic()
    item = update_category(
        info,
        model,
        models.ProtocolEventCategory,
        what="protocol event category",
        node=True,
        rebuild_on_rule_change=True,
    )
    return cast(types.ProtocolEventCategory, item)


def delete_protocol_event_category(
    info: Info,
    input: inputs.DeleteProtocolEventCategoryInput,
) -> strawberry.ID:
    """Remove a protocol event category, if no evidence still names it."""
    model = input.to_pydantic()
    return delete_category(
        info,
        model,
        models.ProtocolEventCategory,
        what="protocol event category",
        instead="Archive the events recorded under it first.",
    )
