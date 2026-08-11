"""A schema change does not stop the world.

Expand-contract: create the new version, backfill under it, flip active, drop the
old at leisure. The property that makes it safe is that readers pinned to the
previous version keep getting correct answers while the backfill runs — the new
version is inactive, so nothing consults it until it is ready.

The version a node was derived under is stamped on it as `__schema_version`, so
"has this value been brought up to date?" is answerable per node rather than
being a global flag.
"""

import pytest

from core import models as core_models
from graph_engine import schema_diff, versioning


@pytest.mark.django_db(transaction=True)
def test_a_new_version_starts_inactive_until_activated(test_graph: core_models.Graph) -> None:
    """Expand: the new schema exists but nothing reads it yet.

    This is what lets a backfill run against `v_n+1` while `v_n` continues to
    serve reads.
    """
    active_before = core_models.GraphSchema.active_for(test_graph)

    pending = core_models.GraphSchema(
        graph=test_graph,
        version=active_before.version,
        index=None,
        definition=versioning.snapshot_definition(test_graph),
        is_active=False,
    )
    pending.save()

    assert core_models.GraphSchema.active_for(test_graph).pk == active_before.pk, "Creating a version must not activate it"

    pending.activate()

    assert core_models.GraphSchema.active_for(test_graph).pk == pending.pk
    active_before.refresh_from_db()
    assert not active_before.is_active, "Activating must deactivate the previous version"


@pytest.mark.django_db(transaction=True)
def test_history_is_preserved_so_a_diff_has_something_to_compare(test_graph: core_models.Graph) -> None:
    """Contract happens later, deliberately. The old version stays readable."""
    first = core_models.GraphSchema.active_for(test_graph)

    core_models.EntityCategory.objects.create(graph=test_graph, key="Terminal", age_name="terminal")
    second = core_models.GraphSchema.active_for(test_graph)

    assert second.pk != first.pk
    first.refresh_from_db()
    assert first.pk, "The superseded version is retained, not deleted"

    difference = schema_diff.diff_schemas(first, second)
    assert "Terminal" not in difference.categories_needing_reprojection or difference.work_set == []


@pytest.mark.django_db(transaction=True)
def test_an_aggregation_swap_needs_no_backfill(test_graph: core_models.Graph) -> None:
    """The case expand-contract exists to make cheap turns out to be free.

    Swapping MEAN for MAX produces a real new version — the schema genuinely
    changed — with an empty work set. No node needs re-deriving, so there is
    nothing to expand into and nothing to contract afterwards.
    """
    category = core_models.EntityCategory.objects.create(
        graph=test_graph,
        key="Terminal2",
        age_name="terminal2",
        property_definitions=[{"key": "size", "derivation": "ROLLUP", "rule": {"source_node": "ROI", "key": "area", "aggregation": "MEAN"}}],
    )
    before = core_models.GraphSchema.active_for(test_graph)

    category.property_definitions = [{"key": "size", "derivation": "ROLLUP", "rule": {"source_node": "ROI", "key": "area", "aggregation": "MAX"}}]
    category.save()

    after = core_models.GraphSchema.active_for(test_graph)
    assert after.pk != before.pk, "The schema did change and must be recorded"

    difference = schema_diff.diff_schemas(before, after)
    assert difference, "…and the change must be visible in the diff"
    assert difference.is_free, "…but it implies no work at all"
    assert difference.changes[0].kind == "aggregation_changed"


@pytest.mark.django_db(transaction=True)
def test_the_active_schema_hash_identifies_the_version(test_graph: core_models.Graph) -> None:
    """The hash is what projected nodes stamp, so it must actually distinguish versions."""
    first = core_models.GraphSchema.active_for(test_graph)
    assert first.hash, "Every schema must carry a content hash"

    core_models.EntityCategory.objects.create(graph=test_graph, key="Terminal3", age_name="terminal3")
    second = core_models.GraphSchema.active_for(test_graph)

    assert second.hash != first.hash, "A changed definition must hash differently"
