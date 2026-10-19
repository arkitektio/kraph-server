"""kraph's hook agent: what the hub's rekuest can ask of this process (``arkitekt_service.hook``).

One action, ``ingest_metrics``: read mikro's change feed of metrics after this organization's
cursor and record what it finds as claims (``evidence.ingest``). It takes the metric a trigger
on CREATED ``@mikro/metric`` was fired for, but only as a nudge -- it reads everything new, not
just that metric -- and a schedule runs it with none, which catches whatever a lost signal
missed. Runs at once are safe: one holds the organization's feed, the others return at once.

Every organization has the agent (rekuest provisions it); nothing is wired. The trigger and the
schedule are the organization's own automation (``docs/wiregram.yaml``).
"""

from __future__ import annotations

from arkitekt_service.feed.consumer import Ended, apply_pages
from arkitekt_service.feed.reader import FeedReader
from arkitekt_service.hook import HookAgent, StructurePort, StructureRef
from authentikate.models import Organization
from django.conf import settings

from evidence import ingest
from graph_engine.controller import GraphController
from graph_engine.projection.context import current_or_default
from kraph_server.contract import contract

agent = HookAgent("kraph", identifier=contract.description.identifier, description="kraph: records what other services observed as claims.")

class FeedHalted(RuntimeError):
    """The organization's feed stopped for good (a restore, a poison entry): a run fails until it is resumed."""


#: How long one run reads before it returns; the next run (or the schedule) goes on from the cursor.
BUDGET_SECONDS = 20.0
#: Entries per page: one transaction here, one request to mikro.
PAGE = 1000


def mikro_reader() -> FeedReader | None:
    """A reader of mikro's metric feed, or None when this hub's kraph is told of no mikro."""
    feed = getattr(settings, "MIKRO_FEED", None)
    if not feed:
        return None
    return FeedReader(url=feed["URL"], producer=feed["IDENTIFIER"], feed=ingest.FEED, issuer=agent.signing_identifier())


@agent.action(args=[StructurePort("metric", ingest.FEED, description="The metric a trigger fired for. A nudge: everything new is read either way.", nullable=True)])
def ingest_metrics(organization: str, metric: StructureRef | None = None) -> dict[str, str | int | None]:
    """Ingest metrics

    Reads mikro's change feed of metrics after this organization's cursor and records every new
    metric as a claim about the datum it measures, every withdrawn one as its retraction. Safe to
    run any number of times, at once or again: each metric is recorded once.
    """
    reader = mikro_reader()
    if reader is None:
        return {"ended": "NO_FEED", "applied": 0}
    # rekuest gives every organization the agent; kraph learns of one when somebody first
    # authenticates in it -- which a schedule may well run before.
    org, _ = Organization.objects.get_or_create(slug=organization)
    controller = GraphController(projector=current_or_default())
    outcome = apply_pages(reader, organization, lambda entries: controller.ingest_metric_page(org, entries), budget_s=BUDGET_SECONDS, limit=PAGE)
    if outcome.ended == Ended.HALTED:
        # A failed run, where the organization's automation shows it -- not a green one.
        raise FeedHalted(f"Reading mikro's metrics for {organization} is halted until someone resumes it: {outcome.halted}")
    return outcome.report()
