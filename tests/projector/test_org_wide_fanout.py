"""One measurement reaches every projection that reads it.

The behaviour change this whole piece of work is for, and a bug fix rather than a
feature. `informs_links_for` filters links by a single graph's `{age_name}:`
prefix, so `dirty()` only ever named entities in the graph the caller passed —
and every write path passed exactly one. A second projection over the same
shared evidence therefore went stale the moment somebody recorded a metric
through the first, and stayed stale until a manual `reproject`.

That directly contradicts the point of sharing evidence across projections. If
these tests fail, ingest is graph-less in signature only.
"""

import pytest
from authentikate.models import Organization

from core import models as core_models
from evidence import models as evidence_models
from evidence import writer
from graph_engine import projector

REF_A = "{graph}:aaaaaaaa-0000-0000-0000-00000000000a"
REF_B = "{graph}:bbbbbbbb-0000-0000-0000-00000000000b"


@pytest.fixture
def shared_across_two_graphs(
    organization: Organization,
    graph_a: core_models.Graph,
    graph_b: core_models.Graph,
    roi_kind: evidence_models.StructureKind,
    assertion: evidence_models.Assertion,
) -> tuple[evidence_models.Structure, str, str]:
    """One structure, informing an entity in each of two graphs."""
    structure = writer.ensure_structure(organization, roi_kind, "roi-shared-fanout", assertion)

    ref_a = REF_A.format(graph=graph_a.age_name)
    ref_b = REF_B.format(graph=graph_b.age_name)

    for ref in (ref_a, ref_b):
        writer.create_link(
            organization,
            kind=evidence_models.Link.Kind.INFORMS,
            source_ref=str(structure.pk),
            target_ref=ref,
            assertion=assertion,
        )

    return structure, ref_a, ref_b


def test_the_fan_out_reaches_both_graphs(
    organization: Organization,
    graph_a: core_models.Graph,
    graph_b: core_models.Graph,
    shared_across_two_graphs: tuple[evidence_models.Structure, str, str],
) -> None:
    """Both projections appear, grouped by the graph they belong to.

    The old `dirty(graph, ...)` would have returned only one of these, depending
    on which graph the caller happened to name.
    """
    structure, ref_a, ref_b = shared_across_two_graphs

    fan_out = projector.dirty_across_organization(organization, [structure.pk])

    assert set(fan_out) == {graph_a.age_name, graph_b.age_name}
    assert fan_out[graph_a.age_name] == [ref_a]
    assert fan_out[graph_b.age_name] == [ref_b]


def test_the_old_single_graph_view_is_a_strict_subset(
    organization: Organization,
    graph_a: core_models.Graph,
    shared_across_two_graphs: tuple[evidence_models.Structure, str, str],
) -> None:
    """Stated as a comparison, so the regression is visible rather than implied.

    `dirty()` still exists and is still correct for "what does *this* graph need
    re-derived". It was simply the wrong question to ask on a write.
    """
    structure, ref_a, ref_b = shared_across_two_graphs

    single = projector.dirty(graph_a, [structure.pk])
    everything = [ref for refs in projector.dirty_across_organization(organization, [structure.pk]).values() for ref in refs]

    assert single == [ref_a]
    assert set(everything) == {ref_a, ref_b}
    assert ref_b not in single, "This is exactly the entity that used to go stale"


def test_recording_a_metric_folds_state_for_both_graphs(
    organization: Organization,
    shared_across_two_graphs: tuple[evidence_models.Structure, str, str],
    length_category: evidence_models.MetricKind,
    assertion: evidence_models.Assertion,
) -> None:
    """A single write updates the statistics behind both projections.

    State vectors are keyed on `entity_ref`, which carries the graph, so one
    metric legitimately produces two rows — one per projection. Producing only
    one is the stale-second-graph bug.
    """
    from evidence import state as state_module

    structure, ref_a, ref_b = shared_across_two_graphs

    metric = writer.record_metric(
        organization,
        structure,
        length_category,
        key="vector_length",
        value=42.0,
        assertion=assertion,
    )

    fan_out = projector.dirty_across_organization(organization, [structure.pk])
    state_module.merge(metric, [ref for refs in fan_out.values() for ref in refs])

    states = evidence_models.State.objects.for_organization(organization).filter(key="vector_length")
    assert {state.entity_ref for state in states} == {ref_a, ref_b}
    assert all(state.n == 1 and state.sum == pytest.approx(42.0) for state in states)


def test_a_graph_with_no_informed_entity_is_not_in_the_fan_out(
    organization: Organization,
    graph_a: core_models.Graph,
    graph_b: core_models.Graph,
    roi_kind: evidence_models.StructureKind,
    assertion: evidence_models.Assertion,
) -> None:
    """Only graphs that actually read this evidence get projected.

    The fan-out is a lookup on the links, not a sweep over every graph in the
    organization — otherwise a tenant with a hundred projections would pay for
    all of them on every write.
    """
    structure = writer.ensure_structure(organization, roi_kind, "roi-only-a", assertion)
    writer.create_link(
        organization,
        kind=evidence_models.Link.Kind.INFORMS,
        source_ref=str(structure.pk),
        target_ref=REF_A.format(graph=graph_a.age_name),
        assertion=assertion,
    )

    fan_out = projector.dirty_across_organization(organization, [structure.pk])

    assert set(fan_out) == {graph_a.age_name}
    assert graph_b.age_name not in fan_out


def test_the_fan_out_stops_at_the_organization(
    organization: Organization,
    other_organization: Organization,
    graph_a: core_models.Graph,
    shared_across_two_graphs: tuple[evidence_models.Structure, str, str],
) -> None:
    """Sharing is within a tenant, and the fan-out has to respect that.

    Widening the write path is exactly where a tenant boundary is easiest to lose.
    """
    structure, _, _ = shared_across_two_graphs

    assert projector.dirty_across_organization(other_organization, [structure.pk]) == {}
