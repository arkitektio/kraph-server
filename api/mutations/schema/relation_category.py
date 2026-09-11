from typing import cast

import strawberry
from kante.types import Info

from api import context, inputs, types
from core import enums, models
from datalayer import models as dl_models
from evidence import writer
from ._guards import delete_or_explain, refuse_bad_color, refuse_edge_properties
from .._scoped import schema_graph, schema_scoped


def create_relation_category(
    info: Info,
    input: inputs.CreateRelationCategoryInput,
) -> types.RelationCategory:
    """GraphQL mutation wrapper for creating relation categories."""

    model = input.to_pydantic()  # Validate input with Pydantic models

    # An edge carries no derived properties, and this resolver never reaches
    # `validate_derivation_rules` — so the refusal has to be repeated here or the
    # single-category path stays the way to get an uncomputable rule stored.
    #
    # `property_definitions`, not `properties`. `CreateRelationCategoryInput`
    # extends `EntityDefinitionInput`, which names the field the first way; the
    # sibling structure-relation and measurement inputs name it the second. This
    # resolver read `model.properties` and so raised `AttributeError` on **every**
    # call — no test reaches this mutation, which is how it stayed that way.
    refuse_edge_properties(model.key, model.property_definitions)

    refuse_bad_color(model.color)

    media_store = None
    if model.image:
        media_store = dl_models.MediaStore.objects.get(id=model.image)

    graph = schema_graph(info, model.graph)
    # Keyed on `(graph, key)`, which is the pair `Category` is unique on —
    # and `key` is what a claim names. This used to key on `(graph, age_name)`
    # and never set `key` at all, so every category created here landed with
    # an empty one.
    vocab, created = models.RelationCategory.objects.update_or_create(
        graph=graph,
        key=model.key,
        defaults=dict(
            term=writer.ensure_term(graph.organization, enums.CategoryKindChoices.RELATION, model.key),
            age_name=model.key.upper(),
            description=model.description,
            image=media_store,
            label=model.label if model.label else model.key,
            # Always empty — `refuse_edge_properties` above has already rejected
            # anything else. Kept as a field rather than dropped so the column
            # keeps its shape, and so this reads as "an edge has none" rather
            # than as an oversight.
            property_definitions=[],
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

    return cast(types.EntityCategory, vocab)


def update_relation_category(info: Info, input: inputs.UpdateRelationCategoryInput) -> types.RelationCategory:
    """GraphQL mutation wrapper for updating relation categories."""
    model = input.to_pydantic()  # Validate input with Pydantic models

    item = schema_scoped(info, models.RelationCategory, model.id, what="relation category")

    refuse_bad_color(model.color)

    if model.image:
        media_store = dl_models.MediaStore.objects.get(
            id=model.image,
        )
    else:
        media_store = None

    item.label = model.label if model.label else item.label
    item.description = model.description if model.description else item.description
    item.color = model.color if model.color else item.color
    item.image = media_store if media_store else item.image

    # The category's rule (RFC 0009): replaced whole, cleared to primitive, or
    # left alone — the input refuses both at once.
    meaning_before = dict(item.definition or {})
    if getattr(model, "clear_definition", False):
        item.definition = {}
    elif getattr(model, "definition", None) is not None:
        item.definition = model.definition.to_stored()

    if model.pin is not None:
        if model.pin:
            item.pinned_by.add(info.context.request.user)
        else:
            item.pinned_by.remove(info.context.request.user)

    item.save()

    if dict(item.definition or {}) != meaning_before:
        # A rule change moves which claims draw this category's edges and whose
        # standings count for them; only a rebuild moves that honestly.
        context.get_controller().rebuild_projection(item.graph)

    # No rematerialization here, and none owed for the cosmetic fields. This resolver writes label,
    # description, colour, store and pins — none of which a vertex or an
    # edge carries — and `property_definitions` is not among them, so nothing in
    # the projection can have gone stale.
    #
    # Nor would it help if it were. `projector.project_edges` writes exactly
    # `category_id` and `__assertion_count` onto an edge: no derivation rule has
    # ever run for a relation category, so the `properties` this API accepts on
    # `createRelationCategory` are stored and never materialized. That is a real
    # gap — the same family as the read-time derivation Tier 0 removed for nodes
    # — and it is recorded in `docs/ARCHITECTURE.md` rather than papered over
    # with a redraw that would have nothing to redraw.

    return item


def delete_relation_category(
    info: Info,
    input: inputs.DeleteRelationCategoryInput,
) -> strawberry.ID:
    model = input.to_pydantic()  # Validate input with Pydantic models
    item = schema_scoped(info, models.RelationCategory, model.id, what="relation category")
    delete_or_explain(item, what=f"relation category '{item.key}'", instead="Archive the relations asserted under it first.")
    return model.id
