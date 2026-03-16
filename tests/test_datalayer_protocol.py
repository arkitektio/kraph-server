from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch
from typing import cast

import jwt
from django.test import override_settings
from kante.types import Info

from datalayer import inputs, models
from datalayer.datalayer import Datalayer
from datalayer.mutations.upload import request_media_upload


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
    datalayer = Datalayer()

    grant = datalayer.generate_file_upload_url("media", "folder/test.png", max_bytes=123)

    parsed = urlsplit(grant.url)
    query = parse_qs(parsed.query)
    payload = jwt.decode(grant.jwt, "super-secret", algorithms=["HS256"])

    assert parsed.scheme == "http"
    assert parsed.netloc == "filer.example"
    assert parsed.path == "/media-root/folder/test.png"
    assert query["jwt"] == [grant.jwt]
    assert grant.method == "POST"
    assert grant.action == "write"
    assert grant.body_format == "multipart"
    assert grant.path == "/media-root/folder/test.png"
    assert grant.max_bytes == 123
    assert payload["allowed_prefixes"] == ["/media-root/folder/test.png"]
    assert payload["allowed_methods"] == ["POST"]
    assert payload["limit"] == 123


@override_settings(
    DATALAYER={
        "media": {
            "path": "media-root",
            "jwt_key": "super-secret",
            "default_max_bytes": 1024,
        }
    },
    DATALAYER_URL="http://filer.example",
)
def test_request_media_upload_returns_signed_grant_and_persists_store() -> None:
    upload_input = inputs.RequestMediaUploadInput(
        key="uploads/image.png",
        datalayer="media",
        file_size=2048,
        content_type="image/png",
    )

    store = models.MediaStore(pk=42, key="uploads/image.png", bucket="media", path="seaweed://media/uploads/image.png")

    with patch.object(models.MediaStore.objects, "get_or_create", return_value=(store, True)) as mocked_get_or_create:
        result = request_media_upload(cast(Info, None), upload_input)

    parsed = urlsplit(result.url)
    query = parse_qs(parsed.query)
    payload = jwt.decode(result.jwt, "super-secret", algorithms=["HS256"])

    assert result.method == "POST"
    assert result.action == "write"
    assert result.body_format == "multipart"
    assert result.datalayer == "media"
    assert result.key == "uploads/image.png"
    assert result.path == "/media-root/uploads/image.png"
    assert result.max_bytes == 2048
    assert parsed.path == "/media-root/uploads/image.png"
    assert query["jwt"] == [result.jwt]
    assert payload["allowed_prefixes"] == ["/media-root/uploads/image.png"]
    assert payload["allowed_methods"] == ["POST"]
    assert payload["limit"] == 2048
    assert result.store == 42
    mocked_get_or_create.assert_called_once_with(
        path="seaweed://media/uploads/image.png",
        defaults={"key": "uploads/image.png", "bucket": "media"},
    )
