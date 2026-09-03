"""Migration 0019 converts a flat `rule.evidence` list losslessly (RFC 0014)."""

from __future__ import annotations

import importlib

import pytest

from core import models as core_models
from evidence.selector import rule_metric_filter

migration = importlib.import_module("core.migrations.0019_property_evidence_is_a_rule_list")


def test_convert_evidence_wraps_a_list_in_one_rule():
    flat = [
        {"field": "APP", "operator": "IS", "value": "segmenter-v3"},
        {"field": "MEASURED_AT", "operator": "SINCE", "value": "2026-06-01T00:00:00Z"},
    ]
    assert migration.convert_evidence(flat) == {"rules": [{"when": flat}]}
    already = {"rules": [{"when": flat}]}
    assert migration.convert_evidence(already) is already
    assert migration.convert_evidence(None) is None


@pytest.mark.django_db(transaction=True)
def test_converted_evidence_parses_and_compiles(test_graph: core_models.Graph, table_projector):
    category = core_models.Category.objects.filter(graph=test_graph, kind="ENTITY").first()
    assert category is not None
    # Stored the way a pre-0014 write left it: the flat list.
    core_models.Category.objects.filter(pk=category.pk).update(
        property_definitions=[
            {
                "key": "avg_length",
                "value_kind": "FLOAT",
                "derivation": "ROLLUP",
                "rule": {
                    "source_node": "ROI",
                    "key": "vector_length",
                    "aggregation": "MEAN",
                    "evidence": [{"field": "APP", "operator": "IS", "value": "segmenter-v3"}],
                },
            }
        ]
    )
    category.refresh_from_db()

    with pytest.raises(Exception):
        category.defined_properties  # the flat list no longer parses

    migration.convert(_Apps(), None)
    category.refresh_from_db()

    (prop,) = category.defined_properties
    assert prop.rule is not None and prop.rule.evidence is not None
    assert prop.rule.evidence.to_stored() == {"rules": [{"when": [{"field": "APP", "operator": "IS", "value": "segmenter-v3"}]}]}
    assert "segmenter-v3" in str(rule_metric_filter(prop.rule))


class _Apps:
    """Enough of the migration `apps` registry for `convert`: the real model."""

    def get_model(self, app_label, model_name):
        assert (app_label, model_name) == ("core", "Category")
        return core_models.Category
