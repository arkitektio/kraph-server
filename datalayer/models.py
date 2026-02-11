from django.db import models
from django.conf import settings
from datalayer.datalayer import Datalayer
from datalayer.fields import S3Field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types_boto3_s3.type_defs import FileobjTypeDef


class S3Store(models.Model):
    """A S3Store represents a file stored in S3. It has a path in the format s3://bucket/key, and the bucket and key are stored separately for easier access. The path is unique to ensure that we don't have duplicate entries for the same file. The S3Store also has a method to get a presigned URL for the file, which can be used to access the file directly from S3 without going through the backend. The presigned URL is valid for 1 hour."""

    path = S3Field(null=True, blank=True, help_text="The stodre of the image", unique=True)
    key = models.CharField(max_length=1000)
    bucket = models.CharField(max_length=1000)
    populated = models.BooleanField(default=False)

    def delete(self, *args, **kwargs) -> tuple[int, dict[str, int]]:
        """Delete the file from S3 when the S3Store is deleted. This ensures that we don't have orphaned files in S3 when an S3Store is deleted."""
        datalayer = Datalayer()
        s3 = datalayer.s3
        s3.delete_object(Bucket=self.bucket, Key=self.key)
        return super().delete(*args, **kwargs)


class BigFileStore(S3Store):
    """
    Docstring for BigFileStore
    """

    pass

    def fill_info(self) -> None:
        """Fill in the info of the big file store. This is used to populate the big file store with the correct path and mark it as populated. The path is in the format s3://bucket/key. This function should be called after the file has been uploaded to S3."""
        pass

    def get_presigned_url(
        self,
        datalayer: Datalayer,
        host: str | None = None,
    ) -> str:
        """Return a presigned URL for the big file store. This is used to access the big file store directly from the frontend without going through the backend. The URL is valid for 1 hour. If a host is provided, it will replace the AWS_S3_ENDPOINT_URL in the generated URL. This is useful for accessing the big file store through a custom domain or a proxy."""
        s3 = datalayer.s3
        url = s3.generate_presigned_url(
            ClientMethod="get_object",
            Params={
                "Bucket": self.bucket,
                "Key": self.key,
            },
            ExpiresIn=3600,
        )
        return url.replace(settings.AWS_S3_ENDPOINT_URL, host or "")


class MediaStore(S3Store):
    """MediaStore represents a media file stored in S3 that can be accessed through a presigned URL. This is used for files that are meant to be accessed directly by the frontend, such as images or videos. The presigned URL is valid for 1 hour and can be used to access the file directly from S3 without going through the backend. The MediaStore also has a method to fill its info after the file has been uploaded to S3, and a method to upload a file to S3 and fill its info accordingly."""

    def get_presigned_url(self, datalayer: Datalayer, host: str | None = None) -> str:
        """Get a presigned URL for the media store. This is used to access the media store directly from the frontend without going through the backend. The URL is valid for 1 hour. If a host is provided, it will replace the AWS_S3_ENDPOINT_URL in the generated URL. This is useful for accessing the media store through a custom domain or a proxy."""
        s3 = datalayer.s3
        url: str = s3.generate_presigned_url(
            ClientMethod="get_object",
            Params={
                "Bucket": self.bucket,
                "Key": self.key,
            },
            ExpiresIn=3600,
        )
        return url.replace(settings.AWS_S3_ENDPOINT_URL, host or "")

    def fill_info(self) -> None:
        """Fill the info of the media store. This is used to populate the media store with the correct path and mark it as populated. The path is in the format s3://bucket/key. This function should be called after the file has been uploaded to S3."""
        pass

    def put_file(self, datalayer: Datalayer, file: FileobjTypeDef) -> None:
        """Upload a file to the media store. This function is used to upload a file to S3 and fill the info of the media store. The file should be uploaded to S3 before calling this function, and the key and bucket of the media store should be set accordingly. After uploading the file, this function will fill the info of the media store and mark it as populated."""
        s3 = datalayer.s3
        s3.upload_fileobj(file, self.bucket, self.key)
        self.save()
