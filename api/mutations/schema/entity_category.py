from typing import cast

import strawberry
from kante.types import Info

from api import context, inputs, types
from core import models
from datalayer import models as datalayer_models
from ._guards import delete_or_explain
from .._scoped import accessible_graph, scoped
from ._rematerialize import fingerprint, rematerialize_if_moved


def create_entity_category(
    info: Info,
    input: inputs.CreateEntityCategoryInput,
) -> types.EntityCategory:
    """GraphQL mutation wrapper for creating entity categories."""

    model = input.to_pydantic()  # Validate input with Pydantic models

    graph = accessible_graph(info, model.graph)

    # An upsert, so this may well be an edit to a category that already draws
    # vertices — the manager does not report which. See `_rematerialize`.
    existing = models.EntityCategory.objects.filter(graph=graph, key=model.key).first()
    before = fingerprint(existing) if existing else None

    ent = models.EntityCategory.objects.create_from_entity_definition(
        graph,
        definition=model,
    )

    if model.backfill:
        context.get_controller().backfill_category(ent)

    if before is not None:
        # After the backfill, not instead of it. A backfill widens *membership*
        # and re-derives through `SET`; only this path `REMOVE`s the keys a
        # dropped property left behind.
        rematerialize_if_moved(ent, before)

    return cast(types.EntityCategory, ent)


def update_entity_category(info: Info, input: inputs.UpdateEntityCategoryInput) -> types.EntityCategory:
    """GraphQL mutation wrapper for updating entity categories."""
    model = input.to_pydantic()  # Validate input with Pydantic models

    item = scoped(info, models.EntityCategory, model.id, what="entity category")

    # Before the write: nothing versions `property_definitions`, so the old
    # definition is unrecoverable one line later. See `_rematerialize`.
    before = fingerprint(item)

    models.EntityCategory.objects.update_from_entity_definition(item, model)

    # Synchronous, and unbounded in the size of the graph — see
    # `_rematerialize`'s module docstring for why that is the accepted limit and
    # what to run when it bites.
    rematerialize_if_moved(item, before)

    return item


def delete_entity_category(
    info: Info,
    input: inputs.DeleteEntityCategoryInput,
) -> strawberry.ID:
    model = input.to_pydantic()  # Validate input with Pydantic models
    item = scoped(info, models.EntityCategory, model.id, what="entity category")
    delete_or_explain(item, what=f"entity category '{item.key}'", instead="Archive the entities first, or leave the category in place — an unused category costs nothing.")
    return model.id
