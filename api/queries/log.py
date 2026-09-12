"""Reading the log as a log (RFC 0020).

Three ways in. `assertions` is the provenance row by who, what tool and when —
newest first, the way a person reads history. `assertion(id:)` is one act with
every claim it recorded. `changes(afterSeq:)` is the feed: ascending from a
cursor, cut at the committed horizon so a consumer that moves its cursor forward
never skips an act whose transaction committed late (`evidence/log.py`).

Every read is scoped to the caller's organization the way `standings` is: the
client names nothing but a primary key or a seq, and the tenant comes from the
request. An assertion of another organization is refused by id, not answered as
null — the id is a uuid nobody could have guessed, so "not found" and "not
yours" are the same answer and the error says which table it looked in.
"""

from typing import List, Optional

from kante.types import Info
import strawberry
import strawberry_django

from api import context, filters, pagination, types
from evidence import log
from evidence import models as evidence_models


def _page(queryset, page: Optional[pagination.LogPaginationInput]) -> list:
    """The offset/limit window — first hundred by default, clamped at `pagination.MAX_LIMIT`."""
    return pagination.slice_window(queryset, page)


def _scoped(info: Info):
    """This organization's log, and nothing else's."""
    organization = context.get_active_organization(info)
    context.assert_can_access_organization(info, organization)
    return evidence_models.Assertion.objects.for_organization(organization)


def assertions(
    info: Info,
    filters: Optional[filters.AssertionFilter] = None,
    pagination: Optional[pagination.LogPaginationInput] = None,
) -> List[types.Assertion]:
    """The acts of claiming, newest first, by who made them and when."""
    queryset = strawberry_django.filters.apply(filters, _scoped(info).order_by("-seq"), info)
    return _page(queryset, pagination)


def assertion(info: Info, id: strawberry.ID) -> types.Assertion:
    """One act, with everything it recorded reachable from it."""
    found = _scoped(info).filter(id=str(id)).first()
    if found is None:
        raise ValueError(f"Assertion not found with id {id}")
    return found  # type: ignore[return-value]


def changes(info: Info, after_seq: int, limit: int = 100) -> types.Changes:
    """The log forward from a cursor, no further than what has certainly committed.

    Ascending, strictly after `after_seq`, and gated by
    `log.before_every_open_transaction`: a seq handed out to a transaction that
    is still open is not returned, and neither is anything written since that
    transaction began — so no seq below `nextSeq` can appear later, and a
    consumer that stores `nextSeq` misses nothing.
    """
    scoped = _scoped(info)
    limit = max(1, min(int(limit), pagination.MAX_LIMIT))
    rows = list(log.before_every_open_transaction(scoped.filter(seq__gt=int(after_seq)).order_by("seq"))[:limit])
    next_seq = int(rows[-1].seq) if rows else int(after_seq)
    return types.Changes(assertions=rows, next_seq=next_seq, horizon=log.horizon(scoped))  # type: ignore[arg-type]
