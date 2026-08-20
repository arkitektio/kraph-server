"""Projection bookkeeping: how far along the log each view's drawing is.

The projection layer's own state, kept beside the projection rather than on the
schema (`core`) or in the log (`evidence`): `core` is what a view *declares*,
`evidence` is what the organization *recorded*, and neither may know that Apache
AGE exists. These two tables do, and that is the whole of what they know.

Two rows, two questions:

- :class:`Projection` — *is this view's drawing current, and under which schema?*
  One per `Graph` today. It carries a `kind` so that a second projection kind (a
  per-view table, a search index) can sit beside the Cypher one later without a
  rename; nothing reads `kind` yet.
- :class:`PendingProjection` — *which assertions has nobody finished drawing?*
  An outbox row written in the same transaction as the assertion and deleted by
  whatever applies it. Its presence is what makes the cursor
  (`graph_engine.watermark.cursor`) safe against the two things a bare
  ``seq > N`` scan cannot see: an assertion whose transaction is still open when
  the scan runs, and one that committed and then crashed before projecting.

Deliberately **not** stored: a per-graph "applied through seq N" that a write
path advances. It was the first design and it stores a lie — a graph would
report 102 while 101, committed late, was still outstanding. The cursor is
*derived* from the outbox instead; see `watermark.py` for the invariant.
"""

from __future__ import annotations

from django.db import models

from authentikate.models import Organization


class Projection(models.Model):
    """One view's drawing and its standing relative to the log."""

    class Status(models.TextChoices):
        #: Every committed assertion at or below the cursor has been applied here.
        CONSISTENT = "consistent", "Consistent"
        #: Created without a backfill; the drawing has not been made at all yet.
        NEEDS_BACKFILL = "needs_backfill", "Needs backfill"
        #: The namespace was dropped and the replay has not finished — a rebuild
        #: that died leaves this, and reports full lag rather than "caught up over
        #: an empty graph".
        REBUILDING = "rebuilding", "Rebuilding"

    graph = models.OneToOneField("core.Graph", on_delete=models.CASCADE, related_name="projection")
    kind = models.CharField(max_length=32, default="age", help_text="Which kind of projection this is. Only Apache AGE exists today; the column is the seam for a second kind.")
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.NEEDS_BACKFILL)
    derived_through_seq = models.BigIntegerField(
        default=0,
        help_text=(
            "Informational: `Max(Assertion.seq)` of the organization when the last bulk operation "
            "(rebuild, backfill, incremental replay) read the log. Not the cursor — that is derived, "
            "see `graph_engine.watermark.cursor`."
        ),
    )
    schema_hash = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        help_text=(
            "`GraphSchema.hash` this drawing was last fully derived under. Differs from the active "
            "schema's hash when a category's rules moved and the vertices have not been redrawn — "
            "what `manage.py rematerialize --stale` selects on."
        ),
    )
    derived_at = models.DateTimeField(null=True, blank=True, help_text="When `projector.project` last wrote derived properties into this drawing.")
    rebuilt_at = models.DateTimeField(null=True, blank=True, help_text="When this drawing was last dropped and replayed in full.")

    class Meta:
        default_related_name = "projections"

    def __str__(self) -> str:
        return f"{self.kind} projection of graph #{self.graph_id} ({self.status})"


class PendingProjection(models.Model):
    """Outbox: an assertion whose synchronous projection has not finished.

    Written by `GraphController._create_assertion` inside the evidence
    transaction — so it exists exactly when the assertion does — and deleted **by
    id only**: by its own writer once the post-commit projection succeeded, or by
    an organization-wide incremental replay that applied its claims to every
    graph. Never by comparing `seq`: a sweep of "everything below the highest
    applied seq" would delete the one row that recorded a late-committed
    assertion nobody drew.
    """

    assertion = models.OneToOneField("evidence.Assertion", on_delete=models.CASCADE, primary_key=True, related_name="pending_projection")
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="pending_projections")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_related_name = "pending_projections"
        indexes = [models.Index(fields=["organization", "created_at"])]

    def __str__(self) -> str:
        return f"pending projection of assertion {self.assertion_id}"
