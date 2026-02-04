from kante.types import Info
import strawberry
from core import types, models, age, inputs, scalars, enums, manager
import uuid
import datetime
import re


@strawberry.input
class TagInput:
    value: str
    graph: strawberry.ID


def create_tag(input: TagInput, info: Info) -> types.Tag:
    tag = models.CategoryTag(
        value=input.value,
        graph_id=input.graph,
        created_at=datetime.datetime.now(),
        updated_at=datetime.datetime.now(),
    )
    tag.save()
    return tag


@strawberry.input
class DeleteTagInput:
    id: scalars.NodeID
