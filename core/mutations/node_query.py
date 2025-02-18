from kante.types import Info
from core.datalayer import get_current_datalayer

import strawberry
from core import types, models, enums, scalars
from core import age
from strawberry.file_uploads import Upload
from django.conf import settings


@strawberry.input(description="Input for creating a new expression")
class NodeQueryInput:
    ontology: strawberry.ID | None = strawberry.field(
        default=None,
        description="The ID of the ontology this expression belongs to. If not provided, uses default ontology",
    )
    name: str = strawberry.field(description="The label/name of the expression")
    query: scalars.Cypher = strawberry.field(description="The label/name of the expression")
    description: str | None = strawberry.field(
        default=None, description="A detailed description of the expression"
    )
    kind: enums.ViewKind = strawberry.field(
        default=None, description="The kind/type of this expression"
    )


@strawberry.input(description="Input for updating an existing expression")
class UpdateNodeQueryInput(NodeQueryInput):
    id: strawberry.ID = strawberry.field(
        description="The ID of the expression to update"
    )


@strawberry.input(description="Input for deleting an expression")
class DeleteNodeQueryInput:
    id: strawberry.ID = strawberry.field(
        description="The ID of the expression to delete"
    )


def create_node_query(
    info: Info,
    input: NodeQueryInput,
) -> types.NodeQuery:

    ontology = (
        models.Ontology.objects.get(id=input.ontology) if input.ontology else None
    )

    if not ontology:

        user = info.context.request.user

        ontology, _ = models.Ontology.objects.get_or_create(
            user=user,
            defaults=dict(
                name="Default for {}".format(user.username),
                description="Default ontology for {}".format(user.username),
            ),
        )

    vocab, _ = models.NodeQuery.objects.update_or_create(
        ontology=ontology,
        query = input.query,
        defaults=dict(
            name=input.name,
            description=input.description,
            kind=input.kind,
        ),
    )

    return vocab




def delete_node_query(
    info: Info,
    input: DeleteNodeQueryInput,
) -> strawberry.ID:
    item = models.NodeQuery.objects.get(id=input.id)
    item.delete()
    return input.id
