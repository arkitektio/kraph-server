from django.db import models
from django.core.exceptions import ValidationError
import re


def validate_s3(value: str) -> None:
    """Validate that the given value is a valid S3 path in the format s3://datalayer/bucket_name/object_key"""
    s3_pattern = r"^s3://.+/.+/.+"
    if not re.match(s3_pattern, value):
        raise ValidationError(
            "Invalid S3 path format. Should be s3://datalayer/bucket_name/object_key",
            code="invalid",
        )


class S3Field(models.CharField):
    """A CharField to store S3 paths with validation for the format s3://datalayer/bucket_name/object_key"""

    description = "CharField to store S3 path for Zarr dataset with validation"

    def __init__(self, *args, **kwargs) -> None:
        """Initialize the S3Field with a default max_length of 500 and add the validate_s3 validator to the field validators. The max_length can be overridden by passing a max_length argument when initializing the field."""
        kwargs["max_length"] = kwargs.get("max_length", 500)

        super().__init__(*args, **kwargs)
