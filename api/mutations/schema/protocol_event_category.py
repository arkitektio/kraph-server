from typing import cast

import strawberry
from kante.types import Info

from api import context, inputs, types
from core import enums, models
from datalayer import models as dl_models
from evidence import writer
from ._guards import delete_or_explain, refuse_bad_color
from .._scoped import accessible_graph, schema_graph, schema_scoped, scoped
from ._rematerialize import fingerprint, rematerialize_if_moved


def create_protocol_event_category(
    info: Info,
    input: inputs.CreateProtocolEventCategoryInput,
) -> types.ProtocolEventCategory:
    """GraphQL mutation wrapper for creating entity categories."""

    model = input.to_pydantic()  # Validate input with Pydantic models

    refuse_bad_color(model.color)

    media_store = None
    if model.image:
        media_store = dl_models.MediaStore.objects.get(id=model.image)

    graph = schema_graph(info, model.graph)
    # Keyed on `(graph, key)`, which is the pair `Category` is unique on —
    # and `key` is what a claim names. This used to key on `(graph, age_name)`
    # and never set `key` at all, so every category created here landed with
    # an empty one.
    # `update_or_create`, so `properties` may be rewriting a category that
    # already draws vertices. Snapshotted before, because the write destroys the
    # old definition — see `_rematerialize`.
    existing = models.ProtocolEventCategory.objects.filter(graph=graph, key=model.key).first()
    before = fingerprint(existing) if existing else None

    vocab, created = models.ProtocolEventCategory.objects.update_or_create(
        graph=graph,
        key=model.key,
        defaults=dict(
            term=writer.ensure_term(graph.organization, enums.CategoryKindChoices.PROTOCOL_EVENT, model.key),
            age_name=model.key,
            description=model.description,
            image=media_store,
            label=model.label if model.label else model.key,
            property_definitions=[pdef.model_dump() for pdef in model.properties] or [],
            # The category's complete rule (RFC 0012). Empty means primitive.
            definition=model.definition.to_stored() if model.definition else {},
        ),
    )

    for ref in model.ontology_references:
        if ref.prefix:
            # Validate ontology reference exists in the database
            if not models.GraphOntology.objects.filter(prefix=ref.prefix).exists():
                raise ValueError(f"Ontology with prefix {ref.prefix} not found in database.")

            models.OntologyReference.objects.get_or_create(
                ontology=models.GraphOntology.objects.get(prefix=ref.prefix),
                graph_id=model.graph,
                category_key=model.key,
            )
        else:
            raise ValueError("Each ontology reference must have either an ontology_id or ontology_url.")

    if model.pin is not None:
        if model.pin:
            vocab.pinned_by.add(info.context.request.user)
        else:
            vocab.pinned_by.remove(info.context.request.user)

    if model.backfill:
        context.get_controller().backfill_category(vocab)

    if before is not None:
        # After the backfill, not instead of it: a backfill widens membership and
        # re-derives through `SET`, and only this path `REMOVE`s the keys a
        # dropped property left behind.
        rematerialize_if_moved(vocab, before)

    return cast(types.ProtocolEventCategory, vocab)


def update_protocol_event_category(info: Info, input: inputs.UpdateProtocolEventCategoryInput) -> types.ProtocolEventCategory:
    """GraphQL mutation wrapper for updating event categories."""
    model = input.to_pydantic()  # Validate input with Pydantic models

    item = schema_scoped(info, models.ProtocolEventCategory, model.id, what="protocol event category")
    refuse_bad_color(model.color)

    if model.image:
        media_store = dl_models.MediaStore.objects.get(
            id=model.image,
        )
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

    if dict(item.definition or {}) != meaning_before:
        # A rule change moves which events this category admits, whose
        # standings count, and which participation claims draw its edges; only
        # a rebuild moves that honestly.
        context.get_controller().rebuild_projection(item.graph)
    return item


def delete_protocol_event_category(
    info: Info,
    input: inputs.DeleteProtocolEventCategoryInput,
) -> strawberry.ID:
    model = input.to_pydantic()  # Validate input with Pydantic models
    item = schema_scoped(info, models.ProtocolEventCategory, model.id, what="protocol event category")
    delete_or_explain(item, what=f"protocol event category '{item.key}'", instead="Archive the events recorded under it first.")
    return model.id
