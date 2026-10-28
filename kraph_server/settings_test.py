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
#: What a test token is unless it says otherwise: kraph's admin, through an app granted all of kraph.
ADMIN_WITH_EVERY_SCOPE = {"roles": ["kraph_admin"], "scope": "openid kraph_all"}

AUTHENTIKATE = {
    **AUTHENTIKATE,
    "allow_static_tokens_in_production": True,
    "static_tokens": {
        name: {**ADMIN_WITH_EVERY_SCOPE, **token}
        for name, token in {
            "test": {"sub": "1"},
            # An app granted only what it reads, for the scope tests (tests/test_scopes.py).
            "readertest": {"sub": "1", "scope": "openid kraph_read"},
            # A colleague who records facts and builds graphs, but curates no vocabulary.
            "editortest": {"sub": "3", "roles": ["kraph_editor"]},
        }.items()
    },
}
# `allow_unscoped_fallback`: there is no STS to assume a role against under unit tests, and a
# grant that cannot be scoped now refuses rather than quietly returning this service's permanent
# key. Tests that exercise a grant care about its *shape*, not its credentials.
# No object store in the test stack: grants are never minted here, so the datalayer only needs a
# media bucket name for the store rows the tests create.
DATALAYER = {"access_key": "test", "secret_key": "test", "media": {"bucket": "media"}, "allow_unscoped_fallback": True}
# The compose stack's redis (tests/integration/docker-compose.yaml); `/ht` pings it.
REDIS_URL = f"redis://localhost:{os.environ.get('KRAPH_TEST_REDIS_PORT', '6666')}/0"
# The subscription tests listen through a stub consumer on the process-local layer;
# production uses channels_redis (settings.py), which the test stack does not need.
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
