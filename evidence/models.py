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

**Time has two axes.** ``observed_at`` is when the world was observed;
``asserted_at`` is when somebody claimed it. They move independently — a
re-analysis run today can assert a fact about an image taken last year — and
collapsing them (as the old single ms-epoch ``timestamp`` property did) makes
"what did we believe on March 3rd" unanswerable. Every claim carries both (RFC
0015): an :class:`Instance` and a :class:`Link` have an ``observed_at`` exactly
as a :class:`Metric` does, defaulting to the assertion's ``asserted_at`` when
the claimant gave no other time, so a rule on ``OBSERVED_AT`` is total.

**Evidence is append-only.** Nothing here is edited in place. Retraction is a
:class:`Standing` saying the thing no longer stands, not a ``DELETE``, because a
derived value that dropped a contributing metric still has to be explainable
afterwards. Attestation is the same row with ``stands=True``: there is no
"un-archive" operation, only somebody newly claiming the thing is there.

**Nothing here names a graph's schema.** Every reference out of this app goes to
the organization's own vocabulary — :class:`Term`, :class:`StructureKind`,
:class:`MetricKind` — and every one of those is ``PROTECT``, never ``CASCADE``. A
word that has been used cannot be deleted; retire it instead.

These used to point at ``core.Category``, which belongs to one graph. That was
wrong twice over. It bound a claim to a single view, so one annotator's
classification could not be seen by a second — against the first axiom above. And
because ``Category.graph`` cascades, deleting a graph once destroyed the
organization-scoped ``Instance`` rows other projections were built from; a ``PROTECT``
was added to stop it. There is no such foreign key any more, so that failure is
not guarded against, it is **unreachable** — and deleting a graph or one of its
categories is now simply allowed, because a view is only a view.

Provenance boundary: ``koherent``'s ``ProvenanceField`` tracks Django *container
and ontology* rows (``Graph``, ``Category``, ``GraphSchema``). It is deliberately
absent here — for instance data the :class:`Assertion` **is** the provenance, and
two provenance systems over the same rows would eventually disagree.
"""

from __future__ import annotations

import uuid
from typing import Any

from authentikate.models import Organization
from datalayer import models as datalayer_models
from django.db import models

from core.enums import ValueKind
from evidence.managers import OrganizationScopedManager


#: The kinds of claim a :class:`Standing` can be about — one per table that holds
#: recorded statements. A plain tuple rather than a `TextChoices`, because the
#: values name *other tables* rather than states of this one. The instance value
#: is ``"node"`` — the historical spelling `writer._TARGET_TYPES` writes and every
#: stored `Standing.target_type` carries; renaming it would mean rewriting the
#: log, which `0008_instance_and_standing.py` explains is exactly what is refused.
CLAIM_TARGETS = ("structure", "metric", "link", "node", "comment")

#: The Postgres sequence backing :attr:`Assertion.seq`.
#:
#: A hand-made sequence rather than a `BigAutoField`, because Django permits an
#: auto field only as a primary key and the primary key here is deliberately a
#: uuid — identity must not carry insertion order, since clients hold it. The
#: sequence is created by the migration that adds the column, and the column
#: takes its value from `db_default`, so the database assigns it and no writer
#: can pass one in.
ASSERTION_SEQ = "evidence_assertion_seq"


class Assertion(models.Model):
    """Who claimed something, with what tool, and when they claimed it.

    Every other row in this app points at one of these. An assertion is never
    modified: superseding a claim means writing a new assertion, which is what
    makes ``as_of`` queries possible at all.

    **This is also where the log's total order lives.** See :attr:`seq`.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    seq = models.BigIntegerField(
        unique=True,
        editable=False,
        db_default=models.Func(
            function="nextval",
            template=f"nextval('{ASSERTION_SEQ}')",
            output_field=models.BigIntegerField(),
        ),
        help_text=(
            "Monotonic position in the organization-spanning log. The identity stays the uuid — "
            "clients hold it, and a sequence would leak insertion order into an external handle — "
            "but every fold needs an order to replay in, and until this existed there was none. "
            "Replay ordered by `measured_at`, which is world time: backfillable, not monotonic "
            "with arrival, and with no tiebreak. "
            "On the **assertion** and nowhere else, because an assertion is already the unit of "
            "authorship — a set of claims made together by one actor in one act is one assertion — "
            "so one column orders the whole log and the rows within an act are simultaneous, which "
            "is what they are. "
            "Assigned at insert, not at commit, so a reader polling `seq > cursor` can skip a row "
            "that committed late; gate the cursor on `pg_snapshot_xmin(pg_current_snapshot())` "
            "rather than serializing the write path, which would throttle bulk ingest."
        ),
    )
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
    action_id = models.CharField(
        max_length=1000,
        null=True,
        blank=True,
        db_index=True,
        help_text="Identity of the action that produced this assertion, where there was one. `ProvenanceContext` has always carried this; the first version of this model dropped it, which left provenance unable to name what actually ran.",
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


def _default_observed_at(claim: Any) -> None:
    """Fill a claim's ``observed_at`` from its assertion when the claimant gave none.

    Called from :meth:`Instance.save` and :meth:`Link.save` — the column is NOT
    NULL, and "when it was claimed" is the honest answer when nobody said when
    the world was in that state. ``Metric`` does the same through
    :func:`evidence.writer.record_metric`. A ``bulk_create`` bypasses ``save`` and
    so must supply the column itself; none of the three claim tables is bulk
    written today.
    """
    if claim.observed_at is None:
        claim.observed_at = claim.assertion.asserted_at


CONFIDENCE_HELP_TEXT = (
    "How sure the claimant was, 0 to 1. Null means they gave no number — which is not 1.0 and not 0.0: "
    "a `CONFIDENCE` rule admits only claims that carry one (RFC 0016)."
)


def _confidence_field() -> Any:
    """The same nullable unit-interval float on every claim table (RFC 0016)."""
    return models.FloatField(null=True, blank=True, help_text=CONFIDENCE_HELP_TEXT)


def _confidence_constraint(table: str) -> Any:
    """The database refuses a confidence outside [0, 1]. The input layer refuses
    it first; this is for every writer that is not the API."""
    return models.CheckConstraint(
        condition=models.Q(confidence__isnull=True) | models.Q(confidence__gte=0.0, confidence__lte=1.0),
        name=f"{table}_confidence_in_unit_interval",
    )


class Term(models.Model):
    """A word this organization uses for a kind of thing — "AIS", "Mitosis", "IS_CONNECTED_TO".

    The organization's vocabulary, and **what the log names**. A claim says "this
    node is an AIS", not "this node is *that graph's* AIS row" — so the thing it
    points at has to outlive, and be shared by, every view.

    It used to point at `core.Category`. That was wrong for one reason and right
    for none: a `Category` is created from a graph's schema definition and holds
    `age_name`, `definition`, `property_definitions` and layout, all meaningless
    outside the graph that owns them. Binding a claim to one meant one annotator's
    classification could not be seen by a second view, which contradicts the axiom
    that evidence is shared across the organization.

    So the split is not "vocabulary versus schema" — it is **which half the log
    may name**. `Category` keeps everything it had, including its graph, and gains
    a foreign key to the term it declares. This carries only what is true
    independently of any view:

    - ``key`` — the word itself.
    - ``kind`` — what sort of thing it names. In identity because "AIS" as an
      entity and "AIS" as a relation are different terms, and because it is all
      the projector needs to reach an event's `AGE_INPUT_EDGE`/`AGE_OUTPUT_EDGE`,
      which are constants of the kind rather than of the graph.

    Everything else is decoration and nullable, exactly as on :class:`StructureKind`
    — which is the same idea for external data, and whose docstring records that it
    left the `Category` hierarchy for this same reason.

    Minted lazily by :func:`evidence.writer.ensure_term`, like the two kinds below:
    refusing to record a claim because no graph had declared the word would be
    refusing a fact on a bookkeeping technicality.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="terms",
    )
    kind = models.CharField(
        max_length=32,
        help_text="What sort of thing this term names — ENTITY, RELATION, NATURAL_EVENT, and so on. Mirrors `core.enums.CategoryKindChoices`.",
    )
    key = models.CharField(
        max_length=1000,
        help_text="The word itself, e.g. 'AIS'. What a classification claim means when it names this term.",
    )
    label = models.CharField(max_length=1000, null=True, blank=True)
    description = models.CharField(max_length=1000, null=True, blank=True)
    purl = models.CharField(
        max_length=1000,
        null=True,
        blank=True,
        help_text="Persistent URL, where this term corresponds to a published ontology term.",
    )
    color = models.JSONField(max_length=1000, null=True, blank=True, help_text="Display colour as RGBA.")
    image = models.ForeignKey(
        datalayer_models.MediaStore,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = OrganizationScopedManager()
    all_objects = models.Manager()

    class Meta:
        base_manager_name = "all_objects"
        default_manager_name = "all_objects"
        constraints = [models.UniqueConstraint(fields=["organization", "kind", "key"], name="unique_term_per_organization")]

    def __str__(self) -> str:
        return f"{self.kind}:{self.key}"


class StructureKind(models.Model):
    """A kind of external datum this organization knows about — a Mikro ROI, an image.

    Organization vocabulary, not schema. Three things distinguish it from the
    `core.Category` hierarchy it used to live in:

    - ``materialize()`` never created one. ``GraphExtensionsInput`` has no
      ``structures`` field and says so: structures are resolved dynamically from
      their identifier at write time.
    - It has no Apache AGE presence. Structures have been relational rows since
      the evidence base landed, and the old ``get_age_vertex_name()`` returned the
      constant ``"Structure"`` regardless.
    - ``identifier`` is owned by another service. ``@mikro/roi`` is not a per-graph
      concept, so N copies of it — one per graph — was duplication with no meaning.

    Being organization-scoped is what lets a measurement be recorded without
    naming a graph at all.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="structure_kinds",
    )
    identifier = models.CharField(
        max_length=1000,
        help_text="The structure identifier, e.g. '@mikro/roi'. Owned by the service that produces the datum.",
    )
    label = models.CharField(max_length=1000, null=True, blank=True)
    description = models.CharField(max_length=1000, null=True, blank=True)
    purl = models.CharField(
        max_length=1000,
        null=True,
        blank=True,
        help_text="Persistent URL, where this kind corresponds to a published ontology term.",
    )
    color = models.JSONField(max_length=1000, null=True, blank=True, help_text="Display colour as RGBA.")
    image = models.ForeignKey(
        datalayer_models.MediaStore,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = OrganizationScopedManager()
    all_objects = models.Manager()

    class Meta:
        base_manager_name = "all_objects"
        default_manager_name = "all_objects"
        constraints = [models.UniqueConstraint(fields=["organization", "identifier"], name="unique_structure_kind_per_organization")]

    def __str__(self) -> str:
        return self.identifier


class MetricKind(models.Model):
    """A kind of measurement that can be made about a structure kind.

    Identity is ``(organization, structure_kind, key, value_kind)``.

    **The structure kind** is in it because `vector_length` on an ROI and on a
    Mask are separate quantities. The old model enforced ``(graph, key)`` while
    looking up by ``(graph, key, structure_category)``, so two metrics named
    `area` on different structures collided.

    **The value kind** is in it because a disagreement about *what type a thing
    is* is a disagreement about what is being measured. One tool recording
    `confidence` as a float and another as a category label are measuring two
    different quantities that happen to share a name, and the alternative —
    rejecting whichever declaration arrived second — refuses a fact about the
    world because someone else reached the key first. Note the cost is bounded:
    `ValueKind` has eleven members, so a key can fan out to eleven terms and no
    further. :func:`evidence.writer.ensure_metric_kind` additionally keeps
    inference from forking a key, so in practice this is one term.

    **Provenance is deliberately not in it**, and the value-kind argument above
    does not extend to it. Which tool measured something is not a claim about
    what the quantity *is*, so folding it in would fragment the aggregation
    grain — `MEAN` over a key would become one mean per tool with nothing to
    combine them — and `action_id` is per-deployment, so cardinality would be
    unbounded rather than eleven. It lives on each metric's :class:`Assertion`,
    and "only what AI_Model_X measured" is a read-time question answered
    reversibly by a conflict policy or a graph selector.

    Because the value kind is part of identity, `State`'s grain carries it too —
    otherwise two terms would fold into one row and `MEAN` would divide a numeric
    sum by a count that included strings.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="metric_kinds",
    )
    structure_kind = models.ForeignKey(
        StructureKind,
        on_delete=models.CASCADE,
        related_name="metric_kinds",
        help_text="The kind of structure this measurement describes.",
    )
    key = models.CharField(max_length=1000, help_text="The measurement key, e.g. 'vector_length'.")
    value_kind = models.CharField(
        max_length=32,
        choices=[(k.value, k.value) for k in ValueKind],
        help_text="What type of value this measurement carries. Non-null: a term whose type is unknown cannot say which column its values belong in.",
    )
    label = models.CharField(max_length=1000, null=True, blank=True)
    description = models.CharField(max_length=1000, null=True, blank=True)
    purl = models.CharField(max_length=1000, null=True, blank=True)
    color = models.JSONField(max_length=1000, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = OrganizationScopedManager()
    all_objects = models.Manager()

    class Meta:
        base_manager_name = "all_objects"
        default_manager_name = "all_objects"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "structure_kind", "key", "value_kind"],
                name="unique_metric_kind_per_value_kind",
            )
        ]
        indexes = [
            # The undeclared-write lookup: every term for a key, to decide
            # whether inference may mint a new one.
            models.Index(fields=["organization", "structure_kind", "key"]),
        ]

    def __str__(self) -> str:
        # The value kind is part of the name, not decoration: two terms for one
        # key otherwise print identically, in the admin and in the error that
        # exists to tell them apart.
        return f"{self.structure_kind.identifier}.{self.key}: {self.value_kind}"


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
    kind = models.ForeignKey(
        StructureKind,
        on_delete=models.PROTECT,
        related_name="structures",
        help_text="The organization's term for this kind of structure.",
    )
    identifier = models.CharField(
        max_length=1000,
        help_text="The structure identifier, e.g. '@mikro/roi'. Denormalized from `kind` because "
        "uniqueness has to be expressible as a table constraint, and **this column is the one that "
        "counts**: the unique constraint and every structure filter read it, not the foreign key. "
        "`ensure_structure` sets the two consistently and nothing else should write either.",
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
    #: No cached `stands`, and deliberately. It used to live here: `writer.record_standing`
    #: wrote the claim and flipped this boolean in one transaction, which made a
    #: log table mutable and blocked `REVOKE UPDATE`. The answer now lives in
    #: :class:`CurrentStanding`, a projection with the same index and the same query
    #: cost, and :func:`evidence.claims.standing` is how a queryset narrows by it.
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
            models.Index(fields=["organization", "kind"]),
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
    kind = models.ForeignKey(
        MetricKind,
        on_delete=models.PROTECT,
        related_name="metrics",
        help_text="The organization's term for this kind of measurement.",
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
    confidence = _confidence_field()
    confidence_type = models.CharField(
        max_length=1000,
        null=True,
        blank=True,
        help_text="What kind of number `confidence` is — a method's own score, a p-value. Metric-only: it annotates a measurement method.",
    )

    observed_at = models.DateTimeField(
        db_index=True,
        help_text=(
            "When the world was observed. The axis a scientist means by 'when'. "
            "Was `measured_at` until RFC 0015 gave every claim the same column under one name."
        ),
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
    #: No cached `stands`, and deliberately. It used to live here: `writer.record_standing`
    #: wrote the claim and flipped this boolean in one transaction, which made a
    #: log table mutable and blocked `REVOKE UPDATE`. The answer now lives in
    #: :class:`CurrentStanding`, a projection with the same index and the same query
    #: cost, and :func:`evidence.claims.standing` is how a queryset narrows by it.
    created_at = models.DateTimeField(auto_now_add=True)

    objects = OrganizationScopedManager()
    all_objects = models.Manager()

    class Meta:
        base_manager_name = "all_objects"
        default_manager_name = "all_objects"
        indexes = [
            # The rollup access path: every metric for a structure under one key.
            models.Index(fields=["organization", "structure", "key"]),
            models.Index(fields=["organization", "kind"]),
            models.Index(fields=["organization", "asserted_at"]),
        ]
        constraints = [_confidence_constraint("metric")]

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
    strings**, and every one of them is now a bare uuid — a :class:`Instance`, a
    :class:`Structure`, or another ``Link``. They used to be able to hold a
    projection-scoped ``{age_name}:{uuid}`` composite; keeping them opaque
    throughout is what made removing that prefix a re-point rather than a
    re-architecture. Do not parse them, and in particular do not infer what a
    ref points at from its shape — every kind of ref looks alike now. ``kind``
    is what says which end is which.
    """

    class Kind(models.TextChoices):
        INFORMS = "informs", "Informs"
        RELATION = "relation", "Relation"
        STRUCTURE_RELATION = "structure_relation", "Structure relation"
        MEASUREMENT = "measurement", "Measurement"
        # Which entities took part in an event, and on which side. The direction
        # is in the kind rather than a column because `(organization, kind,
        # source_ref)` is already indexed, so asking "what went into this event"
        # stays one indexed lookup.
        PARTICIPATES_AS_INPUT = "participates_as_input", "Participates as input"
        PARTICIPATES_AS_OUTPUT = "participates_as_output", "Participates as output"
        # "This node is an AIS" is a claim, and claims are the thing two
        # annotators disagree about. It used to be the `Instance.category` foreign
        # key — written once at creation, never updated anywhere — so there was
        # exactly one classification per node forever, reclassifying meant
        # archiving the node and creating a different one, and a category had no
        # set of claims it could be *defined* over.
        CLASSIFIES = "classifies", "Classifies"
        # "These two AIS are the same one." Every observation mints its own
        # instance — nothing reuses a node id, because an observation cannot be
        # asked to know about a prior one — so identity *between* observations
        # has to be a claim in its own right, contestable and retractable like
        # any other.
        #
        # An equivalence: symmetric and transitive, with no primary. Whoever
        # asserted first is not thereby canonical; that would make identity an
        # accident of arrival order. `evidence.identity` folds the claims into
        # components, which is what makes "everything known about this thing" a
        # single indexed lookup rather than a traversal.
        #
        # **Entities only.** Two structures are never "the same": a structure is
        # a pointer to an external datum, already idempotent by
        # `(identifier, object)`, so sameness there is either a duplicate row
        # (which cannot happen) or a claim about the entities they inform.
        SAME_AS = "same_as", "Same as"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="evidence_links",
    )
    kind = models.CharField(max_length=32, choices=Kind.choices)
    term = models.ForeignKey(
        Term,
        on_delete=models.PROTECT,
        related_name="evidence_links",
        null=True,
        blank=True,
        help_text="The organization's word for this link, where one applies. Plain INFORMS links carry no term.",
    )
    source_ref = models.CharField(
        max_length=1000,
        help_text="Opaque uuid of the source row. Do not parse.",
    )
    target_ref = models.CharField(
        max_length=1000,
        help_text="Opaque uuid of the target row. Do not parse.",
    )
    role = models.CharField(
        max_length=1000,
        null=True,
        blank=True,
        help_text="Which role the source plays, for participation links. The schema names it; it is projected as a property on the edge rather than folded into the edge label, so that 'everything that went into this event' stays answerable without enumerating roles.",
    )
    assertion = models.ForeignKey(
        Assertion,
        on_delete=models.PROTECT,
        related_name="links",
    )
    observed_at = models.DateTimeField(
        db_index=True,
        help_text=(
            "When the world was in this state: a relation held, a participation happened, a classification "
            "applied. Defaults to the assertion's `asserted_at` on save when the claimant gave no other time "
            "(RFC 0015), so `OBSERVED_AT` rules are total."
        ),
    )
    confidence = _confidence_field()
    #: No cached `stands`, and deliberately. It used to live here: `writer.record_standing`
    #: wrote the claim and flipped this boolean in one transaction, which made a
    #: log table mutable and blocked `REVOKE UPDATE`. The answer now lives in
    #: :class:`CurrentStanding`, a projection with the same index and the same query
    #: cost, and :func:`evidence.claims.standing` is how a queryset narrows by it.
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
        constraints = [_confidence_constraint("link")]

    def save(self, *args: Any, **kwargs: Any) -> None:
        _default_observed_at(self)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.source_ref} -{self.kind}-> {self.target_ref}"


class Comment(models.Model):
    """A remark somebody made about a structure. Append-only, like every claim.

    The port of lok's `komment.Comment`, restated in this system's terms. lok
    addresses a comment by ``(identifier, object)`` — which is exactly a
    :class:`Structure`'s identity — so here a comment points at the structure row
    itself, and the structure is what carries the discussion: the same ROI
    commented on from two experiments is one thread.

    What lok kept as mutable columns is evidence here:

    - ``user`` and ``created_at`` are the :class:`Assertion` — who said it, with
      which app, and when they said it.
    - ``resolved`` / ``resolved_by`` were an in-place update. Resolution is a
      :class:`Standing` now: ``stands=False`` says the remark no longer stands —
      whether the author withdrew it or a reviewer resolved it, and the standing's
      own assertion records which — and ``stands=True`` reopens it. Both stay on
      the record, latest wins, and two people can disagree, exactly as they can
      about a metric. The folded answer is cached in :class:`CurrentStanding`
      (comments are organization grain, so the fold is honest here in the way it
      deliberately is not for instances).
    - ``mentions`` was an M2M to the user model. The evidence layer knows actors
      only as subject strings (`Assertion.subject`), so mentions are a JSON list
      of those, extracted from the descendant tree on write.

    The body itself — ``descendants`` — is the rich tree lok renders
    (LEAF/MENTION/PARAGRAPH), stored verbatim so a lok frontend can post and
    render the identical shape; ``text`` is the plain rendering of its leaves,
    derived on write so the body stays searchable without parsing JSON.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    structure = models.ForeignKey(
        Structure,
        on_delete=models.PROTECT,
        related_name="comments",
        help_text="The external datum this remark is about. The structure carries the thread.",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="replies",
        help_text="The comment this replies to, for threading. PROTECT where lok cascades: nothing here deletes.",
    )
    assertion = models.ForeignKey(
        Assertion,
        on_delete=models.PROTECT,
        related_name="comments",
        help_text="The act of commenting: who said it, with which app, and when.",
    )
    descendants = models.JSONField(
        default=list,
        help_text="The rich representation of the remark — a tree of LEAF/MENTION/PARAGRAPH nodes, shape-compatible with lok's komment descendants.",
    )
    text = models.TextField(
        blank=True,
        default="",
        help_text="The plain-text rendering of the descendant tree's leaves, derived on write. Searchable; never authoritative over `descendants`.",
    )
    mentions = models.JSONField(
        default=list,
        help_text="Subject ids mentioned in the descendant tree, extracted on write. Strings, the same vocabulary as `Assertion.subject` — the evidence layer holds no user rows.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = OrganizationScopedManager()
    all_objects = models.Manager()

    class Meta:
        base_manager_name = "all_objects"
        default_manager_name = "all_objects"
        indexes = [
            # The thread read: every remark about one structure, newest first.
            models.Index(fields=["organization", "structure", "-created_at"]),
            models.Index(fields=["organization", "parent"]),
        ]

    def __str__(self) -> str:
        return f"comment on {self.structure_id}: {self.text[:40]}"


class Standing(models.Model):
    """Somebody's position on whether a claim stands. Append-only.

    **The vote, not the claim.** The claims are the other tables in this module —
    an :class:`Instance` ("there is a cell here"), a :class:`Link` ("this is an
    AIS"), a :class:`Metric` ("it is 45.2µm"), a :class:`Structure`. This says
    whether one of them still holds, and who says so. It was called ``Claim``,
    which made the word mean two things at once: every docstring in the app uses
    "claim" for the statements, so the narrow sense had to be inferred from
    context every time.

    This replaces a ``LifecycleEvent`` whose ``status`` was an enum, and the
    change is not cosmetic. A lifecycle event modelled retraction as a *state
    transition on a row*, which made "un-archiving" an operation somebody
    performs on the data. It is not. Reinstating a claim is **new evidence,
    backed by somebody, that the thing exists** — and two people must be able to
    disagree about that, exactly as they disagree about a category.

    That is the same mistake :attr:`Link.Kind.CLASSIFIES` was introduced to
    undo: classification used to be a column written once and never updated, so
    there was one classification per node forever and a category had no set of
    claims it could be *defined* over. Existence had that shape until now.

    ``stands=True`` is an attestation — the first one and any later
    re-attestation alike. ``stands=False`` is a retraction. There is no
    "reinstate" operation and no state machine; there is only more evidence, and
    the current answer is a fold over it (:mod:`evidence.claims`).

    Because it is a fold over *claims*, it can be scoped the way every other read
    is: a graph whose selector counts only Johannes's assertions gets Johannes's
    answer about what exists, and the graph next door can disagree without a row
    being rewritten.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="standings",
    )
    target_type = models.CharField(
        max_length=32,
        help_text="Which table the claim this is about lives in: 'structure', 'metric', 'link', 'comment' or 'node'.",
    )
    target_id = models.CharField(
        max_length=1000,
        help_text="Opaque uuid of the target row. A CharField rather than a UUIDField because the column addresses four different tables; see the note on Link about keeping refs opaque.",
    )
    stands = models.BooleanField(
        help_text="Whether the claimant says this stands. True attests, False retracts. Deliberately not nullable: a claim with no position is not a claim.",
    )
    at = models.DateTimeField(help_text="When the claim took effect. World time, the axis a scientist means.")
    confidence = _confidence_field()
    recorded_at = models.DateTimeField(
        auto_now_add=True,
        help_text=(
            "When we durably stored the claim. Debugging only. It used to break ties between claims sharing an `at`, "
            "and conceded in its own help_text that it was a tiebreak rather than a total order — two claims written "
            "in one request share it to the microsecond often enough that the fold could pick either. "
            "`Assertion.seq` is the tiebreak now."
        ),
    )
    assertion = models.ForeignKey(
        Assertion,
        on_delete=models.PROTECT,
        related_name="standings",
    )

    objects = OrganizationScopedManager()
    all_objects = models.Manager()

    class Meta:
        base_manager_name = "all_objects"
        default_manager_name = "all_objects"
        indexes = [
            # The fold's access path: every claim about one target, newest first.
            # `-at` then the assertion, which the fold joins to for `seq` — see
            # `evidence.claims._LATEST`.
            models.Index(fields=["organization", "target_type", "target_id", "-at", "-assertion"]),
        ]
        constraints = [_confidence_constraint("standing")]

    def __str__(self) -> str:
        return f"{self.target_type}:{self.target_id} {'stands' if self.stands else 'retracted'}"


class CurrentStanding(models.Model):
    """The folded answer to "does this stand", kept as a projection.

    **This is a cache, and it is the reason the log tables are immutable.**

    `Structure`, `Metric` and `Link` each used to carry a `stands` boolean that
    :func:`evidence.writer.record_standing` wrote in the same transaction as the claim. That
    made the log tables mutable — the module docstring in `writer` said "there is
    no update and no delete" while issuing an `UPDATE` four lines down — and it is
    what stopped `REVOKE UPDATE` from being possible. The answer had to live
    somewhere indexed, because `metrics_for`, `informs_links_for` and
    `active_metrics_for_structures` all narrow the highest-churn table in the
    system by it and folding `Standing` per row on those paths is a real regression.
    So it lives here instead: same index, same query cost, and nothing writes to
    the log to maintain it.

    **One row per claimed target, holding the claim that won**, rather than a
    sparse set of retractions. The winning claim is what makes the projection
    explainable — "this metric does not count because of *that* retraction, by
    *that* subject" — and it is what lets a test assert the cache agrees with the
    fold rather than merely that it is self-consistent.

    A target nobody has claimed anything about has no row, and stands: absence is
    not dissent, which is the same rule :func:`evidence.claims.stands_for` applies.

    **Nodes are deliberately absent.** Whether a node stands is a per-view
    question — a node's category clauses decide whose claims it counts (RFC
    0009), so two views may legitimately disagree — and one organization-wide
    answer would be wrong for at least one of them. `projector.resolve_categories`
    folds `Standing` under the resolved category's `trust_filter` for exactly
    that reason, and must keep doing so. The three kinds here are organization-grain: a retracted metric is
    retracted everywhere.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="current_standings",
    )
    target_type = models.CharField(
        max_length=32,
        help_text="Which table the target lives in: 'structure', 'metric' or 'link'. Never 'instance' — see the class docstring.",
    )
    target_id = models.UUIDField(
        help_text="The target row's primary key. A `UUIDField` where `Standing.target_id` is a `CharField`, because this column exists to be joined against those tables' primary keys and a text-to-uuid comparison would either fail or force a cast into every query that narrows by standing.",
    )
    stands = models.BooleanField(
        help_text="The folded answer. Derived from `Standing` and never authoritative — rebuild it and it must not change.",
    )
    standing = models.ForeignKey(
        Standing,
        on_delete=models.CASCADE,
        related_name="+",
        help_text="The standing this answer was folded from — the claim that won. CASCADE because this row is a projection of that one: if it goes, so does the answer derived from it.",
    )

    objects = OrganizationScopedManager()
    all_objects = models.Manager()

    class Meta:
        base_manager_name = "all_objects"
        default_manager_name = "all_objects"
        constraints = [
            models.UniqueConstraint(fields=["organization", "target_type", "target_id"], name="one_current_answer_per_target"),
        ]
        indexes = [
            # The access path every "does this stand" narrowing takes: the
            # retracted subset of one target type, which is the small side.
            models.Index(fields=["organization", "target_type", "stands"]),
            # The same subset, without the organization — because
            # :func:`evidence.claims.standing` does not have one. It takes a
            # queryset and a target type, so its anti-join filters on
            # `(target_type, stands)` and could not use the index above at all:
            # `organization` is its leading column, and skipping a leading column
            # means a scan. Adding the tenant to `standing()`'s signature would
            # mean threading it through twenty-seven call sites on every hot read
            # path; an index matching the query that is actually issued is the
            # smaller and more honest fix. `target_id` rides along so the
            # subquery is answered from the index without touching the heap.
            models.Index(fields=["target_type", "stands", "target_id"], name="currentstanding_retracted_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.target_type}:{self.target_id} {'stands' if self.stands else 'retracted'}"


class State(models.Model):
    """Sufficient statistics for one derived property, kept incrementally.

    This is the table that makes schema iteration stop implying a backfill.

    Every member of ``AggregationFunction`` — MEAN, SUM, MAX, MIN, COUNT, RANGE,
    EUCLIDEAN_RANGE, LATEST — is a monoid over the columns below, so each is O(1)
    to maintain as a metric arrives and O(1) to read. Crucially, none of them is
    *stored*: the row holds statistics, not an answer. Switching a property from
    MEAN to MAX therefore changes what the next read returns without writing
    anything at all, which is the whole claim being made here.

    **Grain: `(claim_ref, source_kind, key, value_kind)` over metrics. Nothing
    else.**

    ``value_kind`` is in the grain because it is in :class:`MetricKind`'s
    identity, and leaving it out would have quietly undone that. Two terms for
    one key would fold into one row; a string bumps ``n`` but contributes nothing
    to ``sum`` (see :func:`evidence.state._numeric`), so `MEAN` over 40, 60 and
    `"big"` would read 33.3. Worse, :func:`evidence.state.recompute` filtered the
    same way, so the incremental fold and its own correctness backstop would have
    agreed on the wrong answer — and `test_state_vector`'s property test would
    have certified it.

    A rule may only aggregate measurements reaching an entity through the
    documented ``(Metric)-[DESCRIBES]->(Structure)-[INFORMS]->(Entity)`` path.
    Aggregating over *related entities or events* — "count this cell's mitosis
    events" — is deliberately **not** expressible, because it is not a fold over
    measured values at all: it is a graph cardinality question with no sum, no
    min and no max, and it would have to be maintained on entity creation rather
    than on metric arrival. `graph_engine.aggregate.validate_rule` rejects such
    rules when the schema is validated, so their author is told, instead of the
    property silently never computing.

    ``claim_ref`` is an opaque bare uuid — a :class:`Instance`, or a ``Link`` when
    the statistic describes an edge. It used to carry the projection implicitly,
    as a ``{age_name}:{uuid}`` composite, so two views over the same evidence
    maintained two rows differing only in that prefix. They no longer do: a
    statistic folded from the organization's metrics is the same statistic
    whichever view reads it, so **there is one row per entity, organization-wide**.
    Which of those metrics a given graph counts is a read-time question its
    selector answers (`projector._scoped_state`), not a reason to keep two copies.

    That is also why the two kinds of ref need no discriminator column. Nothing
    folds under a selector any more, so nodes and edges are folded by identical
    code and read by callers that already know which they asked for — a column
    saying which is which would have no consumer, and an unread column is the
    shape of every cache that has drifted here before.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="states",
    )
    claim_ref = models.CharField(
        max_length=1000,
        help_text="Opaque uuid of the node or edge this statistic describes. Do not parse.",
    )
    source_kind = models.ForeignKey(
        StructureKind,
        on_delete=models.CASCADE,
        related_name="states",
        help_text="The kind of structure the measurements came through.",
    )
    key = models.CharField(max_length=1000, help_text="The measurement key being folded.")
    value_kind = models.CharField(
        max_length=32,
        choices=[(k.value, k.value) for k in ValueKind],
        help_text="The value kind of the metrics folded here. Part of the grain: a key with a FLOAT term and a STRING term maintains two rows, so neither aggregation is polluted by the other's values.",
    )

    # --- The monoid ---
    n = models.PositiveIntegerField(default=0, help_text="Count of contributing metrics. COUNT reads this.")
    sum = models.FloatField(
        null=True,
        blank=True,
        help_text="Running sum of numeric values. MEAN is sum/n; SUM reads it directly.",
    )
    min = models.FloatField(null=True, blank=True)
    max = models.FloatField(null=True, blank=True)

    first_ts = models.DateTimeField(null=True, blank=True, help_text="observed_at of the earliest contributing metric.")
    last_ts = models.DateTimeField(null=True, blank=True, help_text="observed_at of the latest contributing metric.")
    first_value = models.JSONField(
        null=True,
        blank=True,
        help_text="Value at first_ts. JSON rather than typed because LATEST is defined over strings and vectors too, and EUCLIDEAN_RANGE reads this as a point — which is why there is no separate first_pt column duplicating it.",
    )
    last_value = models.JSONField(null=True, blank=True, help_text="Value at last_ts. LATEST reads this.")

    high_water_assertion = models.ForeignKey(
        Assertion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="high_water_states",
        help_text="The latest assertion folded in. Lets a retraction arriving mid-backfill be ordered against what has already been counted.",
    )
    needs_recompute = models.BooleanField(
        default=False,
        help_text="Set when a retraction invalidated an order-dependent statistic (MIN/MAX/LATEST and friends cannot be un-merged). Read as: this row is stale until `recompute` runs.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    objects = OrganizationScopedManager()
    all_objects = models.Manager()

    class Meta:
        base_manager_name = "all_objects"
        default_manager_name = "all_objects"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "claim_ref", "source_kind", "key", "value_kind"],
                name="unique_state_per_claim_source_kind_key_value_kind",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "claim_ref"]),
            models.Index(fields=["organization", "needs_recompute"]),
        ]

    def __str__(self) -> str:
        return f"{self.claim_ref}/{self.key}: {self.value_kind} (n={self.n})"


class Instance(models.Model):
    """An individual this organization claimed into existence — an entity or an event.

    **Named for what it is, not for where it is drawn.** This was ``Node``, which
    made the word mean three things: this row, the GraphQL ``Node`` interface (wider
    — a :class:`Structure` and a :class:`Metric` implement it and neither is ever
    drawn), and an Apache AGE vertex. ``Instance`` is the word the rest of the
    documentation already used for it — "every observation mints its own instance" —
    and it leaves ``Node`` to mean the one thing it should: something a *graph* has.

    Entities and events are not derivable from measurements — somebody claimed
    "there is a cell here", and that claim is evidence like any other. Without a
    row for it, an entity carrying no metrics yet would vanish on rebuild, and
    ``reproject`` could not honestly claim to reconstruct the projection.

    **``id`` is the identity, and it is a bare uuid.** There is no separate
    ``ref`` column and no ``{age_name}:`` prefix on it any more. Two things were
    wrong with the prefix. It made identity a property of a projection, when a
    graph is only a view reconstructed from this table — so the same node could
    not be seen by two views. And it asserted a one-to-one correspondence
    between a node and an Apache AGE vertex, which is false: a vertex may be the
    merge of several nodes. Which graphs a node appears in is answered by their
    derivation rules, never by a substring of its name.

    Note also what the identity is *not*: the AGE vertex id. Vertex ids are
    assigned by AGE and reassigned when a graph is dropped and replayed, so
    keying anything on one would leave it dangling after exactly the operation
    this table exists to support.
    """

    class Kind(models.TextChoices):
        ENTITY = "entity", "Entity"
        NATURAL_EVENT = "natural_event", "Natural event"
        PROTOCOL_EVENT = "protocol_event", "Protocol event"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="instances",
    )
    kind = models.CharField(max_length=32, choices=Kind.choices)
    term = models.ForeignKey(
        Term,
        on_delete=models.PROTECT,
        related_name="instances",
        help_text="The organization's word this instance was first claimed under. Which view shows it, and as what, is decided from the claims — see `projector.resolve_categories`.",
    )
    assertion = models.ForeignKey(
        Assertion,
        on_delete=models.PROTECT,
        related_name="instances",
        help_text="The assertion that first claimed this instance exists.",
    )
    observed_at = models.DateTimeField(
        db_index=True,
        help_text=(
            "When the world contained this individual — for an event, when it happened; for an entity, "
            "when it was seen. A point, not an interval: a duration is a metric. Defaults to the assertion's "
            "`asserted_at` on save (RFC 0015)."
        ),
    )
    confidence = _confidence_field()
    # Deliberately **no cached `stands` column**, unlike Structure/Metric/Link.
    #
    # Those three are organization-grain: a retracted metric is retracted
    # everywhere, so one boolean is a correct denormalization. Whether a *node*
    # stands can differ per view, because a graph's selector decides whose claims
    # count — so a single cached answer would be wrong in the same way the
    # `{age_name}:` prefix on the ref was wrong. Existence is folded at
    # projection time, against the reading graph's selector.
    #
    # There was such a column. `rebuild` filtered on it and nothing ever wrote
    # it, so the filter was a no-op and the two paths agreed only by accident.
    created_at = models.DateTimeField(auto_now_add=True)

    objects = OrganizationScopedManager()
    all_objects = models.Manager()

    class Meta:
        base_manager_name = "all_objects"
        default_manager_name = "all_objects"
        # No `(organization, ref)` uniqueness any more: the primary key *is* the
        # ref, so the database already enforces it.
        indexes = [
            models.Index(fields=["organization", "kind"]),
            models.Index(fields=["organization", "term"]),
        ]
        constraints = [_confidence_constraint("instance")]

    def save(self, *args: Any, **kwargs: Any) -> None:
        _default_observed_at(self)
        super().save(*args, **kwargs)

    @property
    def ref(self) -> str:
        """This node's identity as evidence refers to it — its uuid, as a string.

        `Link.source_ref`, `State.claim_ref` and the lifecycle log all hold
        opaque strings, so the one place that converts is here rather than at
        every call site.
        """
        return str(self.pk)

    def __str__(self) -> str:
        return f"{self.kind}:{self.pk}"


class InstanceIdentity(models.Model):
    """Which nodes are one thing — the fold over :attr:`Link.Kind.SAME_AS`.

    Every observation mints its own instance, so "this is AIS 6" writes a *fresh*
    node and then claims it is the same as one already known. That keeps an
    observation from having to know about a prior one, but it means the answer to
    "what is known about this thing" is spread across a component of nodes rather
    than sitting on one. Walking the sameness claims per read would be a traversal
    on the hot path; this is the persisted union-find that replaces it, so
    "everything in this component" is ``WHERE canonical = c`` — a single seek.

    **Organization grain, like `State` and for the same reason.** The fold counts
    every standing claim; a view whose selector refuses one applies that on read.
    `CLAUDE.md` records what happens otherwise: `merge`, `recompute` and
    `refold_state` once disagreed about which metrics counted, so ingest and
    replay produced different numbers from the same evidence.

    **Only instances that are actually merged have a row.** One nobody has merged
    is a component of one, and materializing that would make this table as large
    as `Instance` for no information. `identity.canonical_for` returns the instance
    itself when there is no row.

    **The representative is the lowest uuid in the component**, not the
    first-asserted one. Identity must not be an accident of arrival order, and a
    deterministic rule is what lets a replay land on the same canonical as the
    original write — the same reason `projector.graphs_for_refs` orders by pk.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="instance_identities",
    )
    instance = models.OneToOneField(
        "Instance",
        on_delete=models.CASCADE,
        related_name="identity",
        help_text="An instance belonging to a component of two or more.",
    )
    canonical = models.ForeignKey(
        "Instance",
        on_delete=models.CASCADE,
        related_name="identity_members",
        help_text="The component's representative — the lowest uuid among its members, itself included.",
    )
    needs_recompute = models.BooleanField(
        default=False,
        help_text=("Set when a retraction may have split this component. Union is O(α) and incremental; un-union is not expressible incrementally, so the affected component is rebuilt from its surviving claims instead. Same escape hatch as `State.needs_recompute`."),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = OrganizationScopedManager()
    all_objects = models.Manager()

    class Meta:
        base_manager_name = "all_objects"
        default_manager_name = "all_objects"
        indexes = [
            # The read: every member of a component, in one seek.
            models.Index(fields=["organization", "canonical"]),
            models.Index(fields=["organization", "needs_recompute"]),
        ]

    def __str__(self) -> str:
        return f"{self.node_id} ~ {self.canonical_id}"
