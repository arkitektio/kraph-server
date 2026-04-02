from typing import Any, Callable, NewType
from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema
from datalayer import models
import strawberry


MediaStore = NewType("MediaStore", str)


scalar_map = {
    MediaStore: strawberry.scalar(
        name="MediaStore",
        description="A type representing a media store reference, which can be either a string ID or a more complex object.",
        serialize=lambda v: v,  # Implement your serialization logic here
        parse_value=lambda v: v,  # Implement your parsing logic here
    ),
}
