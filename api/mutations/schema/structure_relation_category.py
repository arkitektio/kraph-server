"""Declaring, changing and removing a structure relation category — a view's rule
for an edge between two structures.

Its claims are drawn as edges between structure vertices (RFC 0027), so a rule
change moves which edges exist and rebuilds the view, as it does for relations. Its
ends may only name identifiers the view mounts (`core.managers.refuse_unmounted_ends`).
"""

from typing import cast

import strawberry
from kante.types import Info

from api import inputs, types
from core import models
from ._category import create_category, delete_category, update_category
from ._guards import refuse_edge_properties


def create_structure_relation_category(
    info: Info,
    input: inputs.CreateStructureRelationCategoryInput,
) -> types.StructureRelationCategory:
    """Declare a structure relation category in a view."""
    model = input.to_pydantic()

    # An edge carries no derived properties, and this resolver never reaches
    # `validate_derivation_rules` — see `refuse_edge_properties`.
    refuse_edge_properties(model.key, model.properties)

    category = create_category(
        info,
        model,
        models.StructureRelationCategory,
        models.StructureRelationCategory.objects.create_from_structure_relation_definition,
        node=False,
    )
    return cast(types.StructureRelationCategory, category)


def update_structure_relation_category(info: Info, input: inputs.UpdateStructureRelationCategoryInput) -> types.StructureRelationCategory:
    """Change a structure relation category's label, colour, image, pin or rule."""
    model = input.to_pydantic()
    item = update_category(
        info,
        model,
        models.StructureRelationCategory,
        what="structure relation category",
        node=False,
        rebuild_on_rule_change=True,
    )
    return cast(types.StructureRelationCategory, item)


def delete_structure_relation_category(
    info: Info,
    input: inputs.DeleteStructureRelationCategoryInput,
) -> strawberry.ID:
    """Remove a structure relation category, if no evidence still names it."""
    model = input.to_pydantic()
    return delete_category(
        info,
        model,
        models.StructureRelationCategory,
        what="structure relation category",
        instead="Archive the structure relations asserted under it first.",
    )
