from typing import cast

import strawberry
from kante.types import Info

from api import inputs, types
from core import age, models


def create_entity_category(
    info: Info,
    input: inputs.CreateEntityDefinitionInput,
) -> types.EntityCategory:
    """GraphQL mutation wrapper for creating entity categories."""
    
    model = input.to_pydantic()  # Validate input with Pydantic models

    
    
    
    if model.color:
        assert len(model.color) == 3 or len(model.color) == 4, "Color must be a list of 3 or 4 values RGBA"

    media_store = None
    if model.image:
        media_store = models.MediaStore.objects.get(id=model.image)
    
    vocab, created = models.EntityCategory.objects.update_or_create(
        graph_id=model.graph,
        age_name=model.key,
        defaults=dict(
            description=model.description,
            store=media_store,
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
            tag_obj, _ = models.CategoryTag.objects.get_or_create(value=tag, graph=item.graph.id)
            vocab.tags.add(tag_obj)

    if model.pin is not None:
        if model.pin:
            vocab.pinned_by.add(info.context.request.user)
        else:
            vocab.pinned_by.remove(info.context.request.user)


    return cast(types.EntityCategory, vocab)
    
    
    

def update_entity_category(info: Info, input: inputs.UpdateEntityDefinitionInput) -> types.EntityCategory:
    """ GraphQL mutation wrapper for updating entity categories."""
    model = input.to_pydantic()  # Validate input with Pydantic models
    
    item = models.EntityCategory.objects.get(id=model.id)

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
    return item


def delete_entity_category(
    info: Info,
    input: inputs.DeleteEntityDefinitionInput,
) -> strawberry.ID:
    model = input.to_pydantic()  # Validate input with Pydantic models
    item = models.EntityCategory.objects.get(id=model.id)
    item.delete()
    return model.id
