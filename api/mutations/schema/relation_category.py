"""Declaring, changing and removing a relation category — a view's rule for an
edge between two entities.

The shared halves are `._category` (the request-bound part) and
`core.managers.RelationCategoryManager` (what the row is). What stays here is what
only a relation knows: its proxy, and that its input spells the property list
`property_definitions` where its siblings spell it `properties`.
"""

from typing import cast

import strawberry
from kante.types import Info

from api import inputs, types
from core import models
from ._category import create_category, delete_category, update_category
from ._guards import refuse_edge_properties


def create_relation_category(
    info: Info,
    input: inputs.CreateRelationCategoryInput,
) -> types.RelationCategory:
    """Declare a relation category in a view."""
    model = input.to_pydantic()

    # An edge carries no derived properties, and this resolver never reaches
    # `validate_derivation_rules` — so the refusal has to be repeated here, or the
    # single-category path stays the way to get an uncomputable rule stored.
    #
    # `property_definitions`, not `properties`. `CreateRelationCategoryInput`
    # extends `EntityDefinitionInput`, which names the field the first way; the
    # sibling structure-relation and measurement inputs name it the second. This
    # resolver read `model.properties` and so raised `AttributeError` on **every**
    # call — no test reaches this mutation, which is how it stayed that way.
    refuse_edge_properties(model.key, model.property_definitions)

    category = create_category(
        info,
        model,
        models.RelationCategory,
        models.RelationCategory.objects.create_from_relation_definition,
        node=False,
    )
    return cast(types.RelationCategory, category)


def update_relation_category(info: Info, input: inputs.UpdateRelationCategoryInput) -> types.RelationCategory:
    """Change a relation category's label, colour, image, pin or rule."""
    model = input.to_pydantic()
    item = update_category(
        info,
        model,
        models.RelationCategory,
        what="relation category",
        node=False,
        rebuild_on_rule_change=True,
    )
    return cast(types.RelationCategory, item)


def delete_relation_category(
    info: Info,
    input: inputs.DeleteRelationCategoryInput,
) -> strawberry.ID:
    """Remove a relation category, if no evidence still names it."""
    model = input.to_pydantic()
    return delete_category(
        info,
        model,
        models.RelationCategory,
        what="relation category",
        instead="Archive the relations asserted under it first.",
    )
