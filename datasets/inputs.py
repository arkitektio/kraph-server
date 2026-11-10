"""What a client sends to run a pairs query or register a trained model: pydantic models, and the GraphQL inputs over them."""

from typing import Any, Optional

import strawberry
from arkitekt_datalayer.scalars import BigFileLike
from pydantic import BaseModel, ConfigDict, Field
from strawberry.experimental import pydantic
from strawberry.scalars import JSON


class _Strict(BaseModel):
    """A key that is not a field is an error (see `graph_engine.input_models.StrictModel`)."""

    model_config = ConfigDict(extra="forbid")


class RunPairsQueryInputModel(_Strict):
    query: int = Field(description="The pairs query to run")
    name: str = Field(min_length=1, description="What the run is called")
    description: Optional[str] = Field(default=None, description="What the run is for")


@pydantic.input(RunPairsQueryInputModel, description="Input for running a pairs query: its answer from the view's drawing, stored with where the drawing stood")
class RunPairsQueryInput:
    query: strawberry.ID
    name: str
    description: Optional[str] = None


class DeletePairsQueryRunInputModel(_Strict):
    id: int = Field(description="The run to delete")


@pydantic.input(DeletePairsQueryRunInputModel, description="Input for deleting a run. A run a model was trained on stays")
class DeletePairsQueryRunInput:
    id: strawberry.ID


class CreateModelInputModel(_Strict):
    name: str = Field(min_length=1, description="What the model is called")
    framework: str = Field(min_length=1, description="What the weights are for, e.g. 'care' or 'cellpose'")
    store: str = Field(description="The finished big-file upload holding the weights")
    trained_on: Optional[int] = Field(default=None, description="The pairs query run it was trained on; give this or `trained_on_query`, or neither for weights from elsewhere")
    trained_on_query: Optional[int] = Field(default=None, description="The pairs query it was trained on, when nobody kept a run: the server runs it for the model")
    description: Optional[str] = Field(default=None, description="What the model does")
    parameters: Optional[Any] = Field(default=None, description="How it was trained, as the trainer reports it")


@pydantic.input(CreateModelInputModel, description="Input for registering a trained model: its weights (a finished big-file upload) and what it was trained on, a run or a pairs query the server runs")
class CreateModelInput:
    name: str
    framework: str
    store: BigFileLike = strawberry.field(description="The finished big-file upload holding the weights. A client passes the file; its upload middleware turns it into this")
    trained_on: Optional[strawberry.ID] = None
    trained_on_query: Optional[strawberry.ID] = None
    description: Optional[str] = None
    parameters: Optional[JSON] = None


class DeleteModelInputModel(_Strict):
    id: int = Field(description="The model to delete")


@pydantic.input(DeleteModelInputModel, description="Input for deleting a trained model; its weights are flagged orphaned for the datalayer's purge")
class DeleteModelInput:
    id: strawberry.ID
