from kante.types import Info
import strawberry
from core import types, models, age, scalars
import uuid


@strawberry.input(description="Input type for creating a new entity")
class EntityInput:
    entity_category: strawberry.ID = strawberry.field(description="The ID of the kind (LinkedExpression) to create the entity from")
    name: str | None = strawberry.field(default=None, description="Optional name for the entity")
    external_id: str | None = strawberry.field(
        default=None,
        description="An optional external ID for the entity (will upsert if exists)",
    )
    pinned: bool | None = strawberry.field(default=None, description="Whether the entity should be pinned")
    variables: scalars.MetricMap | None = strawberry.field(
        default=None,
        description="Optional variables to set on the entity upon creation",
    )
    properties: scalars.MetricMap | None = strawberry.field(
        default=None,
        description="Optional properties to set on the entity upon creation. Properties will be validated and serialized according to their definitions.",
    )


@strawberry.input
class DeleteEntityInput:
    id: strawberry.ID


def create_entity(
    info: Info,
    input: EntityInput,
) -> types.Entity:
    entity_category = models.EntityCategory.objects.get(id=input.entity_category)

    user_id = str(info.context.request.user.id) if info.context.request.user and hasattr(info.context.request.user, "id") else None

    entity = age.create_age_entity(
        category=entity_category,
        name=input.name,
        external_id=input.external_id,
        properties=input.properties,
        created_by=user_id,
    )

    return types.Entity(_value=entity)


@strawberry.input(description="Input type for creating a new entity")
class UpdateEntityInput:
    id: strawberry.ID
    name: str | None = strawberry.field(default=None, description="Optional name for the entity")
    external_id: str | None = strawberry.field(
        default=None,
        description="An optional external ID for the entity (will upsert if exists)",
    )
    tags: list[str] | None = strawberry.field(default=None, description="Optional tags for the entity")
    pinned: bool | None = strawberry.field(default=None, description="Whether the entity should be pinned by this user")


def update_entity(
    info: Info,
    input: UpdateEntityInput,
) -> types.Entity:
    entity = age.update_entity(age.to_graph_id(input.id), age.to_entity_id(input.id), external_id=input.external_id, tags=input.tags, pinned_by=[str(info.context.request.user.id)] if input.pinned else None)
    return types.Entity(_value=entity)


def delete_entity(
    info: Info,
    input: DeleteEntityInput,
) -> strawberry.ID:
    raise NotImplementedError("Not implemented yet")
    return input.id
