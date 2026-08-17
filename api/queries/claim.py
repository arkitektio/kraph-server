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

from kante.types import Info
import strawberry

from api import context, types
from graph_engine import scalars


def instance(info: Info, id: scalars.GraphID) -> types.Instance:
    """One claimed individual, as the log has it.

    Answers for a claim no view admits, which is exactly what distinguishes it from
    `node(id:, graph:)`: that one is a view's answer and is refused where the view
    has none, this one never consults a projection at all.
    """
    controller = context.get_controller()
    # The row itself: a `kante.django_type` resolves from the model, the way
    # `queries.kinds.term` hands back a `Term`.
    return controller._resolve_instance(str(id), info)  # type: ignore[return-value]


def link(info: Info, id: scalars.GraphID) -> types.Link:
    """One claim relating two things, as the log has it.

    Three of the eight kinds are never drawn — a measurement and a structure relation
    have no AGE edge, and `INFORMS` drives derivation instead — so for those this is
    the only way to read the claim back.
    """
    controller = context.get_controller()
    return controller.resolve_edge_link(str(id), info)  # type: ignore[return-value]


def standings(info: Info, id: strawberry.ID) -> list[types.Standing]:
    """Every position anyone has taken on one claim, newest first.

    The same list `Instance.standings` and `Link.standings` return, reachable by id
    for a claim the caller is holding without having to know which of the two it is.
    Scoped to the organization, and by `target_id` alone: the ids are uuid4 primary
    keys of four different tables, so one cannot collide with another.
    """
    from evidence import models as evidence_models

    organization = context.get_active_organization(info)
    context.assert_can_access_organization(info, organization)

    rows = evidence_models.Standing.objects.for_organization(organization).filter(target_id=str(id)).select_related("assertion").order_by("-at", "-assertion__seq")
    return list(rows)  # type: ignore[arg-type]
