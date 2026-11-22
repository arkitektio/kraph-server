"""What a client sends to change a todo list: pydantic models, and the GraphQL inputs over them."""

import builtins
from datetime import datetime
from enum import Enum

import strawberry
from pydantic import BaseModel, ConfigDict, Field, model_validator
from strawberry.experimental import pydantic


@strawberry.enum(description="The board column a todo item is in")
class TodoStatus(str, Enum):
    TODO = "TODO"
    DOING = "DOING"
    DONE = "DONE"


class _Strict(BaseModel):
    """A key that is not a field is an error (see `graph_engine.input_models.StrictModel`)."""

    model_config = ConfigDict(extra="forbid")


class TodoStructureInputModel(_Strict):
    identifier: str = Field(
        description="The object's structure identifier, e.g. @mikro/image"
    )
    object: str = Field(description="The object's id within its structure")


@pydantic.input(
    TodoStructureInputModel,
    description="An object to put on a todo item, named the way a comment names one",
)
class TodoStructureInput:
    identifier: str
    object: strawberry.ID


class CreateTodoListInputModel(_Strict):
    project: int = Field(description="The project the list belongs to")
    name: str = Field(description="The name of the list")
    description: str | None = Field(default=None, description="What the list is for")
    assignee: str | None = Field(
        default=None, description="The sub of the user the list is assigned to"
    )
    due_at: datetime | None = Field(
        default=None,
        description="When the list is due; its items without a date of their own follow it",
    )


@pydantic.input(CreateTodoListInputModel, description="Input for creating a todo list")
class CreateTodoListInput:
    project: strawberry.ID
    name: str
    description: str | None = None
    assignee: strawberry.ID | None = None
    due_at: datetime | None = None


class UpdateTodoListInputModel(_Strict):
    id: int = Field(description="The list to change")
    name: str = Field(description="Its new name")
    description: str | None = Field(default=None, description="Its new description")
    assignee: str | None = Field(
        default=None, description="Its new assignee (a sub); unassigned when not given"
    )


@pydantic.input(
    UpdateTodoListInputModel,
    description="Input for changing a todo list. Every field is replaced.",
)
class UpdateTodoListInput:
    id: strawberry.ID
    name: str
    description: str | None = None
    assignee: strawberry.ID | None = None


class CreateTodoItemInputModel(_Strict):
    list: int = Field(description="The list the item goes on")
    title: str = Field(description="What is to be done")
    description: str | None = Field(
        default=None, description="More about what is to be done"
    )
    assignee: str | None = Field(
        default=None,
        description="The sub of the user the item is assigned to; the list's assignee when not given",
    )
    status: TodoStatus | None = Field(
        default=None, description="The column it starts in; To do when not given"
    )
    structures: builtins.list[TodoStructureInputModel] | None = Field(
        default=None, description="The objects it is about"
    )
    due_at: datetime | None = Field(
        default=None, description="When it is due; the list's due date when not given"
    )


@pydantic.input(CreateTodoItemInputModel, description="Input for creating a todo item")
class CreateTodoItemInput:
    list: strawberry.ID
    title: str
    description: str | None = None
    assignee: strawberry.ID | None = None
    status: TodoStatus | None = None
    structures: list[TodoStructureInput] | None = None
    due_at: datetime | None = None


class UpdateTodoItemInputModel(_Strict):
    id: int = Field(description="The item to change")
    title: str = Field(description="Its new title")
    description: str | None = Field(default=None, description="Its new description")
    assignee: str | None = Field(
        default=None, description="Its own assignee (a sub); the list's when not given"
    )


@pydantic.input(
    UpdateTodoItemInputModel,
    description="Input for changing a todo item. Every field is replaced.",
)
class UpdateTodoItemInput:
    id: strawberry.ID
    title: str
    description: str | None = None
    assignee: strawberry.ID | None = None


class MoveTodoItemInputModel(_Strict):
    id: int = Field(description="The item to move")
    status: TodoStatus = Field(description="The column to move it to")
    index: int = Field(
        default=0,
        ge=0,
        description="Its place in that column once moved, 0 first; past the end puts it last",
    )
    list: int | None = Field(
        default=None,
        description="Another list (of the same organization) to move it to; its own when not given",
    )


@pydantic.input(
    MoveTodoItemInputModel,
    description="Input for moving a todo item on its board, or onto another list",
)
class MoveTodoItemInput:
    id: strawberry.ID
    status: TodoStatus
    index: int = 0
    list: strawberry.ID | None = None


class AttachToTodoItemInputModel(_Strict):
    item: int = Field(description="The item to put the objects on")
    structures: list[TodoStructureInputModel] = Field(
        description="The objects; one already on the item is left as it is"
    )


@pydantic.input(
    AttachToTodoItemInputModel, description="Input for putting objects on a todo item"
)
class AttachToTodoItemInput:
    item: strawberry.ID
    structures: list[TodoStructureInput]


class SetTodoStructureDoneInputModel(_Strict):
    id: int = Field(description="The object on an item (a TodoItemStructure)")
    done: bool = Field(description="Whether it is done")


@pydantic.input(
    SetTodoStructureDoneInputModel,
    description="Input for ticking (or unticking) one object on a todo item",
)
class SetTodoStructureDoneInput:
    id: strawberry.ID
    done: bool


class SetTodoStructureStatusInputModel(_Strict):
    id: int = Field(description="The object on an item (a TodoItemStructure)")
    status: TodoStatus = Field(description="To do, Doing or Done")


@pydantic.input(
    SetTodoStructureStatusInputModel,
    description="Input for moving one object on a todo item to To do, Doing or Done",
)
class SetTodoStructureStatusInput:
    id: strawberry.ID
    status: TodoStatus


class SetTodoStructuresStatusInputModel(_Strict):
    ids: list[int] = Field(
        default_factory=list,
        max_length=1000,
        description="The objects on items (TodoItemStructures)",
    )
    items: list[int] = Field(
        default_factory=list,
        max_length=1000,
        description="Items whose every object moves, however many they carry",
    )
    status: TodoStatus = Field(description="To do, Doing or Done, for all of them")

    @model_validator(mode="after")
    def _names_something(self) -> "SetTodoStructuresStatusInputModel":
        if not self.ids and not self.items:
            raise ValueError("Name the objects (`ids`) or the items (`items`) to move")
        return self


@pydantic.input(
    SetTodoStructuresStatusInputModel,
    description="Input for moving several objects on todo items to one status at once",
)
class SetTodoStructuresStatusInput:
    ids: list[strawberry.ID] = strawberry.field(
        default_factory=list, description="The objects on items (TodoItemStructures)"
    )
    items: list[strawberry.ID] = strawberry.field(
        default_factory=list,
        description='Items whose every object moves: "mark all done" without reading the objects first',
    )
    status: TodoStatus


class AssignTodoInputModel(_Strict):
    id: int = Field(description="The list or item to assign")
    assignee: str | None = Field(
        default=None,
        description="Who it is for (a sub); nobody when not given (an item then falls back to its list's)",
    )


@pydantic.input(
    AssignTodoInputModel,
    description="Input for changing only who a todo list or item is for",
)
class AssignTodoInput:
    id: strawberry.ID
    assignee: strawberry.ID | None = None


class ScheduleTodoInputModel(_Strict):
    id: int = Field(description="The list or item to schedule")
    due_at: datetime | None = Field(
        default=None,
        description="When it is due; no date when not given (an item then follows its list's)",
    )


@pydantic.input(
    ScheduleTodoInputModel,
    description="Input for changing only when a todo list or item is due",
)
class ScheduleTodoInput:
    id: strawberry.ID
    due_at: datetime | None = None


class TodoIdInputModel(_Strict):
    id: int = Field(description="The row to act on")


@pydantic.input(
    TodoIdInputModel, description="Input naming one todo list, item or item object"
)
class TodoIdInput:
    id: strawberry.ID
