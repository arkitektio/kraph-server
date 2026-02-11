from kante.types import Info
import strawberry
from api import types, scalars
from core import models
import datetime


def create_tag(input: TagInput, info: Info) -> types.Tag:
    tag = models.CategoryTag(
        value=input.value,
        graph_id=input.graph,
        created_at=datetime.datetime.now(),
        updated_at=datetime.datetime.now(),
    )
    tag.save()
    return tag
