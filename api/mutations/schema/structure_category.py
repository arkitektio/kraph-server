"""Mounting, changing and unmounting a structure kind in a view (RFC 0027).

A STRUCTURE category is the vertex label a view draws an external datum under: the
identifier it mounts (`@mikro/arraylens`) named here by a key (`Image`). A structure
relation's ends may only name identifiers the view mounts, so unmounting one that a
structure-relation category still names is refused by the database (`PROTECT` on the
kind is the organization's; the end check is `core.managers.refuse_unmounted_ends`).
"""

from typing import cast

import strawberry
from kante.types import Info

from api import context, inputs, types
from core import models
from ._category import create_category, delete_category, update_category
from .._scoped import schema_scoped


def create_structure_category(info: Info, input: inputs.CreateStructureCategoryInput) -> types.StructureCategory:
    """Mount a structure kind into a view."""
    model = input.to_pydantic()
    category = create_category(info, model, models.StructureCategory, models.StructureCategory.objects.create_from_structure_definition, node=False)
    if models.StructureRelationCategory.objects.filter(graph_id=category.graph_id).exists():
        # An open end admits every mounted kind, so the claims it already holds about
        # this one are owed vertices and edges now, as an unmount owes their removal.
        context.get_controller().rebuild_projection(category.graph)
    return cast(types.StructureCategory, category)


def update_structure_category(info: Info, input: inputs.UpdateStructureCategoryInput) -> types.StructureCategory:
    """Change a mounted structure kind's label, description, colour, image or pin."""
    model = input.to_pydantic()
    item = update_category(info, model, models.StructureCategory, what="structure category", node=False, rebuild_on_rule_change=False)
    return cast(types.StructureCategory, item)


def delete_structure_category(info: Info, input: inputs.DeleteStructureCategoryInput) -> strawberry.ID:
    """Unmount a structure kind, refused while a structure-relation category of the view names its identifier.

    `schema_scoped` first: the id arrives from the client, and the refusal names the view's
    words, which another organization must not learn by guessing a primary key.
    """
    model = input.to_pydantic()
    item = schema_scoped(info, models.StructureCategory, model.id, what="structure category")
    identifier = item.identifier
    naming = [category.key for category in models.StructureRelationCategory.objects.filter(graph_id=item.graph_id) if identifier in {*(category.source_definition_model.identifiers or []), *(category.target_definition_model.identifiers or [])}]
    if naming:
        raise ValueError(f"{identifier} is named by {', '.join(sorted(naming))}: remove it from their ends before unmounting it")
    graph = item.graph
    deleted = delete_category(info, model, models.StructureCategory, what="structure category", instead="Remove it from the structure relations that name it first.")
    if models.StructureRelationCategory.objects.filter(graph=graph).exists():
        # An open end admitted every mounted kind, this one included: its vertices
        # and their edges go, and only a rebuild removes a label honestly.
        context.get_controller().rebuild_projection(graph)
    return deleted
