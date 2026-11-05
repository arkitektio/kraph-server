"""
Subscriptions submodule for the API.

One root type, `Subscription`, whose fields live in the modules beside this one
(`log.py` for RFC 0020's `assertionRecorded`, `todos.py` for `todoChanged`). This package sat empty for a long
time, after the one subscription the schema used to declare turned out to
publish nothing — see the note above `create_schema` in `api/schema.py`.
"""

import strawberry

from .log import Subscription as LogSubscription
from .todos import TodoSubscription


@strawberry.type(description="The log, and todo lists, as they are written")
class Subscription(LogSubscription, TodoSubscription):
    """Root subscription type: every field of the modules beside this one."""


__all__ = ["Subscription"]
