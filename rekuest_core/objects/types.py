import datetime
from typing import Optional

import strawberry
import strawberry_django
from pydantic import BaseModel
from strawberry import LazyType
from strawberry.experimental import pydantic

from rekuest_core.objects import models
from rekuest_core import enums, scalars


class ChoiceModel(BaseModel):
    label: str
    value: str
    image: str | None
    description: str | None


@pydantic.type(models.ChoiceModel, fields=["label", "value", "image", "description"])
class Choice:
    pass


@pydantic.interface(models.AssignWidgetModel)
class AssignWidget:
    kind: enums.AssignWidgetKind
    follow_value: str | None


@pydantic.type(models.SliderAssignWidgetModel)
class SliderAssignWidget(AssignWidget):
    min: float | None
    max: float | None
    step: float | None


@pydantic.type(models.ChoiceAssignWidgetModel)
class ChoiceAssignWidget(AssignWidget):
    choices: strawberry.auto


@pydantic.type(models.CustomAssignWidgetModel)
class CustomAssignWidget(AssignWidget):
    hook: str
    ward: str


@pydantic.type(models.SearchAssignWidgetModel)
class SearchAssignWidget(AssignWidget):
    query: str
    ward: str
    filters: Optional[list[LazyType["Port", __name__]]] = None
    dependencies: list[str] | None = None

    # this took me a while to figure out should be more obvious


@pydantic.type(models.StateChoiceAssignWidgetModel)
class StateChoiceAssignWidget(AssignWidget):
    state_choices: str


@pydantic.type(models.StringWidgetModel)
class StringAssignWidget(AssignWidget):
    placeholder: str
    as_paragraph: bool


@pydantic.interface(models.ReturnWidgetModel)
class ReturnWidget:
    kind: enums.ReturnWidgetKind


@pydantic.type(models.CustomReturnWidgetModel)
class CustomReturnWidget(ReturnWidget):
    hook: str
    ward: str


@pydantic.type(models.ChoiceReturnWidgetModel)
class ChoiceReturnWidget(ReturnWidget):
    choices: strawberry.auto


@pydantic.interface(models.EffectModel)
class Effect:
    kind: enums.EffectKind
    function: scalars.ValidatorFunction
    dependencies: list[str]


@pydantic.type(models.MessageEffectModel)
class MessageEffect(Effect):
    message: str


@pydantic.type(models.CustomEffectModel)
class CustomEffect(Effect):
    ward: str
    hook: str


@pydantic.type(models.HideEffectModel)
class HideEffect(Effect):
    fade: bool = True


@pydantic.type(models.BindsModel)
class Binds:
    implementations: list[strawberry.ID]
    clients: list[strawberry.ID]
    desired_instances: int


@pydantic.type(models.DescriptorMatchModel)
class DescriptorMatch:
    key: str | None = strawberry.field(
        default=None,
        description="The key of the descriptor to match. ",
    )
    value: str | None = strawberry.field(
        default=None,
        description="The value of the descriptor to match. ",
    )
    operator: enums.DescriptorOperator | None = strawberry.field(
        default=None,
        description="The operator to use for matching. ",
    )


@pydantic.type(models.PortMatchModel)
class PortMatch:
    at: int | None = strawberry.field(
        default=None,
        description="The index of the port to match. ",
    )
    key: str | None = strawberry.field(
        default=None,
        description="The key of the port to match.",
    )
    kind: enums.PortKind | None = strawberry.field(
        default=None,
        description="The kind of the port to match. ",
    )
    identifier: str | None = strawberry.field(
        default=None,
        description="The identifier of the port to match. ",
    )
    nullable: bool | None = strawberry.field(
        default=None,
        description="Whether the port is nullable. ",
    )
    children: list[LazyType["PortMatch", __name__]] | None = strawberry.field(
        default=None,
        description="Child ports to match. ",
    )
    descriptors: list[DescriptorMatch] | None = strawberry.field(
        default=None,
        description="Descriptors to match. ",
    )


@pydantic.type(models.PortGroupModel)
class PortGroup:
    key: str
    title: str | None
    description: str | None
    effects: list[Effect] | None
    ports: list[str]


@pydantic.type(models.ValidatorModel)
class Validator:
    function: scalars.ValidatorFunction
    dependencies: list[str] | None
    label: str | None
    error_message: str | None = None


@pydantic.type(models.DescriptorModel)
class Descriptor:
    key: str = strawberry.field(description="The key of the descriptor. This is used to uniquely identify the descriptor")
    value: scalars.Arg = strawberry.field(description="The value of the descriptor. This can be any JSON serializable value")


@pydantic.type(models.PortModel)
class Port:
    identifier: scalars.Identifier | None = strawberry.field(
        default=None,
        description="The identifier of the port. Identifier are used to give meaning to structure ports",
    )
    default: scalars.AnyDefault | None
    kind: enums.PortKind
    key: str
    nullable: bool
    label: str | None
    description: str | None
    effects: list[Effect] | None = None
    children: list[LazyType["Port", __name__]] | None = None
    choices: list[Choice] | None = None
    assign_widget: AssignWidget | None = None
    return_widget: ReturnWidget | None = None
    validators: list[Validator] | None = None
    descriptors: list[Descriptor] | None = None


@pydantic.type(models.DefinitionModel)
class Definition:
    hash: scalars.ActionHash
    name: str
    stateful: bool
    kind: enums.ActionKind
    description: str | None
    port_groups: list[PortGroup]
    collections: list[str]
    scope: enums.ActionScope
    is_test_for: list[str]
    tests: list[str]
    protocols: list[str]
    defined_at: datetime.datetime
    is_dev: bool

    @strawberry_django.field()
    def args(self) -> list[Port]:
        return [models.PortModel(**i) for i in self.args]

    @strawberry_django.field()
    def returns(self) -> list[Port]:
        return [models.PortModel(**i) for i in self.returns]
