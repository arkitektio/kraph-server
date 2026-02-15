from typing import cast

import strawberry
from kante.types import Info

from api import inputs, types
from core import models


def create_measurement_category(
    info: Info,
    input: inputs.CreateRelationDefinitionInput,
) -> types.MeasurementCategory:
    """GraphQL mutation wrapper for creating measurement categories."""

    model = input.to_pydantic()

    if model.color:
        assert len(model.color) == 3 or len(model.color) == 4, "Color must be a list of 3 or 4 values RGBA"

    media_store = None
    if model.image:
        media_store = models.MediaStore.objects.get(id=model.image)

    category, _ = models.MeasurementCategory.objects.update_or_create(
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
        category.tags.clear()
        for tag in model.tags:
            tag_obj, _ = models.CategoryTag.objects.get_or_create(value=tag, graph=category.graph.id)
            category.tags.add(tag_obj)

    if model.pin is not None:
        if model.pin:
            category.pinned_by.add(info.context.request.user)
        else:
            category.pinned_by.remove(info.context.request.user)

    return cast(types.MeasurementCategory, category)


def update_measurement_category(info: Info, input: inputs.UpdateRelationDefinitionInput) -> types.MeasurementCategory:
    """GraphQL mutation wrapper for updating measurement categories."""
    model = input.to_pydantic()

    item = models.MeasurementCategory.objects.get(id=model.id)

    if model.color:
        assert len(model.color) == 3 or len(model.color) == 4, "Color must be a list of 3 or 4 values RGBA"

    if model.image:
        media_store = models.MediaStore.objects.get(id=model.image)
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


def delete_measurement_category(
    info: Info,
    input: inputs.DeleteRelationDefinitionInput,
) -> strawberry.ID:
    model = input.to_pydantic()
    item = models.MeasurementCategory.objects.get(id=model.id)
    item.delete()
    return model.id
