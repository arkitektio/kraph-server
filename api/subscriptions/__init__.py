"""
Subscriptions submodule for the API.

One root type, `Subscription`, whose fields live in the modules beside this one
(`log.py` for RFC 0020's `assertionRecorded`). This package sat empty for a long
time, after the one subscription the schema used to declare turned out to
publish nothing — see the note above `create_schema` in `api/schema.py`.
"""

from .log import Subscription

__all__ = ["Subscription"]
