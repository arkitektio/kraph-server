"""What a client sends to change a todo list: pydantic models, and the GraphQL inputs over them."""

from enum import Enum
from typing import List, Optional

import strawberry
from pydantic import BaseModel, ConfigDict, Field
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
    identifier: str = Field(description="The object's structure identifier, e.g. @mikro/image")
    object: str = Field(description="The object's id within its structure")


@pydantic.input(TodoStructureInputModel, description="An object to put on a todo item, named the way a comment names one")
class TodoStructureInput:
    identifier: str
    object: strawberry.ID


class CreateTodoListInputModel(_Strict):
    project: int = Field(description="The project the list belongs to")
    name: str = Field(description="The name of the list")
    description: Optional[str] = Field(default=None, description="What the list is for")
    assignee: Optional[str] = Field(default=None, description="The sub of the user the list is assigned to")


@pydantic.input(CreateTodoListInputModel, description="Input for creating a todo list")
class CreateTodoListInput:
    project: strawberry.ID
    name: str
    description: Optional[str] = None
    assignee: Optional[strawberry.ID] = None


class UpdateTodoListInputModel(_Strict):
    id: int = Field(description="The list to change")
    name: str = Field(description="Its new name")
    description: Optional[str] = Field(default=None, description="Its new description")
    assignee: Optional[str] = Field(default=None, description="Its new assignee (a sub); unassigned when not given")


@pydantic.input(UpdateTodoListInputModel, description="Input for changing a todo list. Every field is replaced.")
class UpdateTodoListInput:
    id: strawberry.ID
    name: str
    description: Optional[str] = None
    assignee: Optional[strawberry.ID] = None


class CreateTodoItemInputModel(_Strict):
    list: int = Field(description="The list the item goes on")
    title: str = Field(description="What is to be done")
    description: Optional[str] = Field(default=None, description="More about what is to be done")
    assignee: Optional[str] = Field(default=None, description="The sub of the user the item is assigned to; the list's assignee when not given")
    status: Optional[TodoStatus] = Field(default=None, description="The column it starts in; To do when not given")
    structures: Optional[List[TodoStructureInputModel]] = Field(default=None, description="The objects it is about")


@pydantic.input(CreateTodoItemInputModel, description="Input for creating a todo item")
class CreateTodoItemInput:
    list: strawberry.ID
    title: str
    description: Optional[str] = None
    assignee: Optional[strawberry.ID] = None
    status: Optional[TodoStatus] = None
    structures: Optional[List[TodoStructureInput]] = None


class UpdateTodoItemInputModel(_Strict):
    id: int = Field(description="The item to change")
    title: str = Field(description="Its new title")
    description: Optional[str] = Field(default=None, description="Its new description")
    assignee: Optional[str] = Field(default=None, description="Its own assignee (a sub); the list's when not given")


@pydantic.input(UpdateTodoItemInputModel, description="Input for changing a todo item. Every field is replaced.")
class UpdateTodoItemInput:
    id: strawberry.ID
    title: str
    description: Optional[str] = None
    assignee: Optional[strawberry.ID] = None


class MoveTodoItemInputModel(_Strict):
    id: int = Field(description="The item to move")
    status: TodoStatus = Field(description="The column to move it to")
    index: int = Field(default=0, ge=0, description="Its place in that column once moved, 0 first; past the end puts it last")


@pydantic.input(MoveTodoItemInputModel, description="Input for moving a todo item on its board")
class MoveTodoItemInput:
    id: strawberry.ID
    status: TodoStatus
    index: int = 0


class AttachToTodoItemInputModel(_Strict):
    item: int = Field(description="The item to put the objects on")
    structures: List[TodoStructureInputModel] = Field(description="The objects; one already on the item is left as it is")


@pydantic.input(AttachToTodoItemInputModel, description="Input for putting objects on a todo item")
class AttachToTodoItemInput:
    item: strawberry.ID
    structures: List[TodoStructureInput]


class SetTodoStructureDoneInputModel(_Strict):
    id: int = Field(description="The object on an item (a TodoItemStructure)")
    done: bool = Field(description="Whether it is done")


@pydantic.input(SetTodoStructureDoneInputModel, description="Input for ticking (or unticking) one object on a todo item")
class SetTodoStructureDoneInput:
    id: strawberry.ID
    done: bool


class SetTodoStructureStatusInputModel(_Strict):
    id: int = Field(description="The object on an item (a TodoItemStructure)")
    status: TodoStatus = Field(description="To do, Doing or Done")


@pydantic.input(SetTodoStructureStatusInputModel, description="Input for moving one object on a todo item to To do, Doing or Done")
class SetTodoStructureStatusInput:
    id: strawberry.ID
    status: TodoStatus


class TodoIdInputModel(_Strict):
    id: int = Field(description="The row to act on")


@pydantic.input(TodoIdInputModel, description="Input naming one todo list, item or item object")
class TodoIdInput:
    id: strawberry.ID
