"""Writer-level claim helpers: who said what, and when.

The GraphQL helpers (`tests/writes.py`) speak as the request's context, which is
right for most tests and useless for these: a definition binds *subjects* and
*times*, so its tests need claims by named annotators at chosen moments.
`Assertion.asserted_at` is settable on purpose (`evidence/writer.py`) — belief
time is a fact about the claim, not about ingest.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from core import models as core_models
from evidence import models as evidence_models
from evidence import writer


def classify(graph: core_models.Graph, ref: str, category: core_models.Category, subject: str, asserted_at: datetime | None = None) -> Any:
    """One annotator's claim that a node is of a category, optionally back-dated."""
    assertion = writer.create_assertion(graph.organization, subject=subject, app_id="pytest", asserted_at=asserted_at)
    return writer.create_link(
        graph.organization,
        kind=evidence_models.Link.Kind.CLASSIFIES,
        source_ref=ref,
        target_ref=str(category.term_id),
        assertion=assertion,
        term=category.term,
    )


def retract_classifications(graph: core_models.Graph, ref: str) -> None:
    """Withdraw every standing classification of a node, as a claim.

    Through `writer.retract`, not a queryset `.update(stands=False)`. That used to
    work because `Link` carried its own cached answer, so a test could flip the
    projection with no `Standing` behind it — a shape nothing structurally prevented
    application code from copying. The column is gone and standing is folded from
    the log, so withdrawing a claim now means making one.
    """
    assertion = writer.create_assertion(graph.organization, subject="pytest", app_id="pytest")
    links = evidence_models.Link.objects.for_organization(graph.organization).filter(kind=evidence_models.Link.Kind.CLASSIFIES, source_ref=ref)
    for link in links:
        writer.retract(graph.organization, link, assertion)
