import os

from .settings import *  # noqa
from .settings import DATABASES, AUTHENTIKATE

# The test stack publishes postgres and redis on *ephemeral* host ports: docker picks
# them per run, and `tests/conftest.py`'s `django_db_modify_db_settings` overwrites
# PORT and REDIS_URL below with what it picked, before pytest-django creates the test
# database. These values are only the fallback for running a `manage.py` command
# against a stack started by hand: set KRAPH_TEST_DB_PORT / KRAPH_TEST_REDIS_PORT to
# what `docker compose port db 5432` / `port redis 6379` report for it.
DATABASES["default"] = {**DATABASES["default"], "NAME": "testdb", "PORT": os.environ.get("KRAPH_TEST_DB_PORT", "5555"), "HOST": "localhost", "USER": "test", "PASSWORD": "test"}
# Django forces DEBUG=False under the test runner, and authentikate 3.0 refuses static
# tokens when DEBUG is False. These are deliberate test fixtures, so opt in explicitly.
AUTHENTIKATE = {**AUTHENTIKATE, "allow_static_tokens_in_production": True, "static_tokens": {"test": {"sub": "1"}}}
# `allow_unscoped_fallback`: there is no STS to assume a role against under unit tests, and a
# grant that cannot be scoped now refuses rather than quietly returning this service's permanent
# key. Tests that exercise a grant care about its *shape*, not its credentials.
DATALAYER = {"media": {"path": "/tmp/datalayer_test", "jwt_key": "testkey"}, "allow_unscoped_fallback": True}
# The compose stack's redis (tests/integration/docker-compose.yaml); `/ht` pings it.
REDIS_URL = f"redis://localhost:{os.environ.get('KRAPH_TEST_REDIS_PORT', '6666')}/0"
# The subscription tests listen through a stub consumer on the process-local layer;
# production uses channels_redis (settings.py), which the test stack does not need.
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
