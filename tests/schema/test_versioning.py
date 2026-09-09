"""Every ontology change records a version — and most of them cost nothing.

`GraphSchema` used to be written exactly once per graph, with `index=1` and
`is_active=True` hardcoded and `activate()` never called. Category mutations
edited rows in place. With one version and no history there was nothing to
compare, so every schema change looked like "recalculate everything" — which is
why the derivation layer appeared expensive in the first place.

Versioning is driven by a signal rather than by call sites, so the guarantee
holds for every path into a category: the eight mutation modules, the managers,
the admin, and anything written later.
"""

import pytest
from authentikate.models import Organization

from core import models as core_models
from graph_engine import schema_diff, versioning


@pytest.mark.django_db(transaction=True)
def test_materializing_a_graph_emits_exactly_one_schema(test_graph: core_models.Graph) -> None:
    """A schema expressed as dozens of categories is one version, not dozens.

    Without suspending the signal during materialization, the history would
    describe the order rows happened to be inserted rather than anything a user
    did.
    """
    schemas = core_models.GraphSchema.objects.filter(graph=test_graph)

    assert schemas.count() == 1
    assert schemas.get().is_active


@pytest.mark.django_db(transaction=True)
def test_creating_a_category_emits_a_version(test_graph: core_models.Graph) -> None:
    """The signal fires for a category created directly, with no mutation involved."""
    before = core_models.GraphSchema.objects.filter(graph=test_graph).count()

    core_models.EntityCategory.objects.create(graph=test_graph, key="Axon", age_name="axon")

    after = core_models.GraphSchema.objects.filter(graph=test_graph)
    assert after.count() == before + 1
    assert after.order_by("-index").first().is_active


@pytest.mark.django_db(transaction=True)
def test_a_change_that_changes_nothing_emits_nothing(test_graph: core_models.Graph) -> None:
    """Re-saving identical content must not create a version.

    The content hash decides, not the fact that a mutation ran — otherwise the
    history fills with indistinguishable entries and a diff between neighbours
    reports an empty change as a real one.
    """
    category = core_models.EntityCategory.objects.create(graph=test_graph, key="Dendrite", age_name="dendrite")
    count_after_create = core_models.GraphSchema.objects.filter(graph=test_graph).count()

    category.save()

    assert core_models.GraphSchema.objects.filter(graph=test_graph).count() == count_after_create


@pytest.mark.django_db(transaction=True)
def test_only_one_schema_is_ever_active(test_graph: core_models.Graph) -> None:
    """Enforced by the database, not by convention."""
    core_models.EntityCategory.objects.create(graph=test_graph, key="Synapse", age_name="synapse")

    active = core_models.GraphSchema.objects.filter(graph=test_graph, is_active=True)
    assert active.count() == 1


@pytest.mark.django_db(transaction=True)
def test_two_active_schemas_is_a_database_error(test_graph: core_models.Graph) -> None:
    """The constraint has to bite, or `activate()` is just a convention.

    Two concurrent activations would each see the other as inactive; a graph with
    two active schemas has no answer to "which version derived this value".
    """
    from django.db import IntegrityError, transaction as db_transaction

    active = core_models.GraphSchema.objects.get(graph=test_graph, is_active=True)

    with pytest.raises(IntegrityError), db_transaction.atomic():
        core_models.GraphSchema.objects.create(
            graph=test_graph,
            version=active.version,
            index=active.index + 1,
            definition={},
            is_active=True,
        )


@pytest.mark.django_db(transaction=True)
def test_the_index_increments(test_graph: core_models.Graph) -> None:
    """Versions are ordered, so a diff has a direction."""
    core_models.EntityCategory.objects.create(graph=test_graph, key="Bouton", age_name="bouton")
    core_models.EntityCategory.objects.create(graph=test_graph, key="Spine", age_name="spine")

    indices = list(core_models.GraphSchema.objects.filter(graph=test_graph).order_by("index").values_list("index", flat=True))
    assert indices == sorted(indices)
    assert len(set(indices)) == len(indices), "Indices must be unique per graph"


@pytest.mark.django_db(transaction=True)
def test_deleting_a_category_emits_a_version(test_graph: core_models.Graph) -> None:
    """Removal is a schema change too, and the diff has to see it."""
    category = core_models.EntityCategory.objects.create(graph=test_graph, key="Ephemeral", age_name="ephemeral")
    after_create = core_models.GraphSchema.objects.filter(graph=test_graph).count()

    category.delete()

    assert core_models.GraphSchema.objects.filter(graph=test_graph).count() == after_create + 1


@pytest.mark.django_db(transaction=True)
def test_snapshot_reflects_the_categories_not_the_previous_schema(test_graph: core_models.Graph) -> None:
    """The snapshot reads the rows the mutations edit.

    Deriving a new version from the *previous version* instead would make every
    edit invisible, which is precisely the failure the in-place category updates
    used to cause.
    """
    core_models.EntityCategory.objects.create(graph=test_graph, key="Nucleus", age_name="nucleus")

    snapshot = versioning.snapshot_definition(test_graph)
    keys = {entity["key"] for entity in snapshot["extensions"]["entities"]}

    assert "Nucleus" in keys


@pytest.mark.django_db(transaction=True)
def test_versions_are_diffable_and_addition_costs_work(test_graph: core_models.Graph) -> None:
    """Adding a derived property implies re-projecting that category."""
    before = core_models.GraphSchema.objects.get(graph=test_graph, is_active=True)

    core_models.EntityCategory.objects.create(
        graph=test_graph,
        key="Bouton2",
        age_name="bouton2",
        property_definitions=[
            {
                "key": "size",
                "derivation": "ROLLUP",
                "rule": {"source_node": "ROI", "key": "area", "aggregation": "MEAN"},
            }
        ],
    )
    after = core_models.GraphSchema.objects.filter(graph=test_graph, is_active=True).get()

    difference = schema_diff.diff_schemas(before, after)

    assert difference, "Adding a property must register as a change"
    assert "Bouton2" in difference.categories_needing_reprojection
    assert not difference.is_free


@pytest.mark.django_db(transaction=True)
def test_a_protocol_event_category_is_part_of_the_schema(test_graph: core_models.Graph) -> None:
    """Creating one emits a version, and the snapshot carries it with its kind.

    Protocol events were absent from `snapshot_definition` and from
    `materialize`, so a schema change nothing could see: no version, no
    `schemaStale`, and a graph re-materialized from its own snapshot lost them.
    """
    before = core_models.GraphSchema.objects.filter(graph=test_graph).count()

    core_models.ProtocolEventCategory.objects.create(graph=test_graph, key="Fixation", age_name="Fixation", label="Fixation")

    assert core_models.GraphSchema.objects.filter(graph=test_graph).count() == before + 1
    events = {event["key"]: event for event in versioning.snapshot_definition(test_graph)["extensions"]["events"]}
    assert events["Fixation"]["kind"] == "EXTRINSIC"
    assert events["Mitosis"]["kind"] == "INTRINSIC"


@pytest.mark.django_db(transaction=True)
def test_a_save_through_the_base_class_emits_a_version(test_graph: core_models.Graph) -> None:
    """The signal listens on every class a category can be saved through, not
    only the leaf proxies — the namespace refresh always did."""
    before = core_models.GraphSchema.objects.filter(graph=test_graph).count()

    row = core_models.Category.objects.get(graph=test_graph, key="AIS")
    row.description = "an axon initial segment"
    row.save()

    assert core_models.GraphSchema.objects.filter(graph=test_graph).count() == before + 1
