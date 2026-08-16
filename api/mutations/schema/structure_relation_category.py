from typing import cast

import strawberry
from kante.types import Info

from api import inputs, types
from core import enums, models
from evidence import writer
from datalayer import models as dl_models
from ._guards import delete_or_explain, refuse_edge_properties
from .._scoped import accessible_graph, scoped


def create_structure_relation_category(
    info: Info,
    input: inputs.CreateStructureRelationDefinitionInput,
) -> types.StructureRelationCategory:
    """GraphQL mutation wrapper for creating structure relation categories."""

    model = input.to_pydantic()  # Validate input with Pydantic models

    # An edge carries no derived properties, and this resolver never reaches
    # `validate_derivation_rules` — see `refuse_edge_properties`.
    refuse_edge_properties(model.key, model.properties)

    if model.color:
        assert len(model.color) == 3 or len(model.color) == 4, "Color must be a list of 3 or 4 values RGBA"

    media_store = None
    if model.image:
        media_store = dl_models.MediaStore.objects.get(id=model.image)

    graph = accessible_graph(info, model.graph)
    # Keyed on `(graph, key)`, which is the pair `Category` is unique on —
    # and `key` is what a claim names. This used to key on `(graph, age_name)`
    # and never set `key` at all, so every category created here landed with
    # an empty one.
    vocab, created = models.StructureRelationCategory.objects.update_or_create(
        graph=graph,
        key=model.key,
        defaults=dict(
            term=writer.ensure_term(graph.organization, enums.CategoryKindChoices.STRUCTURE_RELATION, model.key),
            age_name=model.key.upper(),
            description=model.description,
            image=media_store,
            label=model.label if model.label else model.key,
            # Always empty — `refuse_edge_properties` has already rejected
            # anything else. See `create_relation_category` for the same note.
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


    return cast(types.StructureRelationCategory, vocab)


def update_structure_relation_category(info: Info, input: inputs.UpdateStructureRelationDefinitionInput) -> types.StructureRelationCategory:
    """GraphQL mutation wrapper for updating structure relation categories."""
    model = input.to_pydantic()  # Validate input with Pydantic models

    item = scoped(info, models.StructureRelationCategory, model.id, what="structure relation category")

    if model.color:
        assert len(model.color) == 3 or len(model.color) == 4, "Color must be a list of 3 or 4 values RGBA"

    if model.image:
        media_store = models.MediaStore.objects.get(
            id=model.image,
        )
    else:
        media_store = None

    item.label = model.label if model.label else item.label
    item.description = model.description if model.description else item.description
    item.color = model.color if model.color else item.color
    item.store = media_store if media_store else item.store

    if model.pin is not None:
        if model.pin:
            item.pinned_by.add(info.context.request.user)
        else:
            item.pinned_by.remove(info.context.request.user)

    item.save()

    # No rematerialization owed, for the same two reasons as
    # `update_relation_category`: this resolver writes no `property_definitions`,
    # and a structure relation is an edge, which `projector.project_edges` draws
    # with `category_id` and `__assertion_count` and nothing derived.

    return item


def delete_structure_relation_category(
    info: Info,
    input: inputs.DeleteStructureRelationDefinitionInput,
) -> strawberry.ID:
    model = input.to_pydantic()  # Validate input with Pydantic models
    item = scoped(info, models.StructureRelationCategory, model.id, what="structure relation category")
    delete_or_explain(item, what=f"structure relation category '{item.key}'", instead="Archive the structure relations asserted under it first.")
    return model.id
