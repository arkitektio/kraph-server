from contextvars import ContextVar
from functools import cached_property
import boto3
from django.conf import settings
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types_boto3_s3 import S3Client
    from types_boto3_sts import STSClient

datalayer: ContextVar = ContextVar("datalayer", default=None)


class Datalayer:
    """A S3 Powered Datalayer"""

    @cached_property
    def s3(self) -> S3Client:
        """Get a boto3 session for S3 without s3v4 signature"""
        return boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            endpoint_url=settings.AWS_S3_ENDPOINT_URL,
            region_name=settings.AWS_S3_REGION_NAME,  # region does not matter when using MinIO
        )

    @cached_property
    def s3v4(self) -> S3Client:
        """Get a boto3 session for S3 with s3v4 signature"""
        return boto3.client(
            "s3",
            endpoint_url=settings.AWS_S3_ENDPOINT_URL,
            region_name=settings.AWS_S3_REGION_NAME,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            aws_session_token=None,
            config=boto3.session.Config(signature_version="s3v4"),  # type: ignore
            verify=False,
        )

    @cached_property
    def sts(self) -> STSClient:
        """Get a boto3 session for STS with s3v4 signature"""
        return boto3.client(
            "sts",
            endpoint_url=settings.AWS_S3_ENDPOINT_URL,
            region_name=settings.AWS_S3_REGION_NAME,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            aws_session_token=None,
            config=boto3.session.Config(signature_version="s3v4"),  # type: ignore
            verify=False,
        )


def get_current_datalayer() -> Datalayer:
    """Get the current datalayer from the context variable, or create a new one if it doesn't exist. This function is used to access the datalayer throughout the codebase without having to pass it explicitly."""
    return Datalayer()
