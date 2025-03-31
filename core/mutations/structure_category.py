from kante.types import Info
from core.datalayer import get_current_datalayer

import strawberry
from core import types, models, enums, scalars, manager, inputs
from core import age
from strawberry.file_uploads import Upload
from django.conf import settings
import re

# re for the scalar string in format "@{exernal_name}/{scalar_name_without_spaces_and_only_alphanumber_with_underscores_and_hypens}"
scalar_string_re = re.compile(
    r"@(?P<external_name>[a-zA-Z0-9_]+)/(?P<scalar_name>[a-zA-Z0-9_]+)"
)


@strawberry.input(description="Input for creating a new expression")
class StructureCategoryInput(inputs.CategoryInput):
    identifier: scalars.StructureIdentifier = strawberry.field(
        description="The label/name of the expression"
    )
    description: str | None = strawberry.field(
        default=None, description="A detailed description of the expression"
    )
    purl: str | None = strawberry.field(
        default=None, description="Permanent URL identifier for the expression"
    )
    color: list[int] | None = strawberry.field(
        default=None, description="RGBA color values as list of 3 or 4 integers"
    )
    image: scalars.RemoteUpload | None = strawberry.field(
        default=None, description="An optional image associated with this expression"
    )


def scalar_identifier_to_graph_name(scalar_string: str) -> str:

    assert "@" in scalar_string, f"Invalid scalar string: {scalar_string}"
    assert "/" in scalar_string, f"Invalid scalar string: {scalar_string}"
    assert ":" not in scalar_string, f"Invalid scalar string: {scalar_string}"
    assert scalar_string.count("@") == 1, f"Invalid scalar string: {scalar_string}"
    assert scalar_string.count("/") == 1, f"Invalid scalar string: {scalar_string}"

    match = scalar_string_re.match(scalar_string)
    assert match, f"Invalid scalar string: {scalar_string}"

    external_name = match.group("external_name")
    scalar_name = match.group("scalar_name")

    identifier = scalar_string.split(":")[0]

    return (
        f"{external_name}_{scalar_name}".replace("-", "_").upper(),
        identifier,
    )


@strawberry.input(description="Input for updating an existing expression")
class UpdateStructureCategoryInput:
    id: strawberry.ID = strawberry.field(
        description="The ID of the expression to update"
    )
    identifier: str | None = strawberry.field(
        default=None,
        description="The label/name of the expression"
    )
    label: str | None = strawberry.field(
        default=None, description="New label for the expression"
    )
    description: str | None = strawberry.field(
        default=None, description="New description for the expression"
    )
    purl: str | None = strawberry.field(
        default=None, description="New permanent URL for the expression"
    )
    color: list[int] | None = strawberry.field(
        default=None, description="New RGBA color values as list of 3 or 4 integers"
    )
    image: strawberry.ID | None = strawberry.field(
        default=None, description="New image ID for the expression"
    )


@strawberry.input(description="Input for deleting an expression")
class DeleteStructureCategoryInput:
    id: strawberry.ID = strawberry.field(
        description="The ID of the expression to delete"
    )


def create_structure_category(
    info: Info,
    input: StructureCategoryInput,
) -> types.StructureCategory:

    graph = models.Graph.objects.get(
        id=input.graph,
    )

    if input.color:
        assert (
            len(input.color) == 3 or len(input.color) == 4
        ), "Color must be a list of 3 or 4 values RGBA"

    if input.image:
        media_store = models.MediaStore.objects.get(
            id=input.image,
        )
    else:
        media_store = None

    age_name, identifier = scalar_identifier_to_graph_name(input.identifier)

    vocab, _ = models.StructureCategory.objects.update_or_create(
        graph=graph,
        age_name=manager.build_structure_age_name(identifier),
        defaults=dict(
            description=input.description,
            purl=input.purl,
            store=media_store,
            identifier=identifier,
        ),
    )

    age.create_age_structure_kind(vocab)

    return vocab


def update_structure_category(
    info: Info, input: UpdateStructureCategoryInput
) -> types.StructureCategory:
    item = models.StructureCategory.objects.get(id=input.id)

    if input.color:
        assert (
            len(input.color) == 3 or len(input.color) == 4
        ), "Color must be a list of 3 or 4 values RGBA"

    if input.image:
        media_store = models.MediaStore.objects.get(
            id=input.image,
        )
    else:
        media_store = None

    item.description = input.description if input.description else item.description
    item.purl = input.purl if input.purl else item.purl
    item.color = input.color if input.color else item.color
    item.store = media_store if media_store else item.store

    item.save()
    return item


def delete_structure_category(
    info: Info,
    input: DeleteStructureCategoryInput,
) -> strawberry.ID:
    item = models.StructureCategory.objects.get(id=input.id)
    item.delete()
    return input.id
