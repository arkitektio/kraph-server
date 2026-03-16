import logging
from urllib import error, request
from urllib.parse import SplitResult, urlsplit, urlunsplit
from uuid import uuid4

from django.db import models
from polymorphic.models import PolymorphicModel
from datalayer.datalayer import Datalayer
from datalayer.fields import StorePathField
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types_boto3_s3.type_defs import FileobjTypeDef


logger = logging.getLogger(__name__)


def build_multipart_upload_payload(filename: str, payload: bytes, content_type: str) -> tuple[bytes, str]:
    boundary = f"----kraph-{uuid4().hex}"
    parts = [
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
        f"Content-Type: {content_type}\r\n\r\n".encode(),
        payload,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def replace_url_base(url: str, host: str | None) -> str:
    if not host:
        return url

    parsed = urlsplit(url)
    replacement = urlsplit(host)
    scheme = replacement.scheme or parsed.scheme
    netloc = replacement.netloc or replacement.path or parsed.netloc
    prefix = replacement.path if replacement.netloc else ""
    path = f"{prefix.rstrip('/')}{parsed.path}" if prefix else parsed.path
    return urlunsplit(SplitResult(scheme, netloc, path, parsed.query, parsed.fragment))


class DatalayerStore(PolymorphicModel):
    """An object stored behind the SeaweedFS datalayer."""

    path = StorePathField(null=True, blank=True, help_text="The object-store URI of the file", unique=True)
    key = models.CharField(max_length=1000)
    bucket = models.CharField(max_length=1000)
    populated = models.BooleanField(default=False)

    def build_store_path(self, datalayer: Datalayer | None = None) -> str:
        layer = datalayer or Datalayer()
        return layer.build_store_path(self.bucket, self.key)

    def grant_read_access(self, datalayer: Datalayer, host: str | None = None):
        grant = datalayer.generate_file_read_url(self.bucket, self.key)
        grant.url = replace_url_base(grant.url, host)
        return grant

    def grant_delete_access(self, datalayer: Datalayer):
        return datalayer.generate_file_delete_url(self.bucket, self.key)

    def delete(self, *args, **kwargs) -> tuple[int, dict[str, int]]:
        """Delete the remote object when the store row is removed."""
        datalayer = Datalayer()
        grant = self.grant_delete_access(datalayer)

        try:
            with request.urlopen(request.Request(grant.url, method=grant.method), timeout=5):
                pass
        except error.HTTPError as exc:
            if exc.code != 404:
                raise
        except error.URLError:
            logger.warning("Unable to delete SeaweedFS object %s during store deletion", self.path or self.key)

        return super().delete(*args, **kwargs)


class BigFileStore(DatalayerStore):
    def fill_info(self) -> None:
        """Mark the object as populated and normalize its stored URI."""
        self.path = self.build_store_path()
        self.populated = True
        self.save(update_fields=["path", "populated"])

    def get_presigned_url(
        self,
        datalayer: Datalayer,
        host: str | None = None,
    ) -> str:
        """Return a signed SeaweedFS read URL for the object."""
        return self.grant_read_access(datalayer, host=host).url


class MediaStore(DatalayerStore):
    """Media objects stored behind the SeaweedFS datalayer."""

    def get_presigned_url(self, datalayer: Datalayer, host: str | None = None) -> str:
        """Return a signed SeaweedFS read URL for the object."""
        return self.grant_read_access(datalayer, host=host).url

    def fill_info(self) -> None:
        """Mark the object as populated and normalize its stored URI."""
        self.path = self.build_store_path()
        self.populated = True
        self.save(update_fields=["path", "populated"])

    def put_file(self, datalayer: Datalayer, file: "FileobjTypeDef") -> None:
        """Upload a file to SeaweedFS using a signed filer URL."""
        grant = datalayer.generate_file_upload_url(self.bucket, self.key)
        payload, content_type = build_multipart_upload_payload(
            self.key.rsplit("/", 1)[-1],
            file.read(),
            getattr(file, "content_type", "application/octet-stream"),
        )
        headers = {"Content-Type": content_type}

        with request.urlopen(request.Request(grant.url, data=payload, headers=headers, method=grant.method), timeout=30):
            pass

        self.fill_info()
