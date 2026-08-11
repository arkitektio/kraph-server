"""The relational evidence base.

These tables are the source of truth. Everything in Apache AGE is a *projection*
of what is stored here — droppable, rebuildable, and never authoritative. See
``docs/ARCHITECTURE.md`` §4.1.

Three decisions are baked into these columns and are expensive to reverse:

**Tenancy is the organization, never the graph.** A ``Graph`` is a view over the
organization's evidence, so the same ROI measured in two experiments is one
``Structure`` row that both projections can see. Nothing in this module may grow
a ``graph`` foreign key; if you find yourself wanting one, you want a selector on
``Graph`` instead.

**Time has two axes.** ``measured_at`` is when the world was observed;
``asserted_at`` is when somebody claimed it. They move independently — a
re-analysis run today can assert a fact about an image taken last year — and
collapsing them (as the old single ms-epoch ``timestamp`` property did) makes
"what did we believe on March 3rd" unanswerable.

**Evidence is append-only.** Nothing here is edited in place. Retraction is a
``LifecycleEvent`` row, not a ``DELETE``, because a derived value that dropped a
contributing metric still has to be explainable afterwards.

Provenance boundary: ``koherent``'s ``ProvenanceField`` tracks Django *container
and ontology* rows (``Graph``, ``Category``, ``GraphSchema``). It is deliberately
absent here — for instance data the :class:`Assertion` **is** the provenance, and
two provenance systems over the same rows would eventually disagree.
"""

from __future__ import annotations

import uuid
from typing import Any

from authentikate.models import Organization
from django.db import models

from core.enums import ValueKind
from evidence.managers import OrganizationScopedManager


class LifecycleStatus(models.TextChoices):
    """The states an evidence row can be in."""

    ACTIVE = "active", "Active"
    ARCHIVED = "archived", "Archived"


class Assertion(models.Model):
    """Who claimed something, with what tool, and when they claimed it.

    Every other row in this app points at one of these. An assertion is never
    modified: superseding a claim means writing a new assertion, which is what
    makes ``as_of`` queries possible at all.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="assertions",
        help_text="The tenant this assertion belongs to.",
    )
    subject = models.CharField(
        max_length=1000,
        help_text="Who made the claim — a user id, or the identity of an automated agent.",
    )
    app_id = models.CharField(
        max_length=1000,
        help_text="Which application made the claim.",
    )
    action_name = models.CharField(
        max_length=1000,
        null=True,
        blank=True,
        help_text="Human-readable name of the action that produced this assertion.",
    )
    action_args = models.JSONField(
        default=dict,
        blank=True,
        help_text="Arguments the action ran with, kept so the claim can be reproduced.",
    )
    asserted_at = models.DateTimeField(
        db_index=True,
        help_text="When the claim was made. Belief time — this is the axis `as_of` filters on.",
    )
    recorded_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When we durably stored the claim. Never equal to asserted_at by definition, and only ever used for debugging ingest, not for answering questions.",
    )

    objects = OrganizationScopedManager()
    all_objects = models.Manager()

    class Meta:
        base_manager_name = "all_objects"
        default_manager_name = "all_objects"
        indexes = [
            models.Index(fields=["organization", "asserted_at"]),
            models.Index(fields=["organization", "subject"]),
        ]

    def __str__(self) -> str:
        return f"Assertion by {self.subject} via {self.app_id} at {self.asserted_at}"


class Structure(models.Model):
    """A pointer to an external datum — a Mikro ROI, an image, a file.

    A structure has no value of its own; it is the thing metrics are *about*. Its
    identity is ``(identifier, object)`` scoped to the organization, which is
    exactly why it deduplicates: the same ROI referenced while building two
    different projections is one row, and a metric attached during experiment A
    is visible to a projection built for experiment B.

    That identity is **immutable**. Repointing a structure at a different
    ``object`` is not an edit, it is a different structure — see
    ``GraphController.update_structure``, which rejects it rather than pretending
    a supersede is possible under the uniqueness constraint.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="structures",
    )
    category = models.ForeignKey(
        "core.StructureCategory",
        on_delete=models.CASCADE,
        related_name="evidence_structures",
        help_text="The ontology term for this kind of structure.",
    )
    identifier = models.CharField(
        max_length=1000,
        help_text="The structure identifier, e.g. '@mikro/roi'. Denormalized from the category because uniqueness has to be expressible as a table constraint.",
    )
    object = models.CharField(
        max_length=1000,
        help_text="The id of the external object this structure points at.",
    )
    assertion = models.ForeignKey(
        Assertion,
        on_delete=models.PROTECT,
        related_name="structures",
        help_text="The assertion that first introduced this structure.",
    )
    status = models.CharField(
        max_length=32,
        choices=LifecycleStatus.choices,
        default=LifecycleStatus.ACTIVE,
        help_text="Cache of the latest LifecycleEvent for this row. Derived, not authoritative — the lifecycle log is.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = OrganizationScopedManager()
    all_objects = models.Manager()

    class Meta:
        base_manager_name = "all_objects"
        default_manager_name = "all_objects"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "identifier", "object"],
                name="unique_structure_per_organization",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "category"]),
        ]

    def __str__(self) -> str:
        return f"{self.identifier}:{self.object}"


class Metric(models.Model):
    """A single measured value about a structure.

    The highest-churn table in the system, and the one the sufficient-statistics
    state vector (M2) folds over.

    The value is split across typed columns rather than stuffed into one JSON
    blob so that numeric aggregation stays a database operation.
    :class:`~core.enums.ValueKind` is the canonical type vocabulary — it is the
    enum exposed through GraphQL, and it is strictly more expressive than the
    internal ``PropertyType`` (whose ``POINT_3D`` is ``THREE_D_VECTOR`` here).
    ``PropertyType`` and its three conversion tables are deleted in M4.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="metrics",
    )
    structure = models.ForeignKey(
        Structure,
        on_delete=models.CASCADE,
        related_name="metrics",
        help_text="The structure this metric describes.",
    )
    category = models.ForeignKey(
        "core.MetricCategory",
        on_delete=models.CASCADE,
        related_name="evidence_metrics",
        help_text="The ontology term for this kind of measurement.",
    )
    key = models.CharField(
        max_length=1000,
        help_text="The measurement key, e.g. 'vector_length'.",
    )

    value_kind = models.CharField(
        max_length=32,
        choices=[(k.value, k.value) for k in ValueKind],
        help_text="Which of the value_* columns carries this metric's value.",
    )
    value_num = models.FloatField(
        null=True,
        blank=True,
        help_text="INT and FLOAT values. Numeric so aggregation stays in the database.",
    )
    value_txt = models.TextField(
        null=True,
        blank=True,
        help_text="STRING and CATEGORY values.",
    )
    value_bool = models.BooleanField(null=True, blank=True, help_text="BOOLEAN values.")
    value_time = models.DateTimeField(
        null=True,
        blank=True,
        help_text="DATETIME values. Given a real column rather than an epoch int so it stays orderable and indexable.",
    )
    value_json = models.JSONField(
        null=True,
        blank=True,
        help_text="Vector values (ONE_D through N_VECTOR), stored as a list of floats.",
    )

    unit = models.CharField(max_length=1000, null=True, blank=True)
    confidence = models.FloatField(null=True, blank=True)
    confidence_type = models.CharField(max_length=1000, null=True, blank=True)

    measured_at = models.DateTimeField(
        db_index=True,
        help_text="When the world was observed. The axis a scientist means by 'when'.",
    )
    asserted_at = models.DateTimeField(
        db_index=True,
        help_text="When this measurement was claimed. Denormalized from the assertion so `as_of` filtering does not need a join on the hottest table.",
    )
    assertion = models.ForeignKey(
        Assertion,
        on_delete=models.PROTECT,
        related_name="metrics",
    )
    status = models.CharField(
        max_length=32,
        choices=LifecycleStatus.choices,
        default=LifecycleStatus.ACTIVE,
        help_text="Cache of the latest LifecycleEvent for this row.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = OrganizationScopedManager()
    all_objects = models.Manager()

    class Meta:
        base_manager_name = "all_objects"
        default_manager_name = "all_objects"
        indexes = [
            # The rollup access path: every metric for a structure under one key.
            models.Index(fields=["organization", "structure", "key"]),
            models.Index(fields=["organization", "category"]),
            models.Index(fields=["organization", "asserted_at"]),
        ]

    # NOTE: deliberately not partitioned. `PARTITION BY organization` was specced
    # for this table, but Postgres requires every unique/primary key on a
    # partitioned table to include the partition key, which a bare `id uuid`
    # primary key does not — and Django has no declarative partitioning, so it
    # would mean hand-written RunSQL on the highest-churn table here. With no
    # production rows there is nothing to buy yet. Revisit when volume justifies
    # it, and expect to change the primary key to (organization, id).

    VALUE_COLUMN_FOR_KIND: dict[str, str] = {
        ValueKind.INT.value: "value_num",
        ValueKind.FLOAT.value: "value_num",
        ValueKind.STRING.value: "value_txt",
        ValueKind.CATEGORY.value: "value_txt",
        ValueKind.BOOLEAN.value: "value_bool",
        ValueKind.DATETIME.value: "value_time",
        ValueKind.ONE_D_VECTOR.value: "value_json",
        ValueKind.TWO_D_VECTOR.value: "value_json",
        ValueKind.THREE_D_VECTOR.value: "value_json",
        ValueKind.FOUR_D_VECTOR.value: "value_json",
        ValueKind.N_VECTOR.value: "value_json",
    }

    @property
    def value(self) -> Any:
        """The metric's value, read from whichever column its kind selects.

        INT shares ``value_num`` with FLOAT so that numeric aggregation stays a
        single-column database operation, so it has to be narrowed back on the
        way out — otherwise a cell count of 3 reads back as 3.0 through the API.
        """
        column = self.VALUE_COLUMN_FOR_KIND.get(self.value_kind)
        if column is None:
            raise ValueError(f"Metric {self.pk} has unknown value_kind {self.value_kind!r}")

        raw = getattr(self, column)
        if self.value_kind == ValueKind.INT.value and raw is not None:
            return int(raw)
        return raw

    def __str__(self) -> str:
        return f"{self.key}={self.value}"


class Link(models.Model):
    """Evidence attaching to something, or to another piece of evidence.

    Replaces the ``ShadowLink`` vertex. The refs are deliberately **opaque
    strings**: a target may be a projection-scoped AGE composite id today and an
    ``evidence_entity`` primary key after M7. Keeping them opaque is what makes
    that a re-point rather than a re-architecture, so do not parse them outside
    the projector.
    """

    class Kind(models.TextChoices):
        INFORMS = "informs", "Informs"
        RELATION = "relation", "Relation"
        STRUCTURE_RELATION = "structure_relation", "Structure relation"
        MEASUREMENT = "measurement", "Measurement"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="evidence_links",
    )
    kind = models.CharField(max_length=32, choices=Kind.choices)
    category = models.ForeignKey(
        "core.Category",
        on_delete=models.CASCADE,
        related_name="evidence_links",
        null=True,
        blank=True,
        help_text="The ontology term for this link, where one applies. Plain INFORMS links carry no category.",
    )
    source_ref = models.CharField(
        max_length=1000,
        help_text="Opaque reference to the source. Do not parse outside the projector.",
    )
    target_ref = models.CharField(
        max_length=1000,
        help_text="Opaque reference to the target. Do not parse outside the projector.",
    )
    assertion = models.ForeignKey(
        Assertion,
        on_delete=models.PROTECT,
        related_name="links",
    )
    status = models.CharField(
        max_length=32,
        choices=LifecycleStatus.choices,
        default=LifecycleStatus.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = OrganizationScopedManager()
    all_objects = models.Manager()

    class Meta:
        base_manager_name = "all_objects"
        default_manager_name = "all_objects"
        indexes = [
            models.Index(fields=["organization", "kind", "source_ref"]),
            models.Index(fields=["organization", "kind", "target_ref"]),
        ]

    def __str__(self) -> str:
        return f"{self.source_ref} -{self.kind}-> {self.target_ref}"


class LifecycleEvent(models.Model):
    """An append-only log of retractions and reinstatements.

    Archiving is a row here, never a ``DELETE``, because a derived value that
    stopped counting a metric still has to be explainable. The ``status`` field
    cached on :class:`Structure` / :class:`Metric` / :class:`Link` is a
    projection of this log and can be recomputed from it.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="lifecycle_events",
    )
    target_type = models.CharField(
        max_length=32,
        help_text="What kind of thing the target is: 'structure', 'metric', 'link' or 'entity'.",
    )
    target_id = models.CharField(
        max_length=1000,
        help_text="Opaque reference to the target — an evidence row's uuid, or a projection-scoped entity ref. A CharField rather than a UUIDField precisely because entities are not evidence rows yet; see the note on Link about keeping refs opaque.",
    )
    status = models.CharField(max_length=32, choices=LifecycleStatus.choices)
    at = models.DateTimeField(help_text="When the status change took effect.")
    assertion = models.ForeignKey(
        Assertion,
        on_delete=models.PROTECT,
        related_name="lifecycle_events",
    )

    objects = OrganizationScopedManager()
    all_objects = models.Manager()

    class Meta:
        base_manager_name = "all_objects"
        default_manager_name = "all_objects"
        indexes = [
            models.Index(fields=["organization", "target_type", "target_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.target_type}:{self.target_id} -> {self.status}"
