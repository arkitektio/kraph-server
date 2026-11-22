"""Comment query resolvers.

A comment is a claim, so these read the way `instance(id:)` and `link(id:)` do:
the evidence row itself, authorized from what the id points at, never from a
tenant the client names. `commentsFor` and `myMentions` mirror lok's komment
queries so a lok client can move over field-for-field.
"""

import strawberry
from django.db.models import QuerySet
from kante.types import Info

from api import context, types
from api import pagination as api_pagination
from evidence import claims
from evidence import models as evidence_models


def comment(info: Info, id: strawberry.ID) -> types.Comment:
    """One remark, as the log has it."""
    controller = context.get_controller()
    return controller._resolve_comment(str(id), info)  # type: ignore[return-value]


def comments_for(
    info: Info,
    identifier: str,
    object: strawberry.ID,
    pagination: api_pagination.LogPaginationInput | None = None,
) -> list[types.Comment]:
    """Every remark about one external datum, newest first, resolved ones included.

    `pagination` reads one page; without it the newest `MAX_LIMIT` are the answer, as before.

    Addressed the way lok addresses a comment — `(identifier, object)` — which is
    a structure's identity, so this is `Structure.comments` for callers holding
    the datum's address rather than a structure id. A datum nobody has pointed at
    yet has no structure and therefore an empty discussion, which is an answer
    rather than an error.
    """
    organization = context.get_active_organization(info)
    structure = (
        evidence_models.Structure.objects.for_organization(organization)
        .filter(identifier=identifier, object=str(object))
        .first()
    )
    if structure is None:
        return []
    queryset = (
        evidence_models.Comment.objects.for_organization(organization)
        .filter(structure=structure)
        .select_related("assertion")
        .order_by("-created_at", "-pk")
    )
    offset, limit = api_pagination.window(pagination, default=api_pagination.MAX_LIMIT)
    return list(queryset[offset : offset + limit])  # type: ignore[arg-type]


def _mentions(info: Info, resolved: bool | None) -> QuerySet[evidence_models.Comment]:
    """The remarks mentioning the caller, narrowed by whether they were resolved.

    Matched on the caller's subject id — the same string the write path put into
    `mentions` when it walked the descendant tree, and the same one
    `Assertion.subject` records. Resolution is the organization-wide fold
    (`CurrentStanding`), the same answer `Comment.resolved` gives: a remark whose
    winning position says it no longer stands.
    """
    organization = context.get_active_organization(info)
    subject = str(info.context.request.user.id)
    mentioning = evidence_models.Comment.objects.for_organization(organization).filter(
        mentions__contains=[subject]
    )
    if resolved is None:
        return mentioning
    open_ones = claims.standing(mentioning, "comment")
    if resolved:
        return mentioning.exclude(pk__in=open_ones.values("pk"))
    return open_ones


def my_mentions(
    info: Info,
    resolved: bool | None = None,
    pagination: api_pagination.LogPaginationInput | None = None,
) -> list[types.Comment]:
    """Every remark that mentions the caller, newest first. `resolved: false` is the inbox."""
    queryset = (
        _mentions(info, resolved).select_related("assertion").order_by("-created_at")
    )
    return api_pagination.slice_window(queryset, pagination)  # type: ignore[return-value]


def my_mention_count(info: Info, resolved: bool | None = None) -> int:
    """How many remarks mention the caller — past any page. `resolved: false` is the badge."""
    return _mentions(info, resolved).count()
