from kante.types import Info
from core.datalayer import get_current_datalayer

import strawberry
from core import types, models, enums, scalars, inputs
from core import age
from strawberry.file_uploads import Upload
from django.conf import settings
from core.renderers.graph import render


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
    test_against: strawberry.ID | None = strawberry.field(
        default=None, description="The graph to test against"
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
    
    graph = models.Graph.objects.get(id=input.test_against) if input.test_against else models.Graph.objects.filter(user=info.context.request.user).first()
    
    
    if graph:
        graph_view, _ = models.GraphView.objects.get_or_create(
            graph=graph,
            query=vocab,
            creator = info.context.request.user,
        )
        try:
            render.render_graph_view(graph_view)
        except Exception as e:
            graph_view.delete()
            vocab.delete()
            raise e
       
       

    return vocab




def delete_graph_query(
    info: Info,
    input: DeleteGraphQueryInput,
) -> strawberry.ID:
    item = models.NodeQuery.objects.get(id=input.id)
    item.delete()
    return input.id

@strawberry.input
class PinGraphQueryInput:
    id: strawberry.ID
    pinned: bool



def pin_graph_query(
    info: Info,
    input: PinGraphQueryInput,
) -> types.GraphQuery:
    item = models.GraphQuery.objects.get(id=input.id)


    if input.pinned:
        item.pinned_by.add(info.context.request.user)
    else:
        item.pinned_by.remove(info.context.request.user)

    item.save()
    return item