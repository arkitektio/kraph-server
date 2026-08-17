"""Reading the standing of a claim back: does it still hold?

The counterpart of :func:`evidence.writer.record_standing`. Nothing here writes.

Existence is not a flag, so it is not read like one. It is a fold over
:class:`~evidence.models.Standing` rows — somebody said this is here, somebody else
said it is not — and the fold takes a **predicate** saying whose claims count.
That predicate is how one graph can hold that a cell exists while the graph next
door does not, with no evidence rewritten and no row belonging to either.

Latest wins, by ``(at, assertion.seq)``. `at` is when the claim took effect, which
is the axis that means something; `seq` breaks ties between claims that took
effect at the same instant, which would otherwise order non-deterministically
under `.first()`. Absence of any claim means it stands — a node whose creation
nobody has disputed is not in limbo.

The tiebreak used to be `recorded_at`, whose own help_text conceded it was "a
tiebreak, not a total order". Two claims written in one request share a
`recorded_at` to the microsecond often enough to matter, and when they do the fold
picks arbitrarily — so the same log could produce two different graphs. `seq` is
assigned by the database, one value per assertion, and cannot tie.
"""

from __future__ import annotations

from typing import Any, Iterable

from django.db.models import Q

from evidence import models as evidence_models

#: Newest first. Both keys, always — see the module docstring.
_LATEST = ("-at", "-assertion__seq")


def standings_about(
    organization: Any,
    target_type: str,
    target_ids: Iterable[str],
    predicate: Q | None = None,
) -> Any:
    """Every standing recorded about these claims, newest first, narrowed by the predicate."""
    queryset = evidence_models.Standing.objects.for_organization(organization).filter(
        target_type=target_type,
        target_id__in=[str(target_id) for target_id in target_ids],
    )
    if predicate is not None:
        queryset = queryset.filter(predicate)
    return queryset.order_by(*_LATEST)


def stands(
    organization: Any,
    target_type: str,
    target_id: str,
    predicate: Q | None = None,
) -> bool:
    """Whether the winning claim says this target stands.

    Prefer :func:`stands_for` when asking about more than one target — this is
    one query per call, and the projector asks about every node in a graph.
    """
    latest = standings_about(organization, target_type, [target_id], predicate).first()
    return True if latest is None else latest.stands


def stands_for(
    organization: Any,
    target_type: str,
    target_ids: Iterable[str],
    predicate: Q | None = None,
) -> dict[str, bool]:
    """The same fold, for many targets in one query.

    Returns an answer for **every** id asked about, including ones nothing has
    claimed anything about — they stand. A caller that had to distinguish "absent
    from this dict" from "retracted" would get it wrong eventually, and the
    distinction carries no meaning: silence is not dissent.

    One query and a Python fold rather than a window function, because the rows
    are already ordered and the set is one graph's nodes. If that stops being
    true, this is the place to put `DISTINCT ON`.
    """
    wanted = [str(target_id) for target_id in target_ids]
    if not wanted:
        return {}

    winner: dict[str, bool] = {}
    for claim in standings_about(organization, target_type, wanted, predicate).values_list("target_id", "stands", named=True):
        # Ordered newest first, so the first claim seen for a target is the one
        # that wins and every later row about it is history.
        winner.setdefault(str(claim.target_id), claim.stands)

    return {target_id: winner.get(target_id, True) for target_id in wanted}


def retracted_ids(
    organization: Any,
    target_type: str,
    target_ids: Iterable[str],
    predicate: Q | None = None,
) -> set[str]:
    """Which of these targets do *not* stand. The inverse of :func:`stands_for`."""
    return {target_id for target_id, standing in stands_for(organization, target_type, target_ids, predicate).items() if not standing}


# ===================================================================
# The cached answer
#
# Everything above folds `Standing` directly and takes a predicate, which is what
# makes per-view disagreement possible. Everything below maintains
# `CurrentStanding`, the organization-wide answer the hot read paths narrow by —
# see that model's docstring for why it exists and why instances are not in it.
# ===================================================================

#: Which kinds of claim get a cached answer. An instance's standing is folded per
#: view instead, because a graph's selector decides whose claims it counts. A
#: comment's is organization grain like a structure's — no selector ever scopes
#: whether a remark stands — so the folded boolean is honest and cached.
CACHED_TARGETS = ("structure", "metric", "link", "comment")


def standing(queryset: Any, target_type: str) -> Any:
    """Narrow a queryset of log rows to the ones that currently stand.

    The replacement for `.filter(stands=True)`, which used to read a boolean on
    the log row itself. An anti-join against the retracted subset rather than a
    join against the standing one, because absence of a claim means a thing
    stands: the vast majority of rows have no `CurrentStanding` at all, and the small
    side of the comparison is the one worth scanning.
    """
    from evidence import models as evidence_models

    retracted = evidence_models.CurrentStanding.all_objects.filter(target_type=target_type, stands=False).values("target_id")
    return queryset.exclude(pk__in=retracted)


def current(organization: Any, target_type: str, target_id: Any) -> bool:
    """The cached answer for one target. Organization-wide, unscoped by any view."""
    from evidence import models as evidence_models

    row = evidence_models.CurrentStanding.objects.for_organization(organization).filter(target_type=target_type, target_id=str(target_id)).first()
    return True if row is None else row.stands


def record_current(organization: Any, target_type: str, target_id: Any, standing: Any) -> bool:
    """Point the cached answer at this standing, and say whether it moved.

    **The return value is the transition, and callers depend on it.**
    `state.merge`/`state.retract` are deltas, not idempotent — folding the same
    retraction twice subtracts a value already taken out — so they must fire on
    the edge, not on every claim. That guard used to be the mutable `stands`
    column on the log row; it is this instead, which is a projection, and which is
    therefore allowed to be compared against and rewritten.

    Nothing is written for an instance: its answer is per-view. Returns ``False``
    for those, since there is no organization-wide edge to report.
    """
    from evidence import models as evidence_models

    if target_type not in CACHED_TARGETS:
        return False

    row = evidence_models.CurrentStanding.all_objects.filter(
        organization=organization,
        target_type=target_type,
        target_id=str(target_id),
    ).first()

    if row is None:
        evidence_models.CurrentStanding.objects.create_for_organization(
            organization=organization,
            target_type=target_type,
            target_id=str(target_id),
            stands=standing.stands,
            standing=standing,
        )
        # A first claim that something stands changes nothing: it already did,
        # because absence is not dissent.
        return standing.stands is False

    moved = row.stands != standing.stands
    row.stands = standing.stands
    row.standing = standing
    row.save(update_fields=["stands", "standing"])
    return moved


def refold_current(organization: Any) -> int:
    """Rebuild every cached answer from the claim log. Returns rows written.

    The honesty test for this projection: drop it, replay it, and the graph must
    not change. `rebuild` calls it before anything reads standing, because
    `project_all` narrows its links by exactly this table.

    Organization-wide, like `refold_state` and for the same reason — the answer it
    caches is organization-grain, so there is no per-graph slice of it to rebuild.
    """
    from django.db import transaction

    from evidence import models as evidence_models

    with transaction.atomic():
        evidence_models.CurrentStanding.objects.for_organization(organization).delete()

        written = 0
        for target_type in CACHED_TARGETS:
            targets = evidence_models.Standing.objects.for_organization(organization).filter(target_type=target_type).values_list("target_id", flat=True).distinct()
            folded = stands_for(organization, target_type, list(targets))

            winners = {}
            for standing in standings_about(organization, target_type, list(targets)).only("id", "target_id", "stands"):
                winners.setdefault(str(standing.target_id), standing)

            # `all_objects`, because `bulk_create` goes through the manager's
            # default queryset and the scoped one deliberately has none. Every row
            # below names its organization explicitly, which is the guarantee the
            # guard exists to enforce.
            evidence_models.CurrentStanding.all_objects.bulk_create(
                [
                    evidence_models.CurrentStanding(
                        organization=organization,
                        target_type=target_type,
                        target_id=target_id,
                        stands=stands_now,
                        standing=winners[target_id],
                    )
                    for target_id, stands_now in folded.items()
                    if target_id in winners
                ]
            )
            written += len(folded)

    return written
