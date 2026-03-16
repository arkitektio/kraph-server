import strawberry
from datalayer import models
from kante.types import Info
import kante
from typing import cast

from datalayer.datalayer import get_current_datalayer


@kante.type(description="A signed SeaweedFS grant for a specific object path.")
class DatalayerAccessGrant:
    url: str
    jwt: str
    path: str
    method: str
    action: str
    body_format: str
    expires_in: int
    max_bytes: int


@kante.type(description="A signed SeaweedFS upload grant tied to a media store.")
class MediaUploadGrant:
    url: str
    jwt: str
    path: str
    method: str
    action: str
    body_format: str
    expires_in: int
    max_bytes: int
    datalayer: str
    key: str
    store: strawberry.ID


@kante.django_type(
    models.BigFileStore,
    description="A BigFileStore represents a large object stored behind the SeaweedFS datalayer.",
)
class BigFileStore:
    """A large object stored behind the SeaweedFS datalayer."""

    id: strawberry.auto
    path: str
    bucket: str
    key: str

    @strawberry.field(description="Get a signed SeaweedFS read grant for the object.")
    def access_grant(self, info: Info, host: str | None = None) -> DatalayerAccessGrant:
        datalayer = get_current_datalayer()
        grant = cast(models.BigFileStore, self).grant_read_access(datalayer=datalayer, host=host)
        return DatalayerAccessGrant(**grant.model_dump())

    @strawberry.field()
    def presigned_url(self, info: Info) -> str:
        """Compatibility field returning the signed SeaweedFS read URL."""
        datalayer = get_current_datalayer()
        return cast(models.BigFileStore, self).get_presigned_url(datalayer=datalayer)


@kante.django_type(models.MediaStore)
class MediaStore:
    """A media object stored behind the SeaweedFS datalayer."""

    id: strawberry.auto
    path: str
    bucket: str
    key: str

    @kante.django_field(description="Get a signed SeaweedFS read grant for the media object.")
    def access_grant(self, info: Info, host: str | None = None) -> DatalayerAccessGrant:
        datalayer = get_current_datalayer()
        grant = cast(models.MediaStore, self).grant_read_access(datalayer=datalayer, host=host)
        return DatalayerAccessGrant(**grant.model_dump())

    @kante.django_field(description="Compatibility field returning the signed SeaweedFS read URL.")
    def presigned_url(self, info: Info, host: str | None = None) -> str:
        """Compatibility field returning the signed SeaweedFS read URL."""
        datalayer = get_current_datalayer()
        return cast(models.MediaStore, self).get_presigned_url(datalayer=datalayer, host=host)
