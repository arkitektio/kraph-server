import logging
from pathlib import PurePosixPath
from collections.abc import Callable
from typing import TYPE_CHECKING
from uuid import uuid4

from django.db import models
from datalayer import base_models
from datalayer.enums import DatalayerStoreKindChoices
from datalayer.datalayer import AccessGrant, Datalayer

if TYPE_CHECKING:
    from types_boto3_s3.type_defs import FileobjTypeDef


logger = logging.getLogger(__name__)


def get_default_upload_token() -> str:
    """Return the default opaque token used sfor storage keys."""
    return uuid4().hex


def build_opaque_storage_key(original_file_name: str, generator: Callable[[], str] = get_default_upload_token) -> str:
    """Build a fully opaque storage key without sembsedding filename metadata."""
    del original_file_name
    return generator()


class StoreManager(models.Manager):
    """Scopes a store proxy to its own `kind`, the way its own table used to."""

    def get_queryset(self) -> models.QuerySet:
        queryset = super().get_queryset()
        kind = self.model.KIND
        return queryset.filter(kind=kind) if kind is not None else queryset

    def create(self, **kwargs):
        kind = self.model.KIND
        if kind is not None:
            kwargs.setdefault("kind", kind)
        return super().create(**kwargs)


class DatalayerStore(models.Model):
    """An object stored behind the S3-backed datalayer.

    One table for every kind of store. `kind` says which proxy owns a row; the Zarr
    columns below are simply unset on the other three kinds, which add no state of their
    own and differ only in behaviour.
    """

    KIND: "str | None" = None

    objects: models.Manager["DatalayerStore"]  # type: ignore[assignment]

    kind = models.CharField(
        max_length=32,
        choices=DatalayerStoreKindChoices.choices,
        help_text="Which kind of object this store points at.",
    )
    path = models.CharField(max_length=1000, null=True, blank=True, help_text="The object-store URI of the file", unique=True)
    key = models.CharField(max_length=1000, help_text="The object key/path within the datalayer bucket.")
    bucket = models.CharField(max_length=1000, help_text="The datalayer bucket/service this store belongs to.")
    original_file_name = models.CharField(max_length=1000, null=True, blank=True, help_text="The original client-provided file name.")
    content_type = models.CharField(max_length=255, null=True, blank=True, help_text="The client-provided content type for the uploaded file.")
    populated = models.BooleanField(default=False, help_text="Whether the store has been populated with a valid path and is ready for use.")

    # --- Zarr only ---
    shape = models.JSONField(null=True, blank=True, help_text="The shape of the Zarr array stored at this location.")
    chunks = models.JSONField(null=True, blank=True, help_text="The chunk size of the Zarr array stored at this location.")
    version = models.CharField(max_length=10, null=True, blank=True, help_text="The Zarr format version of the array stored at this location.")
    dtype = models.CharField(max_length=255, null=True, blank=True, help_text="The dtype of the Zarr array stored at this location.")
    dimension_names = models.JSONField(null=True, blank=True, help_text="The dimension names declared by the Zarr array.")
    fill_value = models.JSONField(null=True, blank=True, help_text="The fill value declared by the Zarr array.")
    attributes = models.JSONField(null=True, blank=True, help_text="The user attributes stored in zarr.json.")
    storage_transformers = models.JSONField(null=True, blank=True, help_text="The storage transformers declared by the Zarr array.")
    chunk_key_encoding = models.JSONField(null=True, blank=True, help_text="The chunk key encoding configuration for the Zarr array.")
    codecs = models.JSONField(null=True, blank=True, help_text="The codec pipeline declared for the Zarr array.")

    def save(self, *args, **kwargs):
        """Stamp the discriminator so a proxy's rows are visible through that proxy."""
        if not self.kind and type(self).KIND is not None:
            self.kind = type(self).KIND
        return super().save(*args, **kwargs)

    def build_store_path(self, datalayer: Datalayer | None = None) -> str:
        """Return the canonical object-store URI for this store."""
        layer = datalayer or Datalayer()
        return layer.build_store_path(self.bucket, self.key)

    def grant_read_access(self, datalayer: Datalayer, host: str | None = None) -> AccessGrant:
        """Return temporary credentials for reading this store."""
        del host
        return datalayer.generate_file_read_url(self.bucket, self.key, store_id=str(self.pk))

    def grant_delete_access(self, datalayer: Datalayer) -> AccessGrant:
        """Return temporary credentials for deleting this store."""
        return datalayer.generate_file_delete_url(self.bucket, self.key, store_id=str(self.pk))

    def fill_info(self, datalayer: Datalayer | None = None) -> None:
        """Finalize the store after a successful upload."""
        raise NotImplementedError("Subclasses must implement fill_info()")

    def delete(self, *args, **kwargs) -> tuple[int, dict[str, int]]:
        """Delete the remote object when the store row is removed."""
        datalayer = Datalayer()

        try:
            datalayer.delete_object(self.bucket, self.key)
        except Exception:
            logger.warning("Unable to delete S3 object %s during store deletion", self.path or self.key)

        return super().delete(*args, **kwargs)

    def get_upload_file_name(self) -> str:
        """Return the client-visible filename to use in multipart uploads."""
        if self.original_file_name:
            return PurePosixPath(self.original_file_name).name

        return self.key.rsplit("/", 1)[-1]


class BigFileStore(DatalayerStore):
    """A large file stored behind the S3-backed datalayer."""

    KIND = DatalayerStoreKindChoices.BIG_FILE
    objects = StoreManager()

    class Meta:
        proxy = True

    def grant_read_access(self, datalayer: Datalayer, host: str | None = None) -> base_models.BigFileAccessGrant:
        """Return temporary credentials for reading this big file."""
        del host
        return datalayer.generate_bigfile_access_grant(self)

    def get_access_grant(self, datalayer: Datalayer) -> base_models.BigFileAccessGrant:
        """Return temporary credentials for reading the object."""
        return self.grant_read_access(datalayer)

    def fill_info(self, datalayer: Datalayer | None = None) -> None:
        """Mark the object as populated and normalize its stored URI."""
        self.path = self.build_store_path(datalayer)
        self.populated = True
        self.save(update_fields=["path", "populated"])

    def get_presigned_url(
        self,
        datalayer: Datalayer,
        host: str | None = None,
    ) -> str:
        """Return the canonical S3 path for the object."""
        del host
        return self.build_store_path(datalayer)

    def calculate_size(self, datalayer: Datalayer) -> int:
        """Calculate the size of the big file by querying the datalayer."""
        return datalayer.get_object_size(self.bucket, self.key)


class MediaStore(DatalayerStore):
    """Media objects stored behind the S3-backed datalayer."""

    KIND = DatalayerStoreKindChoices.MEDIA
    objects = StoreManager()

    class Meta:
        proxy = True

    def grant_read_access(self, datalayer: Datalayer, host: str | None = None) -> base_models.MediaAccessGrant:
        """Return temporary credentials for reading this media object."""
        del host
        return datalayer.generate_media_access_grant(self)

    def get_access_grant(self, datalayer: Datalayer) -> base_models.MediaAccessGrant:
        """Return temporary credentials for reading the object."""
        return self.grant_read_access(datalayer)

    def get_presigned_url(self, datalayer: Datalayer, host: str | None = None) -> str:
        """Return the canonical S3 path for the object."""
        del host
        return self.build_store_path(datalayer)

    def fill_info(self, datalayer: Datalayer | None = None) -> None:
        """Mark the object as populated and normalize its stored URI."""
        self.path = self.build_store_path(datalayer)
        self.populated = True
        self.save(update_fields=["path", "populated"])

    def put_file(self, datalayer: Datalayer, file: "FileobjTypeDef") -> None:
        """Upload a file with the service credentials and finalize the store."""
        datalayer.put_file(
            self.bucket,
            self.key,
            file.read(),
            getattr(file, "content_type", "application/octet-stream"),
        )
        self.fill_info(datalayer)


class ZarrStore(DatalayerStore):
    """Zarr objects stored behind the S3-backed datalayer."""

    KIND = DatalayerStoreKindChoices.ZARR
    objects = StoreManager()

    class Meta:
        proxy = True

    def grant_read_access(self, datalayer: Datalayer, host: str | None = None) -> base_models.ZarrAccessGrant:
        """Return temporary credentials for reading this Zarr prefix."""
        del host
        return datalayer.generate_zarr_access_grant(self)

    def get_access_grant(self, datalayer: Datalayer) -> base_models.ZarrAccessGrant:
        """Return temporary credentials for reading the object prefix."""
        return self.grant_read_access(datalayer)

    def fill_info(self, datalayer: Datalayer | None = None) -> None:
        """Populate Zarr metadata and mark the store as ready.

        Raises:
            FileNotFoundError: If the Zarr metadata file cannot be retrieved.
            ValueError: If the Zarr metadata is invalid or unsupported.
        """
        layer = datalayer or Datalayer()
        self.path = self.build_store_path(layer)
        metadata = layer.get_zarr_metadata(self)
        self.shape = metadata.shape
        self.chunks = metadata.chunks
        self.dtype = metadata.dtype
        self.dimension_names = metadata.dimension_names
        self.fill_value = metadata.fill_value
        self.attributes = metadata.attributes
        self.storage_transformers = metadata.storage_transformers
        self.chunk_key_encoding = metadata.chunk_key_encoding
        self.codecs = metadata.codecs
        self.version = metadata.version
        self.populated = True
        self.save(
            update_fields=[
                "path",
                "shape",
                "chunks",
                "dtype",
                "dimension_names",
                "fill_value",
                "attributes",
                "storage_transformers",
                "chunk_key_encoding",
                "codecs",
                "version",
                "populated",
            ]
        )

    @property
    def c_size(self) -> int:
        """Return the regular chunk shape for callers using the legacy field name."""
        return self.shape[0]

    @property
    def t_size(self) -> int:
        """Return the regular chunk shape for callers using the legacy field name."""
        return self.shape[1]

    @property
    def z_size(self) -> int:
        """Return the regular chunk shape for callers using the legacy field name."""
        return self.shape[2]

    @property
    def y_size(self) -> int:
        """Return the regular chunk shape for callers using the legacy field name."""
        return self.shape[3]

    @property
    def x_size(self) -> int:
        """Return the regular chunk shape for callers using the legacy field name."""
        return self.shape[4]


class ParquetStore(DatalayerStore):
    """Parquet objects stored behind the S3-backed datalayer."""

    KIND = DatalayerStoreKindChoices.PARQUET
    objects = StoreManager()

    class Meta:
        proxy = True

    def grant_read_access(self, datalayer: Datalayer, host: str | None = None) -> base_models.ParquetAccessGrant:
        """Return temporary credentials for reading this parquet object."""
        del host
        return datalayer.generate_parquet_access_grant(self)

    def get_access_grant(self, datalayer: Datalayer) -> base_models.ParquetAccessGrant:
        """Return temporary credentials for reading the object."""
        return self.grant_read_access(datalayer)

    def fill_info(self, datalayer: Datalayer | None = None) -> None:
        """Mark the Parquet store as populated after a successful upload."""
        self.path = self.build_store_path(datalayer)
        self.populated = True
        self.save(update_fields=["path", "populated"])
