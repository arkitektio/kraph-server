"""Inputs for writing projects; validated by pydantic, the way todo inputs are."""

from typing import Optional

import strawberry
from pydantic import BaseModel, ConfigDict, Field
from strawberry.experimental import pydantic


class _Strict(BaseModel):
    """A key that is not a field is an error (see `graph_engine.input_models.StrictModel`)."""

    model_config = ConfigDict(extra="forbid")


class CreateProjectInputModel(_Strict):
    name: str = Field(description="The name of the project")
    description: Optional[str] = Field(default=None, description="What the project is about")


@pydantic.input(CreateProjectInputModel, description="Input for creating a project")
class CreateProjectInput:
    name: str
    description: Optional[str] = None


class UpdateProjectInputModel(_Strict):
    id: int = Field(description="The project to change")
    name: str = Field(description="Its new name")
    description: Optional[str] = Field(default=None, description="Its new description")


@pydantic.input(UpdateProjectInputModel, description="Input for changing a project")
class UpdateProjectInput:
    id: strawberry.ID
    name: str
    description: Optional[str] = None


class ProjectIdInputModel(_Strict):
    id: int = Field(description="The project to act on")


@pydantic.input(ProjectIdInputModel, description="Input naming one project")
class ProjectIdInput:
    id: strawberry.ID
