"""The projection layer's own tables: the drawing itself, and its bookkeeping.

Kept beside the projection rather than on the schema (`core`) or in the log
(`evidence`): `core` is what a view *declares*, `evidence` is what the
organization *recorded*, and neither may know how a drawing is stored. These
tables do, and that is the whole of what they know.

**The drawing** — :class:`ProjectionVertex` and :class:`ProjectionEdge` — is
what a view draws, one row per drawn node or edge. It is derived state, exactly
as the Apache AGE namespace it replaced was: rebuildable by `manage.py
reproject`, never a source of truth, and free to destroy. Nothing carries a
foreign key *into* it from evidence or core; its own `graph` key points outward
so a deleted view takes its drawing with it. Only
`graph_engine/projection/table.py` may read or write these rows — the same
one-module rule that kept Cypher in one file
(`tests/projector/test_projector_protocol.py` enforces it).

**The bookkeeping** answers two questions:

- :class:`Projection` — *is this view's drawing current, and under which schema?*
  One per `Graph`. `kind` names the projection kind drawing it.
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
    kind = models.CharField(max_length=32, default="table", help_text="Which kind of projection this is. Only the table kind exists today; the column is the seam for a second kind.")
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


class ProjectionVertex(models.Model):
    """One drawn node: how one view draws one **individual** (RFC 0018).

    An individual is a component of instances the view's categories hold to be
    one thing — the closure of the standing `SAME_AS` claims their rules trust —
    and most often a single instance. `ref` is the component's representative,
    the lowest member uuid, so it is arrival-independent; every member is a
    `ProjectionMember` row, the representative included. `ref` is held as a
    plain value, never a foreign key: the drawing may not hold the log in place,
    and a rebuild must be free to happen while evidence is written. `kind` is
    the claim's `Instance.Kind` — the fact `RetrievedNode.node_type` reads.

    **What the vertex is drawn as lives on `ProjectionLabel`** (RFC 0019): one
    row per category of the view that admits the individual, so a cell the view
    holds to be both Pyramidal and Excitatory is one vertex with two labels. A
    vertex has at least one label; the last label going takes the vertex with it
    (a trigger, migration 0009). `label` and `category_pk` used to be columns
    here, which is why a node two definitions admitted was refused.

    `properties` holds only the **derived** values (`Projector.write_properties`);
    the identity trio (`id`, `category_ids`, `type`) is folded back into the
    record by the reader from the columns and the label rows, so a drawn record
    looks the same as it always did: ``{id, label, labels, properties}``.

    The row id is the drawing's opaque vertex id — reassigned by every rebuild,
    carried on `RetrievedNode.vertex_id`, never identity.
    """

    graph = models.ForeignKey("core.Graph", on_delete=models.CASCADE, related_name="projection_vertices")
    ref = models.UUIDField(help_text="The drawn claim's uuid. A value, not a FK: the drawing never holds evidence in place.")
    kind = models.CharField(max_length=32, help_text="The claim's `Instance.Kind` (ENTITY, NATURAL_EVENT, PROTOCOL_EVENT).")
    properties = models.JSONField(default=dict, blank=True, help_text="Derived properties only; identity lives in the columns.")

    class Meta:
        default_related_name = "projection_vertices"
        constraints = [models.UniqueConstraint(fields=["graph", "ref"], name="one_vertex_per_ref_per_view")]

    def __str__(self) -> str:
        return f"vertex {self.ref} in graph #{self.graph_id}"


class ProjectionLabel(models.Model):
    """One category a drawn vertex is drawn under (RFC 0019).

    `label` is the view's own word for the category (`Category.age_name`) and
    `category_pk` the category row that admitted the individual. A plain integer
    to Django, but backed by a raw composite foreign key
    `(graph_id, category_pk) REFERENCES core_category (graph_id, id)`
    ON DELETE CASCADE (migration 0009, relocated from the vertex — Django cannot
    express a composite FK), so the database itself refuses a label under a
    category its graph does not declare, and a deleted category takes its labels
    with it. NULL passes the constraint (MATCH SIMPLE): only rows an older
    projector drew carry it, and `manage.py reproject` is their repair.

    `graph` is carried redundantly so the per-category views of the namespace
    and the composite FK never join through the vertex. Cascades with the vertex;
    the reverse holds too — a vertex whose last label is deleted is deleted by
    the `projectionlabel_last_label_deletes_vertex` trigger, because a vertex
    drawn under nothing is a node the view does not admit.
    """

    graph = models.ForeignKey("core.Graph", on_delete=models.CASCADE, related_name="projection_labels")
    vertex = models.ForeignKey(ProjectionVertex, on_delete=models.CASCADE, related_name="labels")
    label = models.CharField(max_length=1000, help_text="The view's word for the category (`Category.age_name`).")
    category_pk = models.BigIntegerField(null=True, blank=True, help_text="The category row that admitted this node; composite FK to `core_category (graph_id, id)` in SQL (migration 0009). RFC 0006, RFC 0019.")

    class Meta:
        default_related_name = "projection_labels"
        constraints = [models.UniqueConstraint(fields=["vertex", "category_pk"], name="one_label_per_category_per_vertex")]
        indexes = [
            models.Index(fields=["graph", "label"]),
            # Serves both the composite FK's delete-cascade lookups and the
            # per-category vertex views of the graph's PGQ namespace, which
            # filter on `(graph_id, category_pk)` (RFC 0006).
            models.Index(fields=["graph", "category_pk"]),
        ]

    def __str__(self) -> str:
        return f"label {self.label} on vertex #{self.vertex_id} in graph #{self.graph_id}"


class ProjectionMember(models.Model):
    """One instance a drawn vertex stands for (RFC 0018).

    A vertex holds one row per member of its component, the representative
    included, so any member ref addresses the vertex: `node(id: <member>)`, an
    edge endpoint, an INFORMS target. `(graph, ref)` is unique — one vertex per
    instance per view — which is the constraint that used to sit on the vertex's
    own `ref` and now holds for every member. `graph` is carried redundantly so
    the lookup never joins through the vertex. Cascades with the vertex.
    """

    graph = models.ForeignKey("core.Graph", on_delete=models.CASCADE, related_name="projection_members")
    vertex = models.ForeignKey(ProjectionVertex, on_delete=models.CASCADE, related_name="members")
    ref = models.UUIDField(help_text="An `evidence.Instance` uuid this vertex stands for.")

    class Meta:
        default_related_name = "projection_members"
        constraints = [models.UniqueConstraint(fields=["graph", "ref"], name="one_vertex_per_member_per_view")]

    def __str__(self) -> str:
        return f"member {self.ref} of vertex #{self.vertex_id} in graph #{self.graph_id}"


class ProjectionEdge(models.Model):
    """One drawn edge: how one view draws one link between two drawn nodes.

    Endpoints are foreign keys to the drawn vertices, so erasing a node takes
    every edge touching it — the `DETACH` the protocol promises — by cascade.
    That cascade is **database-level** (migration 0005 rewrites Django's NO
    ACTION constraints to `ON DELETE CASCADE`), because the composite category
    FK on the vertex deletes rows below the ORM, where only SQL can follow.
    Converges on ``(source, target, label)`` exactly as the Cypher ``MERGE``
    pattern did; `graph` is carried redundantly so dropping a namespace and
    listing a view's edges never join through a vertex.
    """

    graph = models.ForeignKey("core.Graph", on_delete=models.CASCADE, related_name="projection_edges")
    source = models.ForeignKey(ProjectionVertex, on_delete=models.CASCADE, related_name="outgoing_edges")
    target = models.ForeignKey(ProjectionVertex, on_delete=models.CASCADE, related_name="incoming_edges")
    label = models.CharField(max_length=1000, help_text="The view's word for the edge category (`Category.age_name`).")
    properties = models.JSONField(default=dict, blank=True)

    class Meta:
        default_related_name = "projection_edges"
        constraints = [models.UniqueConstraint(fields=["source", "target", "label"], name="one_edge_per_endpoints_and_label")]
        indexes = [models.Index(fields=["graph", "label"])]

    def __str__(self) -> str:
        return f"edge {self.source_id} -[{self.label}]-> {self.target_id} in graph #{self.graph_id}"


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
