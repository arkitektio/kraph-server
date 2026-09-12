"""The convergence runner: what finishes a drawing the request could not.

Every write draws inside its request; the outbox row it settles afterwards is
the record that it did. When the draw fails after the act committed, the row
stands and the write reports `pending` — and nothing used to apply it until an
operator ran `reproject --incremental` by hand. This module is the runner that
command loops over: one pass per organization with outstanding rows, under the
organization's projection lock, through the same `projector.replay` the manual
command uses, so the two can never disagree about what "applying the outbox"
means.

Policy the runner does **not** take: a graph that is `NEEDS_BACKFILL` or
`REBUILDING` is skipped and named, never rebuilt. The first is an operator's
explicit `backfill=False`; the second, seen while this runner holds the lock,
is a rebuild that died — a fact worth a warning, not a decision an unattended
loop should make about an organization-wide refold. A `--repair` flag is the
place for that, if it is ever wanted.

Known residual: an outbox row whose claims cannot be drawn keeps every pass
for its organization failing (nothing settles, and `since_seq` widening redraws
everything after it each time). The loop logs that at ERROR and backs off per
organization; the fix is the cause, not the runner.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import timedelta

from authentikate.models import Organization
from django.db import connections

from graph_engine import locks, watermark
from graph_engine.projector import DrawingHost
from graph_engine.reports import ReplayReport

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Pass:
    """What one pass did for one organization."""

    organization: Organization
    #: Nothing was owed, so nothing was done — the lock was not even taken.
    idle: bool = False
    #: Another session holds the organization's projection lock (a rebuild, or
    #: another runner); this pass left the organization alone.
    locked_elsewhere: bool = False
    #: `projector.replay`'s report, when a replay ran.
    report: ReplayReport | None = None

    @property
    def settled(self) -> int:
        """Outbox rows this pass cleared; zero when it did not run."""
        return self.report.settled if self.report else 0


def run_once(
    controller: DrawingHost,
    organizations: Iterable[Organization] | None = None,
    *,
    wait_for_lock: bool = False,
    older_than: timedelta | None = None,
) -> list[Pass]:
    """One pass over the organizations: apply what each outbox says is owed.

    `older_than` leaves rows younger than that alone — the runner's grace so it
    does not race a request that committed a moment ago and is drawing right
    now. `wait_for_lock=True` is the manual command's choice (queue behind a
    rebuild); the loop tries once and moves on.
    """
    from graph_engine import projector

    if organizations is None:
        organizations = list(Organization.objects.all().order_by("id"))

    passes: list[Pass] = []
    for organization in organizations:
        if watermark.pending_count(organization) == 0:
            passes.append(Pass(organization=organization, idle=True))
            continue
        with locks.organization_projection_lock(organization, wait=wait_for_lock) as held:
            if not held:
                logger.info("%s: projection lock held elsewhere; leaving this pass to whoever holds it", organization.slug)
                passes.append(Pass(organization=organization, locked_elsewhere=True))
                continue
            report = projector.replay(controller, organization, older_than=older_than)
        _log(organization, report)
        passes.append(Pass(organization=organization, report=report))
    return passes


def _log(organization: Organization, report: ReplayReport) -> None:
    if report.pending == 0:
        logger.info("%s: nothing old enough to apply yet", organization.slug)
        return
    logger.info(
        "%s: %d assertion(s) settled over %d ref(s) in %d graph(s)",
        organization.slug,
        report.settled,
        report.refs,
        len(report.graphs),
    )
    for entry in report.skipped:
        logger.warning("%s: graph #%s %r skipped, %s — needs a full `reproject --graph %s`", organization.slug, entry.graph.pk, entry.graph.name, entry.status, entry.graph.pk)


@dataclass
class Loop:
    """`run_forever`'s state, exposed for the command and for tests."""

    passes: int = 0
    failures: int = 0
    #: Organizations whose last pass raised, keyed by primary key, with the
    #: number of consecutive failures.
    backoff: dict[int, int] = field(default_factory=dict)


def run_forever(
    controller: DrawingHost,
    *,
    interval: float,
    stop: threading.Event,
    older_than: timedelta | None = None,
    max_iterations: int | None = None,
) -> Loop:
    """`run_once`, every `interval` seconds, until `stop` is set.

    A pass that raises is logged and retried next time — after closing every
    database connection, so a Postgres restart (which also drops any session
    lock) is recovered from rather than fatal. Organizations whose pass keeps
    failing are skipped for a growing number of passes (`Loop.backoff`), so one
    poison-pill row does not turn every pass into the same traceback.
    """
    state = Loop()
    while not stop.is_set() and (max_iterations is None or state.passes < max_iterations):
        state.passes += 1
        try:
            organizations = list(Organization.objects.all().order_by("id"))
            due = [org for org in organizations if state.backoff.get(org.pk, 0) <= 0]
            for org in organizations:
                if state.backoff.get(org.pk, 0) > 0:
                    state.backoff[org.pk] -= 1
            for org in due:
                try:
                    run_once(controller, [org], wait_for_lock=False, older_than=older_than)
                    state.backoff.pop(org.pk, None)
                except Exception:  # noqa: BLE001 - the loop must outlive one organization's bad row
                    state.failures += 1
                    strikes = state.backoff.get(org.pk, 0)
                    skip = min(2 ** min(strikes, 6), 64)
                    state.backoff[org.pk] = skip
                    logger.exception("%s: runner pass failed; skipping the next %d pass(es)", org.slug, skip)
                    connections.close_all()
        except Exception:  # noqa: BLE001 - see above
            state.failures += 1
            logger.exception("runner pass failed; retrying in %ss", interval)
            connections.close_all()
        stop.wait(interval)
    return state
