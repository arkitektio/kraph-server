from typing import cast

import strawberry
from kante.types import Info

from api import inputs, types
from core import models
from datalayer import models as dl_models
from graph_engine.materialize import re_materialize_structure_relation_category


def create_structure_relation_category(
    info: Info,
    input: inputs.CreateStructureRelationDefinitionInput,
) -> types.StructureRelationCategory:
    """GraphQL mutation wrapper for creating structure relation categories."""

    model = input.to_pydantic()  # Validate input with Pydantic models

    if model.color:
        assert len(model.color) == 3 or len(model.color) == 4, "Color must be a list of 3 or 4 values RGBA"

    media_store = None
    if model.image:
        media_store = dl_models.MediaStore.objects.get(id=model.image)

    vocab, created = models.StructureRelationCategory.objects.update_or_create(
        graph_id=model.graph,
        age_name=model.key,
        key=model.key,
        defaults=dict(
            description=model.description,
            image=media_store,
            label=model.label if model.label else model.key,
            property_definitions=[pdef.model_dump() for pdef in model.properties] or [],
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

    if model.tags:
        vocab.tags.clear()
        for tag in model.tags:
            tag_obj, _ = models.CategoryTag.objects.get_or_create(value=tag, graph=vocab.graph.id)
            vocab.tags.add(tag_obj)

    if model.pin is not None:
        if model.pin:
            vocab.pinned_by.add(info.context.request.user)
        else:
            vocab.pinned_by.remove(info.context.request.user)

    re_materialize_structure_relation_category(vocab.graph, vocab)

    return cast(types.StructureRelationCategory, vocab)


def update_structure_relation_category(info: Info, input: inputs.UpdateStructureRelationDefinitionInput) -> types.StructureRelationCategory:
    """GraphQL mutation wrapper for updating structure relation categories."""
    model = input.to_pydantic()  # Validate input with Pydantic models

    item = models.StructureRelationCategory.objects.get(id=model.id)

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

    if model.tags:
        item.tags.clear()
        for tag in model.tags:
            tag_obj, _ = models.CategoryTag.objects.get_or_create(value=tag, graph=item.graph.id)
            item.tags.add(tag_obj)

    if model.pin is not None:
        if model.pin:
            item.pinned_by.add(info.context.request.user)
        else:
            item.pinned_by.remove(info.context.request.user)

    item.save()

    # TODO: Rematerialize all entities of this category if properties were updated
    # We should do this asynchronously in the background and notify the user when it's done, since it could take a while for large graphs with many entities in this category

    return item


def delete_structure_relation_category(
    info: Info,
    input: inputs.DeleteStructureRelationDefinitionInput,
) -> strawberry.ID:
    model = input.to_pydantic()  # Validate input with Pydantic models
    item = models.StructureRelationCategory.objects.get(id=model.id)
    item.delete()
    return model.id
