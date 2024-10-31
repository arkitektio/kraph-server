from kante.types import Info
import strawberry
from core import types, models, age
from django.db import connections
from contextlib import contextmanager



@strawberry.input
class OntologyInput:
    name: str
    description: str | None = None
    purl: str | None = None
    image: strawberry.ID | None = None

@strawberry.input
class UpdateOntologyInput:
    id: strawberry.ID
    name: str | None = None
    description: str | None = None
    purl: str | None = None
    image: strawberry.ID | None = None


@strawberry.input
class DeleteOntologyInput:
    id: strawberry.ID


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
        description=input.description or "",
        store=media_store,
        purl=input.purl)
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

