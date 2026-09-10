"""Reading a claim back as a claim.

`node(id:, graph:)` and `relation(id:)` answer with a *drawing* — how a view holds
the thing, derived properties and all. These two answer with the recorded statement:
what was claimed, under which word, by whom, and whether anyone has since said it no
longer stands.

Without them `Instance` and `Link` would be reachable only from the payload of the
write that created them, so "does that still hold?" would be unanswerable a minute
later. Both authorize the way every other evidence read does — the client names a
primary key and never a tenant, so the check comes from the row.
"""

from typing import Optional

from kante.types import Info
import strawberry
import strawberry_django

from api import context, types
from api import filters as api_filters
from api import pagination as api_pagination


def instance(info: Info, id: strawberry.ID) -> types.Instance:
    """One claimed individual, as the log has it.

    Answers for a claim no view admits, which is exactly what distinguishes it from
    `node(id:, graph:)`: that one is a view's answer and is refused where the view
    has none, this one never consults a projection at all.
    """
    controller = context.get_controller()
    # The row itself: a `kante.django_type` resolves from the model, the way
    # `queries.kinds.term` hands back a `Term`.
    return controller._resolve_instance(str(id), info)  # type: ignore[return-value]


def link(info: Info, id: strawberry.ID) -> types.Link:
    """One claim relating two things, as the log has it.

    Three of the eight kinds are never drawn — a measurement and a structure relation
    have no AGE edge, and `INFORMS` drives derivation instead — so for those this is
    the only way to read the claim back.
    """
    controller = context.get_controller()
    return controller.resolve_edge_link(str(id), info)  # type: ignore[return-value]


def standings(
    info: Info,
    id: Optional[strawberry.ID] = None,
    filters: Optional[api_filters.StandingFilter] = None,
    pagination: Optional[api_pagination.LogPaginationInput] = None,
) -> list[types.Standing]:
    """Positions on claims, newest first — on one claim, or across the log.

    With `id`, the same list `Instance.standings` and `Link.standings` return,
    reachable for a claim the caller is holding without having to know which
    table it is in: `target_id` alone, since the ids are uuid4 primary keys of
    five different tables and cannot collide. Without it (RFC 0020), the
    organization's positions by who took them, on what kind of claim and when —
    "what did this reviewer retract last week" — each with its `target`.
    """
    from evidence import models as evidence_models

    organization = context.get_active_organization(info)
    context.assert_can_access_organization(info, organization)

    rows = evidence_models.Standing.objects.for_organization(organization).select_related("assertion").order_by("-at", "-assertion__seq")
    if id is not None:
        rows = rows.filter(target_id=str(id))
    rows = strawberry_django.filters.apply(filters, rows, info)
    return api_pagination.slice_window(rows, pagination)  # type: ignore[arg-type]
