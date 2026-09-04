"""Migration 0020 renames the stored rule field `MEASURED_AT` to `OBSERVED_AT` (RFC 0015).

Without it the old spelling would not fail: `selector._condition_q` returns no
predicate for a field it does not know, so the condition would be silently
dropped and a property that folded only last summer's measurements would fold
all of them.
"""

from __future__ import annotations

import importlib

import pytest

from core import models as core_models
from evidence.selector import rule_metric_filter, trust_filter

migration = importlib.import_module("core.migrations.0020_every_claim_has_a_time_of_observation")


def test_rename_field_walks_when_and_unless():
    stored = {
        "rules": [
            {
                "when": [
                    {"field": "APP", "operator": "IS", "value": "segmenter-v3"},
                    {"field": "MEASURED_AT", "operator": "SINCE", "value": "2026-06-01T00:00:00Z"},
                ],
                "unless": [{"when": [{"field": "MEASURED_AT", "operator": "BEFORE", "value": "2026-01-01T00:00:00Z"}]}],
            }
        ]
    }
    assert migration.rename_field(stored) is True
    assert stored["rules"][0]["when"][1]["field"] == "OBSERVED_AT"
    assert stored["rules"][0]["unless"][0]["when"][0]["field"] == "OBSERVED_AT"
    assert stored["rules"][0]["when"][0]["field"] == "APP", "other fields untouched"

    assert migration.rename_field(stored) is False, "idempotent"
    assert migration.rename_field(None) is False
    assert migration.rename_field({"rules": "not-a-list"}) is False


@pytest.mark.django_db(transaction=True)
def test_renamed_definitions_compile_to_a_time_predicate(test_graph: core_models.Graph, table_projector):
    category = core_models.Category.objects.filter(graph=test_graph, kind="ENTITY").first()
    assert category is not None
    # Stored the way a pre-0015 write left it: MEASURED_AT in a measurement-only
    # definition rule and in a property's evidence.
    core_models.Category.objects.filter(pk=category.pk).update(
        definition={
            "rules": [
                {"when": [{"field": "WORD", "operator": "IS", "value": category.key}, {"field": "KIND", "operator": "NOT_IN", "value": ["MEASUREMENT"]}]},
                {"when": [{"field": "KIND", "operator": "IS", "value": "MEASUREMENT"}, {"field": "MEASURED_AT", "operator": "SINCE", "value": "2026-06-01T00:00:00Z"}]},
            ]
        },
        property_definitions=[
            {
                "key": "avg_length",
                "value_kind": "FLOAT",
                "derivation": "ROLLUP",
                "rule": {
                    "source_node": "ROI",
                    "key": "vector_length",
                    "aggregation": "MEAN",
                    "evidence": {"rules": [{"when": [{"field": "MEASURED_AT", "operator": "SINCE", "value": "2026-06-01T00:00:00Z"}]}]},
                },
            }
        ],
    )
    category.refresh_from_db()

    stale_claim = trust_filter(category.definition, kind="MEASUREMENT", asserted_at_column="asserted_at", include_metric_fields=True)
    assert "observed_at" not in str(stale_claim), "the unknown field compiles to nothing — the silent drop the migration exists for"

    migration.rename(_Apps(), None)
    category.refresh_from_db()

    assert category.definition["rules"][1]["when"][1]["field"] == "OBSERVED_AT"
    claim = trust_filter(category.definition, kind="MEASUREMENT", asserted_at_column="asserted_at", include_metric_fields=True)
    assert "observed_at__gte" in str(claim)

    (prop,) = category.defined_properties
    assert prop.rule is not None and prop.rule.evidence is not None
    assert "observed_at__gte" in str(rule_metric_filter(prop.rule))


class _Apps:
    """Enough of the migration `apps` registry for `rename`: the real model."""

    def get_model(self, app_label, model_name):
        assert (app_label, model_name) == ("core", "Category")
        return core_models.Category
