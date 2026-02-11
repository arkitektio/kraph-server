import strawberry
from datalayer import models
from kante.types import Info
import kante
from typing import cast

from datalayer.datalayer import get_current_datalayer


@kante.type(description="Temporary Credentials for a file upload that can be used by a Client (e.g. in a python datalayer)")
class Credentials:
    """Temporary Credentials for a a file upload."""

    status: str
    access_key: str
    secret_key: str
    session_token: str
    datalayer: str
    bucket: str
    key: str
    store: str


@kante.type(description="Temporary Credentials for a file upload that can be used by a Client (e.g. in a python datalayer)")
class PresignedPostCredentials:
    """Temporary Credentials for a a file upload."""

    key: str
    x_amz_algorithm: str
    x_amz_credential: str
    x_amz_date: str
    x_amz_signature: str
    policy: str
    datalayer: str
    bucket: str
    store: str


@kante.type(description="Temporary Credentials for a file download that can be used by a Client (e.g. in a python datalayer)")
class AccessCredentials:
    """Temporary Credentials for a a file upload."""

    access_key: str
    secret_key: str
    session_token: str
    bucket: str
    key: str
    path: str


@kante.django_type(
    models.BigFileStore,
    description="A BigFileStore represents a large file stored in S3 that can be accessed through a presigned URL. This is used for files that are too large to be uploaded through the standard media store, and are not meant to be accessed directly by the frontend. The presigned URL is valid for 1 hour and can be used to access the file directly from S3 without going through the backend.",
)
class BigFileStore:
    """A BigFileStore represents a large file stored in S3 that can be accessed through a presigned URL. This is used for files that are too large to be uploaded through the standard media store, and are not meant to be accessed directly by the frontend. The presigned URL is valid for 1 hour and can be used to access the file directly from S3 without going through the backend."""

    id: strawberry.auto
    path: str
    bucket: str
    key: str

    @strawberry.field()
    def presigned_url(self, info: Info) -> str:
        """Get a presigned URL for the big file store. This is used to access the big file store directly from the frontend without going through the backend. The URL is valid for 1 hour. If a host is provided, it will replace the AWS_S3_ENDPOINT_URL in the generated URL. This is useful for accessing the big file store through a custom domain or a proxy."""
        datalayer = get_current_datalayer()
        return cast(models.BigFileStore, self).get_presigned_url(datalayer=datalayer)


@kante.django_type(models.MediaStore)
class MediaStore:
    """A MediaStore represents a media file stored in S3 that can be accessed through a presigned URL. This is used for files that are meant to be accessed directly by the frontend, such as images or videos. The presigned URL is valid for 1 hour and can be used to access the file directly from S3 without going through the backend. The MediaStore also has a method to fill its info after the file has been uploaded to S3, and a method to upload a file to S3 and fill its info accordingly."""

    id: strawberry.auto
    path: str
    bucket: str
    key: str

    @kante.django_field(
        description="Get a presigned URL for the media store. This is used to access the media store directly from the frontend without going through the backend. The URL is valid for 1 hour. If a host is provided, it will replace the AWS_S3_ENDPOINT_URL in the generated URL. This is useful for accessing the media store through a custom domain or a proxy."
    )
    def presigned_url(self, info: Info, host: str | None = None) -> str:
        """Get a presigned URL for the media store. This is used to access the media store directly from the frontend without going through the backend. The URL is valid for 1 hour. If a host is provided, it will replace the AWS_S3_ENDPOINT_URL in the generated URL. This is useful for accessing the media store through a custom domain or a proxy."""
        datalayer = get_current_datalayer()
        return cast(models.MediaStore, self).get_presigned_url(datalayer=datalayer, host=host)
