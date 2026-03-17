import time
from urllib import error, request
from uuid import uuid4

from django.test import override_settings

from datalayer import models
from datalayer.datalayer import Datalayer


def wait_for_filer(base_url: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        try:
            with request.urlopen(f"{base_url.rstrip('/')}/", timeout=2):
                return
        except error.HTTPError as exc:
            if exc.code in {200, 401}:
                return
        except (error.URLError, ConnectionResetError, OSError):
            time.sleep(1)

    raise TimeoutError(f"SeaweedFS filer at {base_url} did not become ready in time")


@override_settings(
    DATALAYER={
        "media": {
            "path": "media",
            "jwt_key": "a_very_long_random_secret_string_12345",
            "default_max_bytes": 1024 * 1024,
        }
    },
    DATALAYER_URL="http://localhost:18888",
)
def test_signed_upload_round_trip_against_seaweed_filer(backend_stack) -> None:
    del backend_stack

    wait_for_filer("http://localhost:18888")

    datalayer = Datalayer()
    key = f"integration/{uuid4().hex}.txt"
    payload = b"seaweedfs signed upload round trip"

    upload_grant = datalayer.generate_file_upload_url("media", key, max_bytes=len(payload))
    upload_body, upload_content_type = models.build_multipart_upload_payload(
        key.rsplit("/", 1)[-1],
        payload,
        "text/plain",
    )
    upload_request = request.Request(
        datalayer.build_external_url(upload_grant),
        data=upload_body,
        headers={"Content-Type": upload_content_type},
        method=upload_grant.method,
    )

    with request.urlopen(upload_request, timeout=10) as response:
        assert response.status in {200, 201, 202, 204}

    read_grant = datalayer.generate_file_read_url("media", key)
    with request.urlopen(request.Request(datalayer.build_external_url(read_grant), method=read_grant.method), timeout=10) as response:
        assert response.read() == payload

    delete_grant = datalayer.generate_file_delete_url("media", key)
    with request.urlopen(request.Request(datalayer.build_external_url(delete_grant), method=delete_grant.method), timeout=10) as response:
        assert response.status in {200, 202, 204}
