"""What a schema change costs, stated as a table.

The §3.1 rescan matrix, executable. The row that matters most is the first one:
**changing an aggregation produces an empty work set.** That is the claim the
sufficient-statistics state vector was built to support — the row holds
statistics rather than an answer, so MEAN and MAX read the same data and the
"migration" is nothing at all.

Needs no database.
"""

import pytest
from graph_engine import schema_diff
from core import models as core_models
from graph_engine import versioning


def _definition(properties: list[dict]) -> dict:
    return {"system_version": "1.0.0", "extensions": {"entities": [{"key": "AIS", "property_definitions": properties}]}}


def _rollup(key: str, source: str = "ROI", metric: str = "vector_length", aggregation: str = "MEAN") -> dict:
    return {"key": key, "derivation": "ROLLUP", "rule": {"source_node": source, "key": metric, "aggregation": aggregation}}


CASES = [
    pytest.param(
        _definition([_rollup("avg_length", aggregation="MEAN")]),
        _definition([_rollup("avg_length", aggregation="MAX")]),
        "aggregation_changed",
        False,
        id="aggregation-swap-is-free",
    ),
    pytest.param(
        _definition([_rollup("avg_length", metric="vector_length")]),
        _definition([_rollup("avg_length", metric="perimeter")]),
        "source_changed",
        True,
        id="different-metric-key-needs-work",
    ),
    pytest.param(
        _definition([_rollup("avg_length", source="ROI")]),
        _definition([_rollup("avg_length", source="Mask")]),
        "source_changed",
        True,
        id="different-source-needs-work",
    ),
    pytest.param(
        _definition([]),
        _definition([_rollup("avg_length")]),
        "added",
        True,
        id="added-property-needs-projection",
    ),
    pytest.param(
        _definition([_rollup("avg_length")]),
        _definition([]),
        "removed",
        True,
        id="removed-property-needs-clearing",
    ),
]


@pytest.mark.parametrize(("before", "after", "expected_kind", "expected_work"), CASES)
def test_change_classification(before: dict, after: dict, expected_kind: str, expected_work: bool) -> None:
    """Each kind of edit is classified, and only some of them imply work."""
    difference = schema_diff.diff(before, after)

    assert len(difference.changes) == 1
    change = difference.changes[0]
    assert change.kind == expected_kind
    assert change.needs_reprojection is expected_work
    assert bool(difference.work_set) is expected_work


def test_swapping_an_aggregation_produces_an_empty_work_set() -> None:
    """The headline row of the matrix, asserted on its own.

    If this ever starts reporting work, the state vector has stopped being
    sufficient statistics and has started storing answers.
    """
    difference = schema_diff.diff(
        _definition([_rollup("avg_length", aggregation="MEAN")]),
        _definition([_rollup("avg_length", aggregation="MAX")]),
    )

    assert difference, "The change is real and must be recorded"
    assert difference.work_set == [], "…but it costs nothing to apply"
    assert difference.is_free
    assert difference.categories_needing_reprojection == set()


def test_an_identical_definition_is_not_a_change() -> None:
    """No diff, no version, no work."""
    definition = _definition([_rollup("avg_length")])

    assert not schema_diff.diff(definition, definition)


def test_cosmetic_edits_cost_nothing() -> None:
    """Renaming a label does not touch a single derived value."""
    before = _definition([{**_rollup("avg_length"), "label": "Average"}])
    after = _definition([{**_rollup("avg_length"), "label": "Mean length"}])

    difference = schema_diff.diff(before, after)

    assert difference.changes[0].kind == "cosmetic"
    assert difference.is_free


def test_diff_covers_relations_and_events_too() -> None:
    """Properties are not only on entities, and a partial diff is a wrong diff."""
    before = {"system_version": "1.0.0", "extensions": {"relations": [{"key": "IS_CONNECTED_TO", "properties": [_rollup("distance")]}]}}
    after = {"system_version": "1.0.0", "extensions": {"relations": [{"key": "IS_CONNECTED_TO", "properties": []}]}}

    difference = schema_diff.diff(before, after)

    assert difference.categories_needing_reprojection == {"IS_CONNECTED_TO"}


def test_json_patch_is_available_for_humans() -> None:
    """The raw patch is fine for display, but must not be what decides work.

    A replaced `aggregation` and a replaced `source_node` are the same shape of
    patch operation and wildly different in cost, which is why the structured
    diff exists.
    """
    patch = schema_diff.json_patch(
        _definition([_rollup("avg_length", aggregation="MEAN")]),
        _definition([_rollup("avg_length", aggregation="MAX")]),
    )

    assert any(operation.get("op") == "replace" for operation in patch)


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
