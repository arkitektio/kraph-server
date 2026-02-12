from typing import Any, Callable, NewType
from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema
from datalayer import models


MediaStoreLike = NewType("MediaStoreLike", str)


class MediaStore(str):
    """A type representing a media store reference, which can be either a string ID or a more complex object."""

    def __init__(self, value: str):
        super().__init__(value)

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        source_type: Any,  # noqa: ANN401
        handler: GetCoreSchemaHandler,  # noqa: ANN401
    ) -> CoreSchema:
        """Get the pydantic core schema for the interface"""
        return core_schema.no_info_after_validator_function(cls.validate, handler(str))

    @classmethod
    def validate(cls, v: str) -> str:
        """Validate the interface"""
        if not isinstance(v, str):
            raise TypeError("MediaStore value must be a string representing the media store ID.")
        return v

    def model(self) -> models.MediaStore:
        """Fetch the corresponding MediaStore model instance from the database."""

        return models.MediaStore.objects.get(id=self)
