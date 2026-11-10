"""Insight results: a pairs query run into a stored training set, and the models trained on one.

kraph has three layers: the **log** records everything claimed, the **graph** draws what
a view's rules admit, and a **query** over the graph is an insight. A pairs query
(`core.GraphPairsQuery`) selects pairs from a view's drawing; the drawing has no "as of"
(RFC 0014), so the only way to say exactly which pairs a model learned from is to keep
the answer. A **run** is that kept answer: the pairs, the plan as it was, and the
drawing's position when it was read. Nothing here is a claim: a run writes no `Assertion`
and no `Standing`, and it is never edited, only deleted.
"""

from arkitekt_service.service.described import Described
from authentikate.models import Organization
from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.db import models


class PairsQueryRun(Described):
    """One run of a pairs query: the pairs it answered, stored with where the drawing stood."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="pairs_query_runs", help_text="The organization whose view was read")
    query = models.ForeignKey(
        "core.GraphQuery",
        on_delete=models.RESTRICT,
        related_name="runs",
        help_text="The pairs query that was run. A query with runs cannot be deleted until they are",
    )
    graph = models.ForeignKey("core.Graph", on_delete=models.CASCADE, related_name="pairs_query_runs", help_text="The view the query was run against")
    name = models.CharField(max_length=1000, help_text="What the run is called")
    description = models.TextField(null=True, blank=True, help_text="What the run is for")
    auto = models.BooleanField(default=False, help_text="Run by the server for a model registered against the query, not by somebody running it")
    as_of_seq = models.BigIntegerField(
        help_text="The drawing's position when it was read: everything the log committed at or below it was drawn. The lower of the view's projection cursor and the log's committed horizon",
    )
    plan = models.JSONField(help_text="The query's plan as it was run")
    schema_hash = models.CharField(max_length=1000, null=True, blank=True, help_text="The view's schema hash when it was run: which rules drew what was read")
    n_pairs = models.PositiveIntegerField(default=0, help_text="How many pairs it holds")
    source_identifier = models.CharField(max_length=1000, null=True, blank=True, help_text="The structure identifier every source shares; null when they differ")
    target_identifier = models.CharField(max_length=1000, null=True, blank=True, help_text="The structure identifier every target shares; null when they differ")
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="pairs_query_runs", help_text="Who ran it")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "created_at"]),
            # What a port's `requires` reads (kraph_server/service.py: `@kraph/pairsrun`).
            GinIndex(fields=["stored_descriptors"], name="pairs_run_desc_gin", opclasses=["jsonb_path_ops"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} (as of seq {self.as_of_seq})"


class PairsQueryRunEntry(models.Model):
    """One pair a run answered: a source datum and a target datum, in the drawing's order.

    The endpoints are copied as ``(identifier, object)``, the address a structure has
    outside kraph, so a client resolves them through the datum's own service. An endpoint
    that is a drawn instance rather than a structure travels as ``@kraph/entity``.
    """

    run = models.ForeignKey(PairsQueryRun, on_delete=models.CASCADE, related_name="entries")
    position = models.PositiveIntegerField(help_text="Its place in the run, 0 first")
    source_identifier = models.CharField(max_length=1000, help_text="The source datum's structure identifier, e.g. @mikro/arraylens")
    source_object = models.CharField(max_length=1000, help_text="The source datum's id within its structure")
    target_identifier = models.CharField(max_length=1000, help_text="The target datum's structure identifier")
    target_object = models.CharField(max_length=1000, help_text="The target datum's id within its structure")

    class Meta:
        ordering = ["position"]
        constraints = [models.UniqueConstraint(fields=["run", "position"], name="pairs_run_entry_position_unique")]

    def __str__(self) -> str:
        return f"{self.source_identifier}:{self.source_object} -> {self.target_identifier}:{self.target_object}"


class TrainedModel(Described):
    """A trained model: its weights, and the pairs query run it learned from.

    The weights are a big file in kraph's datalayer, uploaded the way every service's
    files are (request, write, finish), and named by the store the upload finished. The
    store FK cascades store -> data, as every datalayer reference does. What it was
    trained on is a run (made for it when the trainer named only the query), cited and
    restricted: deleting the run directly is refused, because the model's provenance
    would point at nothing, while an organization's deletion takes both.
    """

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="trained_models", help_text="The organization the model belongs to")
    name = models.CharField(max_length=1000, help_text="What the model is called")
    description = models.TextField(null=True, blank=True, help_text="What the model does")
    framework = models.CharField(max_length=1000, help_text="What the weights are for, e.g. 'care' or 'cellpose': what an action needs to load them")
    trained_on = models.ForeignKey(
        PairsQueryRun,
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="trained_models",
        help_text="The pairs query run it was trained on. Null for weights that came from elsewhere (a published pretrained model)",
    )
    store = models.ForeignKey(
        "datalayer.BigFileStore",
        on_delete=models.CASCADE,
        related_name="trained_models",
        help_text="The big file holding the weights",
    )
    parameters = models.JSONField(null=True, blank=True, help_text="How it was trained (epochs, learning rate, ...), as the trainer reported it")
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="trained_models", help_text="Who registered it")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "created_at"]),
            # What a port's `requires` reads (kraph_server/service.py: `@kraph/model`).
            GinIndex(fields=["stored_descriptors"], name="trained_model_desc_gin", opclasses=["jsonb_path_ops"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.framework})"
