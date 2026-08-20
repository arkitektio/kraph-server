from .settings import *  # noqa
from .settings import DATABASES, AUTHENTIKATE

DATABASES["default"] = {**DATABASES["default"], "NAME": "testdb", "PORT": 5555, "HOST": "localhost", "USER": "test", "PASSWORD": "test"}
# Django forces DEBUG=False under the test runner, and authentikate 3.0 refuses static
# tokens when DEBUG is False. These are deliberate test fixtures, so opt in explicitly.
AUTHENTIKATE = {**AUTHENTIKATE, "allow_static_tokens_in_production": True, "static_tokens": {"test": {"sub": "1"}}}
# `allow_unscoped_fallback`: there is no STS to assume a role against under unit tests, and a
# grant that cannot be scoped now refuses rather than quietly returning this service's permanent
# key. Tests that exercise a grant care about its *shape*, not its credentials.
DATALAYER = {"media": {"path": "/tmp/datalayer_test", "jwt_key": "testkey"}, "allow_unscoped_fallback": True}
DATALAYER_URL = "http://testserver/datalayer"
