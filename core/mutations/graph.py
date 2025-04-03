from kante.types import Info
import strawberry
from core import types, models, age, enums, scalars, manager
from django.db import connections
from contextlib import contextmanager


@strawberry.input(description="Input type for creating a new ontology")
class GraphInput:
    name: str = strawberry.field(
        description="The name of the ontology (will be converted to snake_case)"
    )
    description: str | None = strawberry.field(
        default=None, description="An optional description of the ontology"
    )
    image: strawberry.ID | None = strawberry.field(
        default=None, description="An optional ID reference to an associated image"
    )


@strawberry.input(description="Input type for creating a new ontology node")
class GraphNodeInput:
    id: str = strawberry.field(description="The AGE_NAME of the ontology")
    position_x: float | None = strawberry.field(
        default=None, description="An optional x position for the ontology node"
    )
    position_y: float | None = strawberry.field(
        default=None, description="An optional y position for the ontology node"
    )
    height: float | None = strawberry.field(
        default=None, description="An optional height for the ontology node"
    )
    width: float | None = strawberry.field(
        default=None, description="An optional width for the ontology node"
    )
    color: list[int] | None = strawberry.field(
        default=None, description="An optional RGBA color for the ontology node"
    )


@strawberry.input(description="Input type for updating an existing ontology")
class UpdateGraphInput:
    id: strawberry.ID = strawberry.field(description="The ID of the ontology to update")
    name: str | None = strawberry.field(
        default=None,
        description="New name for the ontology (will be converted to snake_case)",
    )
    purl: str | None = strawberry.field(
        default=None,
        description="A new PURL for the ontology (will be converted to snake_case)",
    )
    description: str | None = strawberry.field(
        default=None, description="New description for the ontology"
    )
    image: strawberry.ID | None = strawberry.field(
        default=None, description="New ID reference to an associated image"
    )
    nodes: list[GraphNodeInput] | None = strawberry.field(
        default=None, description="New nodes for the ontology"
    )


@strawberry.input(description="Input type for deleting an ontology")
class DeleteGraphInput:
    id: strawberry.ID = strawberry.field(description="The ID of the ontology to delete")


def to_snake_case(string):
    return string.replace(" ", "_").lower()


def create_graph(
    info: Info,
    input: GraphInput,
) -> types.Graph:

    assert input.name, "Graph name is required"
    assert input.name != "", "Graph name cannot be empty"
    assert len(input.name) < 100, "Graph name cannot be longer than 100 characters"
    assert len(input.name) > 5, "Graph name must be at least 3 characters long"

    if input.image:
        media_store = models.MediaStore.objects.get(
            id=input.image,
        )
    else:
        media_store = None

    item, _ = models.Graph.objects.update_or_create(
        age_name=manager.build_graph_age_name(input.name),
        defaults=dict(
            description=input.description or "",
            store=media_store,
            user=info.context.request.user,
            name=input.name,
        ),
    )

    age.create_age_graph(item.age_name)

    return item


def update_graph(info: Info, input: UpdateGraphInput) -> types.Graph:
    item = models.Graph.objects.get(id=input.id)

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

    if input.nodes:
        
        for i in input.nodes:
            
            x = models.NodeCategory.objects.get(
                id=i.id,
            )
            if i.position_x:
                x.position_x = i.position_x
            if i.position_y:
                x.position_y = i.position_y
            if i.height:
                x.height = i.height
            if i.width:
                x.width = i.width
            if i.color:
                x.color = i.color
                
            x.save()




    else:
        if input.nodes:
            raise Exception("You must provide both nodes and edges if you provide any")
        if input.edges:
            raise Exception("You must provide both nodes and edges if you provide any")

    return item


def delete_graph(
    info: Info,
    input: DeleteGraphInput,
) -> strawberry.ID:
    item = models.Graph.objects.get(id=input.id)
    
    age.delete_age_graph(item.age_name)
    
    item.delete()

    return input.id


@strawberry.input(description="Input type for pinning an ontology")
class PinGraphInput:
    id: strawberry.ID = strawberry.field(description="The ID of the ontology to pin")
    pinned: bool = strawberry.field(description="Whether to pin the ontology or not")


def pin_graph(
    info: Info,
    input: PinGraphInput,
) -> types.Graph:
    item = models.Graph.objects.get(id=input.id)
    item.pinned = input.pinned
    item.save()

    return item
