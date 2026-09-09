"""Which term a derivation rule reads, when a key has more than one.

Once `value_kind` is part of a measurement term's identity, a key can carry
several terms — and a rule has to say which it means. `prop.value_kind` cannot
answer that: it is the aggregation's *result* type, so `AGGREGATION_RESULT_TYPES`
maps COUNT to INT over STRING sources and EUCLIDEAN_RANGE to FLOAT over 3D-vector
sources. Reading the source row by it would pick the wrong row precisely where it
differs from the source.

So `DerivationRule.source_value_kind` exists, and resolution mirrors the write
side: declared is exact, silence is resolved from the vocabulary, and genuine
ambiguity is reported rather than guessed.

The one widening is INT with FLOAT. They are distinct declarations — a cell count
and a length — but the same quantity to every aggregation, both in `value_num`
and both accepted by `state._numeric`. A rule naming FLOAT that read only the
FLOAT term would silently drop half its evidence, which is the under-derivation
this whole grain exists to prevent.
"""

import logging

import pytest
from authentikate.models import Organization

from core import models as core_models
from core.enums import ValueKind
from evidence import models as evidence_models
from evidence import state as state_module
from evidence import writer
from graph_engine import projector


def _property(source_value_kind: str | None = None, aggregation: str = "MEAN") -> dict:
    rule: dict = {"source_node": "@mikro/roi", "key": "confidence", "aggregation": aggregation}
    if source_value_kind is not None:
        rule["source_value_kind"] = source_value_kind
    return {"key": "score", "value_kind": "FLOAT", "derivation": "ROLLUP", "rule": rule}


def _category(graph: core_models.Graph, source_value_kind: str | None = None) -> core_models.EntityCategory:
    return core_models.EntityCategory.objects.create(
        graph=graph,
        key=f"Scored{source_value_kind or 'Any'}",
        age_name=f"scored{(source_value_kind or 'any').lower()}",
        property_definitions=[_property(source_value_kind)],
    )


@pytest.fixture
def measured(
    organization: Organization,
    graph_a: core_models.Graph,
    roi_kind: evidence_models.StructureKind,
    assertion: evidence_models.Assertion,
) -> str:
    """An ROI informing one entity, with nothing measured yet."""
    structure = writer.ensure_structure(organization, roi_kind, "roi-family", assertion)
    ref = f"{graph_a.age_name}:22222222-0000-0000-0000-000000000001"
    writer.create_link(
        organization,
        kind=evidence_models.Link.Kind.INFORMS,
        source_ref=str(structure.pk),
        target_ref=ref,
        assertion=assertion,
    )
    return ref


def _record(organization: Organization, roi_kind: evidence_models.StructureKind, assertion: evidence_models.Assertion, ref: str, value: object, value_kind: ValueKind) -> None:
    structure = evidence_models.Structure.objects.for_organization(organization).get(object="roi-family")
    term = writer.ensure_metric_kind(organization, roi_kind, "confidence", value_kind)
    metric = writer.record_metric(organization, structure, term, key="confidence", value=value, assertion=assertion)
    state_module.merge(metric, [ref])


@pytest.mark.django_db(transaction=True)
def test_a_rule_naming_float_still_sees_int_measurements(
    organization: Organization,
    graph_a: core_models.Graph,
    roi_kind: evidence_models.StructureKind,
    assertion: evidence_models.Assertion,
    measured: str,
) -> None:
    """MEAN of 40.0 (FLOAT) and 60 (INT) is 50, not 40.

    The failure this widening prevents: two legitimate declarations of one
    quantity, and a rule that saw only one of them.
    """
    _record(organization, roi_kind, assertion, measured, 40.0, ValueKind.FLOAT)
    _record(organization, roi_kind, assertion, measured, 60, ValueKind.INT)

    category = _category(graph_a, source_value_kind="FLOAT")
    derived = projector.derive_properties(graph_a, measured, category)

    assert derived["score"] == pytest.approx(50.0), "Both numeric terms contribute"


@pytest.mark.django_db(transaction=True)
def test_an_undeclared_rule_resolves_a_single_family(
    organization: Organization,
    graph_a: core_models.Graph,
    roi_kind: evidence_models.StructureKind,
    assertion: evidence_models.Assertion,
    measured: str,
) -> None:
    """Silence is fine when the key is unambiguous — INT and FLOAT are one family.

    Requiring `source_value_kind` on every rule would make the common case pay
    for the rare one.
    """
    _record(organization, roi_kind, assertion, measured, 40.0, ValueKind.FLOAT)
    _record(organization, roi_kind, assertion, measured, 60, ValueKind.INT)

    category = _category(graph_a)
    derived = projector.derive_properties(graph_a, measured, category)

    assert derived["score"] == pytest.approx(50.0)


@pytest.mark.django_db(transaction=True)
def test_a_declared_rule_reads_only_its_own_family(
    organization: Organization,
    graph_a: core_models.Graph,
    roi_kind: evidence_models.StructureKind,
    assertion: evidence_models.Assertion,
    measured: str,
) -> None:
    """A STRING measurement under the same key does not reach a FLOAT rule."""
    _record(organization, roi_kind, assertion, measured, 40.0, ValueKind.FLOAT)
    _record(organization, roi_kind, assertion, measured, 60.0, ValueKind.FLOAT)
    _record(organization, roi_kind, assertion, measured, "high", ValueKind.STRING)

    category = _category(graph_a, source_value_kind="FLOAT")
    derived = projector.derive_properties(graph_a, measured, category)

    assert derived["score"] == pytest.approx(50.0), "MEAN of 40 and 60, with the label excluded"


@pytest.mark.django_db(transaction=True)
def test_an_ambiguous_key_warns_and_does_not_derive(
    organization: Organization,
    graph_a: core_models.Graph,
    roi_kind: evidence_models.StructureKind,
    assertion: evidence_models.Assertion,
    measured: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Two families, no declaration: say so, and derive nothing.

    Skipping silently is the failure mode this codebase keeps removing — a
    property that never computes and never explains why. Picking a term
    arbitrarily would be worse still, because the answer would depend on which
    write happened to run first.
    """
    _record(organization, roi_kind, assertion, measured, 40.0, ValueKind.FLOAT)
    _record(organization, roi_kind, assertion, measured, "high", ValueKind.STRING)

    category = _category(graph_a)
    with caplog.at_level(logging.WARNING, logger="graph_engine.projector"):
        derived = projector.derive_properties(graph_a, measured, category)

    assert "score" not in derived, "An ambiguous rule must not guess"

    messages = [record.getMessage() for record in caplog.records]
    ambiguity = [message for message in messages if "source_value_kind" in message]
    assert ambiguity, f"The warning must say how to fix it; got {messages}"
    assert "FLOAT" in ambiguity[0] and "STRING" in ambiguity[0], "…and name the terms it could not choose between"
    assert "INT" not in ambiguity[0], "Only terms that exist — FLOAT widening to INT is not a term anybody declared"


@pytest.mark.django_db(transaction=True)
def test_a_key_with_no_evidence_derives_nothing_quietly(
    organization: Organization,
    graph_a: core_models.Graph,
    assertion: evidence_models.Assertion,
    measured: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Terms are minted lazily, so "no term yet" is the ordinary starting state.

    Warning here would make every freshly declared property noisy until the first
    measurement arrived.
    """
    category = _category(graph_a)
    with caplog.at_level(logging.WARNING, logger="graph_engine.projector"):
        derived = projector.derive_properties(graph_a, measured, category)

    # No value, spelled as `None`: the projector hands the writer every key so a
    # key whose evidence went away is cleared from the drawing (RFC 0023).
    assert derived.get("score") is None
    assert not [record for record in caplog.records if "source_value_kind" in str(record.msg)]
