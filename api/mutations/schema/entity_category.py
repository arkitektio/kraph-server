from typing import cast

import strawberry
from kante.types import Info

from api import inputs, types
from core import models
from datalayer import models as datalayer_models


def create_entity_category(
    info: Info,
    input: inputs.CreateEntityDefinitionInput,
) -> types.EntityCategory:
    """GraphQL mutation wrapper for creating entity categories."""

    model = input.to_pydantic()  # Validate input with Pydantic models

    graph = models.Graph.objects.get(id=model.graph)

    ent = models.EntityCategory.objects.create_from_entity_definition(
        graph,
        definition=model,
    )

    return cast(types.EntityCategory, ent)


def update_entity_category(info: Info, input: inputs.UpdateEntityDefinitionInput) -> types.EntityCategory:
    """GraphQL mutation wrapper for updating entity categories."""
    model = input.to_pydantic()  # Validate input with Pydantic models

    item = models.EntityCategory.objects.get(id=model.id)

    models.EntityCategory.objects.update_from_entity_definition(item, model)
    # TODO: Rematerialize all entities of this category if properties were updated
    # We should do this asynchronously in the background and notify the user when it's done, since it could take a while for large graphs with many entities in this category

    return item


def delete_entity_category(
    info: Info,
    input: inputs.DeleteEntityDefinitionInput,
) -> strawberry.ID:
    model = input.to_pydantic()  # Validate input with Pydantic models
    item = models.EntityCategory.objects.get(id=model.id)
    item.delete()
    return model.id
