from kante.types import Info
from core.datalayer import get_current_datalayer

import strawberry
from core import types, models, enums, scalars, inputs
from core import age
from strawberry.file_uploads import Upload
from django.conf import settings
from core.renderers.node import render
from django.contrib.auth import get_user_model


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
    columns: list[inputs.ColumnInput] | None = strawberry.field(
        default=None, description="The columns (if ViewKind is Table)"
    )
    test_against: strawberry.ID | None = strawberry.field(
        default=None, description="The node to test against"
    )
    allowed_entities: list[strawberry.ID] | None = strawberry.field(
        default=None, description="The allowed entitie classes for this query"
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
            columns=[strawberry.asdict(c) for c in input.columns] if input.columns else [],
        ),
    )
    
    if not input.test_against:
        graph = models.Graph.objects.filter(user=info.context.request.user).first()
        if not graph:
            return vocab
        try:
            node = age.get_random_node(graph.age_name)
        except Exception as e:
            return vocab
        
        node_id = node.unique_id

    else:
        graph = models.Graph.objects.get(age_name=age.to_graph_id(input.test_against))
        node_id = input.test_against
    
        
    
    new_view, _ = models.NodeView.objects.get_or_create(
        graph = graph,
        node_id = node_id,
        query = vocab,
        creator = info.context.request.user,
    )
    try:
        render.render_node_view(new_view)
    except Exception as e:
        new_view.delete()
        vocab.delete()
        raise e
       

    return vocab




def delete_node_query(
    info: Info,
    input: DeleteNodeQueryInput,
) -> strawberry.ID:
    item = models.NodeQuery.objects.get(id=input.id)
    item.delete()
    return input.id



@strawberry.input
class PinNodeQueryInput:
    id: strawberry.ID
    pinned: bool



def pin_node_query(
    info: Info,
    input: PinNodeQueryInput,
) -> types.NodeQuery:
    item = models.NodeQuery.objects.get(id=input.id)


    if input.pinned:
        item.pinned_by.add(info.context.request.user)
    else:
        item.pinned_by.remove(info.context.request.user)

    item.save()
    return item