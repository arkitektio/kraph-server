"""Declaring, changing and removing an entity category — a view's rule for a word
naming a thing rather than an event.

The one category family whose *update* is not the all-optional patch shape: an
entity category's update carries `property_definitions` and `instance_kind`, so it
passes its manager method to `._category.update_category` as the patch rather than
taking the default. Everything else is shared.
"""

from typing import cast

import strawberry
from kante.types import Info

from api import inputs, types
from core import models
from ._category import create_category, delete_category, update_category


def _patch_entity(item, model, manager) -> bool:
    """An entity category's patch is its manager's, because it writes more.

    The manager saves, so this reports `True` and `update_category` does not save
    again — a second `Category.save()` would refresh the graph's namespace a
    second time.
    """
    manager.update_from_entity_definition(item, model)
    return True


def create_entity_category(
    info: Info,
    input: inputs.CreateEntityCategoryInput,
) -> types.EntityCategory:
    """Declare an entity category in a view."""
    model = input.to_pydantic()
    category = create_category(
        info,
        model,
        models.EntityCategory,
        models.EntityCategory.objects.create_from_entity_definition,
        node=True,
    )
    return cast(types.EntityCategory, category)


def update_entity_category(info: Info, input: inputs.UpdateEntityCategoryInput) -> types.EntityCategory:
    """Change an entity category's label, colour, image, pin, properties or rule."""
    model = input.to_pydantic()
    item = update_category(
        info,
        model,
        models.EntityCategory,
        what="entity category",
        node=True,
        rebuild_on_rule_change=True,
        patch=_patch_entity,
    )
    return cast(types.EntityCategory, item)


def delete_entity_category(
    info: Info,
    input: inputs.DeleteEntityCategoryInput,
) -> strawberry.ID:
    """Remove an entity category, if no evidence still names it."""
    model = input.to_pydantic()
    return delete_category(
        info,
        model,
        models.EntityCategory,
        what="entity category",
        instead="Archive the entities first, or leave the category in place — an unused category costs nothing.",
    )
