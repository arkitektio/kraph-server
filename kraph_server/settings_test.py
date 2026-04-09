from .settings import *  # noqa
from .settings import DATABASES, AUTHENTIKATE

DATABASES["default"] = {**DATABASES["default"], "NAME": "testdb", "PORT": 5555, "HOST": "localhost", "USER": "test", "PASSWORD": "test"}
AUTHENTIKATE = {**AUTHENTIKATE, "STATIC_TOKENS": {"test": {"sub": "1"}}}
DATALAYER = {"media": {"path": "/tmp/datalayer_test", "jwt_key": "testkey"}}
DATALAYER_URL = "http://testserver/datalayer"
