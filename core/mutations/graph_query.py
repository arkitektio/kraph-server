from kante.types import Info
from core.datalayer import get_current_datalayer

import strawberry
from core import types, models, enums, scalars, inputs
from core import age
from strawberry.file_uploads import Upload
from django.conf import settings
from core.queries import path, pairs, table


@strawberry.input(description="Input for creating a new expression")
class GraphQueryInput:
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
    columns: list[inputs.ColumnInput] | None = strawberry.field(
        default=None, description="The columns (if ViewKind is Table)"
    )


@strawberry.input(description="Input for updating an existing expression")
class UpdateGraphQueryInput(GraphQueryInput):
    id: strawberry.ID = strawberry.field(
        description="The ID of the expression to update"
    )


@strawberry.input(description="Input for deleting an expression")
class DeleteGraphQueryInput:
    id: strawberry.ID = strawberry.field(
        description="The ID of the expression to delete"
    )


def create_graph_query(
    info: Info,
    input: GraphQueryInput,
) -> types.GraphQuery:

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

    for graph in ontology.graphs.all()[:1]:
        if input.kind == enums.ViewKind.PATH:
            path(info, graph.id, input.query)
        elif input.kind == enums.ViewKind.PAIRS:
            pairs(info, graph.id, input.query)
        elif input.kind == enums.ViewKind.TABLE:
            table(info, graph.id, input.query, input.columns)
        
        

    vocab, _ = models.GraphQuery.objects.update_or_create(
        ontology=ontology,
        query = input.query,
        defaults=dict(
            name=input.name,
            description=input.description,
            kind=input.kind,
            columns=[strawberry.asdict(c) for c in input.columns] if input.columns else [],
        ),
    )

    return vocab




def delete_graph_query(
    info: Info,
    input: DeleteGraphQueryInput,
) -> strawberry.ID:
    item = models.NodeQuery.objects.get(id=input.id)
    item.delete()
    return input.id
