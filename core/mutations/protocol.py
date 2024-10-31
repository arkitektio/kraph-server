from kante.types import Info
import strawberry
from core import types, models
import uuid




@strawberry.input
class ProtocolInput:
    name: str
    description: str | None = None
    experiment: strawberry.ID



@strawberry.input
class DeleteProtocolInput:
    id: strawberry.ID



def create_protocol(
    info: Info,
    input: ProtocolInput,
) -> types.Protocol:
    
    item, _ = models.Protocol.objects.get_or_create(
        name=input.name,
        experiment_id=input.experiment,
        defaults=dict(description=input.description)
    )

    return item


def delete_protocol(
    info: Info,
    input: DeleteProtocolInput,
) -> strawberry.ID:
    item = models.Protocol.objects.get(id=input.id)
    item.delete()
    return input.id

