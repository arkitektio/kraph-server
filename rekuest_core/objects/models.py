import strawberry
from typing import Optional
from pydantic import BaseModel
from typing import Literal, Union
import datetime
from rekuest_core import enums
from typing import Any


class ChoiceModel(BaseModel):
    label: str
    value: str
    image: str | None
    description: str | None


class AssignWidgetModel(BaseModel):
    kind: str
    follow_value: str | None = None


class SliderAssignWidgetModel(AssignWidgetModel):
    kind: Literal["SLIDER"]
    min: float | None = None
    max: float | None = None
    step: float | None = None


class ChoiceAssignWidgetModel(AssignWidgetModel):
    kind: Literal["CHOICE"]
    choices: list[ChoiceModel] | None


class CustomAssignWidgetModel(AssignWidgetModel):
    kind: Literal["CUSTOM"]
    hook: str
    ward: str


class SearchAssignWidgetModel(AssignWidgetModel):
    kind: Literal["SEARCH"]
    query: str  # TODO: Validators
    ward: str
    filters: list["PortModel"] | None = None
    dependencies: list[str] | None = None


class StateChoiceAssignWidgetModel(AssignWidgetModel):
    kind: Literal["STATE_CHOICE"]
    state_choices: str


class StringWidgetModel(AssignWidgetModel):
    kind: Literal["STRING"]
    placeholder: str | None
    as_paragraph: bool | None


AssignWidgetModelUnion = Union[
    SliderAssignWidgetModel,
    ChoiceAssignWidgetModel,
    SearchAssignWidgetModel,
    StateChoiceAssignWidgetModel,
    StringWidgetModel,
    CustomAssignWidgetModel,
]


class ReturnWidgetModel(BaseModel):
    kind: str


class CustomReturnWidgetModel(ReturnWidgetModel):
    hook: str
    ward: str


class ChoiceReturnWidgetModel(ReturnWidgetModel):
    kind: Literal["CHOICE"]
    choices: list[ChoiceModel] | None


ReturnWidgetModelUnion = Union[CustomReturnWidgetModel, ChoiceReturnWidgetModel]


class EffectModel(BaseModel):
    kind: str
    function: str
    dependencies: list[str]


class MessageEffectModel(EffectModel):
    kind: Literal["MESSAGE"]
    message: str


class HideEffectModel(EffectModel):
    kind: Literal["HIDE"]
    fade: bool = True


class CustomEffectModel(EffectModel):
    kind: Literal["CUSTOM"]
    hook: str
    ward: str


EffectModelUnion = Union[MessageEffectModel, HideEffectModel, CustomEffectModel]


class BindsModel(BaseModel):
    implementations: Optional[list[str]] = None
    clients: Optional[list[str]] = None
    desired_instances: int = 1
    minimum_instances: int = 1


class PortGroupModel(BaseModel):
    key: str
    title: str | None
    description: str | None
    effects: list[EffectModelUnion] | None = None
    ports: list[str]


class ValidatorModel(BaseModel):
    function: str
    dependencies: list[str] | None = []
    label: str | None = None
    error_message: str | None = None


class DescriptorMatchModel(BaseModel):
    key: str | None = None
    operator: enums.DescriptorOperator
    value: Any | None = None


class PortMatchModel(BaseModel):
    at: int | None = None
    key: str | None = None
    kind: str | None = None
    identifier: str | None = None
    children: list["PortMatchModel"] | None = None
    nullable: bool | None = False
    descriptors: list[DescriptorMatchModel] | None = None


class DescriptorModel(BaseModel):
    key: str
    value: Any


class PortModel(BaseModel):
    key: str
    label: str | None = None
    kind: str
    description: str | None = None
    identifier: str | None = None
    nullable: bool
    effects: list[EffectModelUnion] | None
    default: Any | None = None
    children: list["PortModel"] | None
    choices: list[ChoiceModel] | None = None
    assign_widget: AssignWidgetModelUnion | None
    return_widget: ReturnWidgetModelUnion | None
    validators: list[ValidatorModel] | None
    descriptors: list[DescriptorModel] | None = None


class DefinitionModel(BaseModel):
    id: strawberry.ID
    hash: str
    name: str
    kind: enums.ActionKind
    description: str | None
    port_groups: list[PortGroupModel]
    collections: list[str]
    scope: enums.ActionScope
    is_test_for: list[str]
    tests: list[str]
    protocols: list[str]
    defined_at: datetime.datetime
    is_dev: bool = False
    args: list[PortModel]
    returns: list[PortModel]


SearchAssignWidgetModel.update_forward_refs()
