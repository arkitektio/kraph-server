"""A second database session, for tests about what one transaction can see of another."""

from __future__ import annotations

import psycopg
from django.conf import settings


def raw_connection() -> psycopg.Connection:
    """A session outside Django's connection — the other writer."""
    db = settings.DATABASES["default"]
    return psycopg.connect(host=db["HOST"], port=db["PORT"], dbname=db["NAME"], user=db["USER"], password=db["PASSWORD"], autocommit=False)
