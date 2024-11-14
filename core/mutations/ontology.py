from kante.types import Info
import strawberry
from core import types, models, age
from django.db import connections
from contextlib import contextmanager


@strawberry.input(description="Input type for creating a new ontology")
class OntologyInput:
    name: str = strawberry.field(
        description="The name of the ontology (will be converted to snake_case)"
    )
    description: str | None = strawberry.field(
        default=None, description="An optional description of the ontology"
    )
    purl: str | None = strawberry.field(
        default=None, description="An optional PURL (Persistent URL) for the ontology"
    )
    image: strawberry.ID | None = strawberry.field(
        default=None, description="An optional ID reference to an associated image"
    )


@strawberry.input(description="Input type for updating an existing ontology")
class UpdateOntologyInput:
    id: strawberry.ID = strawberry.field(description="The ID of the ontology to update")
    name: str | None = strawberry.field(
        default=None,
        description="New name for the ontology (will be converted to snake_case)",
    )
    description: str | None = strawberry.field(
        default=None, description="New description for the ontology"
    )
    purl: str | None = strawberry.field(
        default=None, description="New PURL (Persistent URL) for the ontology"
    )
    image: strawberry.ID | None = strawberry.field(
        default=None, description="New ID reference to an associated image"
    )


@strawberry.input(description="Input type for deleting an ontology")
class DeleteOntologyInput:
    id: strawberry.ID = strawberry.field(description="The ID of the ontology to delete")


def to_snake_case(string):
    return string.replace(" ", "_").lower()


def create_ontology(
    info: Info,
    input: OntologyInput,
) -> types.Ontology:

    if input.image:
        media_store = models.MediaStore.objects.get(
            id=input.image,
        )
    else:
        media_store = None

    item, _ = models.Ontology.objects.update_or_create(
        name=to_snake_case(input.name),
        defaults=dict(
            description=input.description or "", store=media_store, purl=input.purl
        ),
    )

    return item


def update_ontology(info: Info, input: UpdateOntologyInput) -> types.Ontology:
    item = models.Ontology.objects.get(id=input.id)

    if input.image:
        media_store = models.MediaStore.objects.get(
            id=input.image,
        )
    else:
        media_store = None

    item.name = input.name or item.name
    item.description = input.description or item.description
    item.purl = input.purl or item.purl
    item.store = media_store or item.store
    item.save()

    return item


def delete_ontology(
    info: Info,
    input: DeleteOntologyInput,
) -> strawberry.ID:
    item = models.Ontology.objects.get(id=input.id)
    item.delete()

    return input.id
