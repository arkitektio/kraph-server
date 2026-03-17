from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch
from typing import cast

import jwt
from django.test import override_settings
from kante.types import Info

from datalayer import inputs, models
from datalayer.datalayer import Datalayer
from datalayer.mutations.bigfile import request_bigfile_upload
from datalayer.mutations.media import request_media_upload
from datalayer.mutations._stores import generate_storage_key
from datalayer.mutations.zarr import request_zarr_upload


@override_settings(
    DATALAYER={
        "media": {
            "path": "media-root",
            "jwt_key": "super-secret",
            "default_max_bytes": 512,
        }
    },
    DATALAYER_URL="http://filer.example",
)
def test_generate_file_upload_url_signs_query_jwt() -> None:
    """Upload grants should encode SeaweedFS path and method restrictions in the JWT."""
    datalayer = Datalayer()

    grant = datalayer.generate_file_upload_url("media", "folder/test.png", max_bytes=123)

    relative_url = datalayer.build_relative_url(grant)
    parsed = urlsplit(relative_url)
    query = parse_qs(parsed.query)
    payload = jwt.decode(grant.jwt, "super-secret", algorithms=["HS256"])

    assert parsed.path == "/media-root/folder/test.png"
    assert query["jwt"] == [grant.jwt]
    assert grant.method == "POST"
    assert grant.action == "write"
    assert grant.body_format == "multipart"
    assert grant.path == "/media-root/folder/test.png"
    assert grant.max_bytes == 123
    assert "url" not in grant.model_dump()
    assert payload["allowed_prefixes"] == ["/media-root/folder/test.png"]
    assert payload["allowed_methods"] == ["POST"]
    assert payload["limit"] == 123


@override_settings(
    DATALAYER={
        "media": {
            "path": "media-root",
            "jwt_key": "super-secret",
            "default_max_bytes": 1024,
        },
        "bigfile": {
            "path": "bigfile-root",
            "jwt_key": "big-secret",
            "default_max_bytes": 8192,
        },
        "zarr": {
            "path": "zarr-root",
            "jwt_key": "zarr-secret",
            "default_max_bytes": 2048,
        },
    },
    DATALAYER_URL="http://filer.example",
)
def test_request_media_upload_returns_signed_grant_and_persists_store() -> None:
    """Media uploads should create or reuse a MediaStore and return its upload grant."""
    upload_input = inputs.RequestMediaUploadInput(
        original_file_name="image.png",
        file_size=2048,
        content_type="image/png",
    )

    store = models.MediaStore(
        pk=42,
        key="opaque-id",
        bucket="media",
        path="seaweed://media/opaque-id",
        original_file_name="image.png",
        content_type="image/png",
    )

    with (
        patch("datalayer.mutations._stores.generate_storage_key", return_value="opaque-id"),
        patch.object(models.MediaStore.objects, "get_or_create", return_value=(store, True)) as mocked_get_or_create,
    ):
        result = request_media_upload(cast(Info, None), upload_input)

    parsed = urlsplit(f"{result.path}?jwt={result.jwt}")
    query = parse_qs(parsed.query)
    payload = jwt.decode(result.jwt, "super-secret", algorithms=["HS256"])

    assert result.method == "POST"
    assert result.action == "write"
    assert result.body_format == "multipart"
    assert result.datalayer == "media"
    assert result.key == "opaque-id"
    assert result.original_file_name == "image.png"
    assert result.upload_file_name == "image.png"
    assert result.upload_content_type == "image/png"
    assert result.upload_form_field == "file"
    assert result.path == "/media-root/opaque-id"
    assert result.max_bytes == 2048
    assert parsed.path == "/media-root/opaque-id"
    assert query["jwt"] == [result.jwt]
    assert not hasattr(result, "url")
    assert payload["allowed_prefixes"] == ["/media-root/opaque-id"]
    assert payload["allowed_methods"] == ["POST"]
    assert payload["limit"] == 2048
    assert result.store == 42
    mocked_get_or_create.assert_called_once_with(
        path="seaweed://media/opaque-id",
        defaults={
            "key": "opaque-id",
            "bucket": "media",
            "original_file_name": "image.png",
            "content_type": "image/png",
        },
    )


@override_settings(
    DATALAYER={
        "media": {
            "path": "media-root",
            "jwt_key": "super-secret",
            "default_max_bytes": 1024,
        },
        "bigfile": {
            "path": "bigfile-root",
            "jwt_key": "big-secret",
            "default_max_bytes": 8192,
        },
        "zarr": {
            "path": "zarr-root",
            "jwt_key": "zarr-secret",
            "default_max_bytes": 2048,
        },
    },
    DATALAYER_URL="http://filer.example",
)
def test_request_bigfile_upload_uses_bigfilestore() -> None:
    """Big file uploads should create or reuse a BigFileStore."""
    upload_input = inputs.RequestMediaUploadInput(
        original_file_name="big.bin",
        file_size=4096,
    )
    store = models.BigFileStore(
        pk=24,
        key="big-opaque",
        bucket="bigfile",
        path="seaweed://bigfile/big-opaque",
        original_file_name="big.bin",
    )

    with (
        patch("datalayer.mutations._stores.generate_storage_key", return_value="big-opaque"),
        patch.object(models.BigFileStore.objects, "get_or_create", return_value=(store, True)) as mocked_get_or_create,
    ):
        result = request_bigfile_upload(cast(Info, None), upload_input)

    assert result.store == 24
    assert result.key == "big-opaque"
    assert result.datalayer == "bigfile"
    assert result.original_file_name == "big.bin"
    assert result.upload_file_name == "big.bin"
    assert result.upload_form_field == "file"
    assert result.path == "/bigfile-root/big-opaque"
    mocked_get_or_create.assert_called_once_with(
        path="seaweed://bigfile/big-opaque",
        defaults={
            "key": "big-opaque",
            "bucket": "bigfile",
            "original_file_name": "big.bin",
            "content_type": None,
        },
    )


@override_settings(
    DATALAYER={
        "media": {
            "path": "media-root",
            "jwt_key": "super-secret",
            "default_max_bytes": 1024,
        },
        "bigfile": {
            "path": "bigfile-root",
            "jwt_key": "big-secret",
            "default_max_bytes": 8192,
        },
        "zarr": {
            "path": "zarr-root",
            "jwt_key": "zarr-secret",
            "default_max_bytes": 2048,
        },
    },
    DATALAYER_URL="http://filer.example",
)
def test_request_zarr_upload_uses_zarrstore() -> None:
    """Zarr uploads should create or reuse a ZarrStore."""
    upload_input = inputs.RequestMediaUploadInput(
        original_file_name="array.zarr/.zgroup",
        file_size=512,
    )
    store = models.ZarrStore(
        pk=7,
        key="zarr-opaque",
        bucket="zarr",
        path="seaweed://zarr/zarr-opaque",
        original_file_name="array.zarr/.zgroup",
    )

    with (
        patch("datalayer.mutations._stores.generate_storage_key", return_value="zarr-opaque"),
        patch.object(models.ZarrStore.objects, "get_or_create", return_value=(store, True)) as mocked_get_or_create,
    ):
        result = request_zarr_upload(cast(Info, None), upload_input)

    assert result.store == 7
    assert result.key == "zarr-opaque"
    assert result.datalayer == "zarr"
    assert result.original_file_name == "array.zarr/.zgroup"
    assert result.upload_file_name == ".zgroup"
    assert result.upload_form_field == "file"
    assert result.path == "/zarr-root/zarr-opaque"
    mocked_get_or_create.assert_called_once_with(
        path="seaweed://zarr/zarr-opaque",
        defaults={
            "key": "zarr-opaque",
            "bucket": "zarr",
            "original_file_name": "array.zarr/.zgroup",
            "content_type": None,
        },
    )


def test_generate_storage_key_uses_only_the_generated_id() -> None:
    """Opaque storage keys should not embed any filename metadata."""
    assert generate_storage_key("folder/image.ome.tiff", generator=lambda: "opaque") == "opaque"
    assert generate_storage_key("array.zarr/.zgroup", generator=lambda: "opaque") == "opaque"
