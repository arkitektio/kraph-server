"""One measurement reaches every projection that reads it.

The behaviour change this whole piece of work is for, and a bug fix rather than a
feature. `dirty()` asks about a single graph, and every write path passed exactly
one — so a second projection over the same shared evidence went stale the moment
somebody recorded a metric through the first, and stayed stale until a manual
`reproject`.

That directly contradicts the point of sharing evidence across projections. If
these tests fail, ingest is graph-less in signature only.

The fan-out is now two steps rather than one: :func:`refs_informed_by` asks the
evidence base what a structure supports, and :func:`graphs_for_refs` asks which
views show those nodes. Splitting them is what lets the fold reach edge refs,
which belong to no graph and which the old grouped version silently dropped.
"""

import uuid

import pytest
from asgiref.sync import sync_to_async
from authentikate.models import Organization
from core import models as core_models
from evidence import models as evidence_models
from evidence import writer
from graph_engine import projector
from datetime import datetime, timedelta, timezone
from evidence import state as state_module
from tests.support import reads, writes


@pytest.fixture
def shared_across_two_graphs(
    organization: Organization,
    graph_a: core_models.Graph,
    graph_b: core_models.Graph,
    entity_category_a: core_models.EntityCategory,
    entity_category_b: core_models.EntityCategory,
    make_node,
    roi_kind: evidence_models.StructureKind,
    assertion: evidence_models.Assertion,
) -> tuple[evidence_models.Structure, str, str]:
    """One structure, informing an entity in each of two graphs."""
    structure = writer.ensure_structure(organization, roi_kind, "roi-shared-fanout", assertion)

    ref_a = make_node(entity_category_a)
    ref_b = make_node(entity_category_b)

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

    refs = projector.refs_informed_by(organization, [structure.pk])
    grouped = projector.graphs_for_refs(organization, refs)

    assert {graph.pk for graph in grouped} == {graph_a.pk, graph_b.pk}
    assert {graph.pk: value for graph, value in grouped.items()}[graph_a.pk] == [ref_a]
    assert {graph.pk: value for graph, value in grouped.items()}[graph_b.pk] == [ref_b]


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
    everything = projector.refs_informed_by(organization, [structure.pk])

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

    Two entities, so two state rows — one per node, not one per graph. Producing
    only one is the stale-second-graph bug.
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

    state_module.merge(metric, projector.refs_informed_by(organization, [structure.pk]))

    states = evidence_models.State.objects.for_organization(organization).filter(key="vector_length")
    assert {state.claim_ref for state in states} == {ref_a, ref_b}
    assert all(state.n == 1 and state.sum == pytest.approx(42.0) for state in states)


def test_a_graph_with_no_informed_entity_is_not_in_the_fan_out(
    organization: Organization,
    graph_a: core_models.Graph,
    graph_b: core_models.Graph,
    entity_category_a: core_models.EntityCategory,
    make_node,
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
        target_ref=make_node(entity_category_a),
        assertion=assertion,
    )

    grouped = projector.graphs_for_refs(organization, projector.refs_informed_by(organization, [structure.pk]))

    assert {graph.pk for graph in grouped} == {graph_a.pk}
    assert graph_b.pk not in {graph.pk for graph in grouped}


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

    assert projector.refs_informed_by(other_organization, [structure.pk]) == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_one_recorded_metric_moves_both_projections(
    api_schema,
    simple_api_context,
    test_graph: core_models.Graph,
    second_graph: core_models.Graph,
    table_projector,
) -> None:
    """The claim, checked through the mutation rather than around it.

    Two graphs, an entity in each, both informed by the same ROI. Record one
    measurement — naming no graph — and both entities' derived values move.

    The pieces are unit-tested above; this is the wiring. `_record_metric` has to
    call `dirty_across_organization` and fold across every ref it returns, and
    the write path has to project all of them. Testing the pieces separately
    would pass even if nothing joined them up.
    """
    object_id = f"roi_{uuid.uuid4().hex[:8]}"

    # Both views declare AIS with a MEAN over ROI; the write names the word, not a view.
    entity_ids = {str(graph.pk): await writes.create_entity(api_schema, simple_api_context, "AIS", evidence=writes.roi(object_id, 40.0)) for graph in (test_graph, second_graph)}

    structures = await sync_to_async(lambda: evidence_models.Structure.objects.for_organization(test_graph.organization).filter(object=object_id).count())()
    assert structures == 1, "Both graphs must be informed by the *same* structure row"

    # One measurement, no graph named anywhere.
    await writes.execute(api_schema, simple_api_context, writes.ASSERT_METRIC_VALUE, {"input": {"identifier": "ROI", "object": object_id, "key": "vector_length", "value": 60.0, "valueKind": "FLOAT"}})

    for graph_id, entity_id in entity_ids.items():
        avg = await reads.property_of(api_schema, simple_api_context, graph_id, entity_id, "avg_length")
        assert avg == pytest.approx(50.0), f"graph #{graph_id} still reads {avg}: mean of 40 and 60 is 50. A projection that did not move is the stale-second-graph bug."


BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def two_entities_one_structure(
    organization: Organization,
    graph_a: core_models.Graph,
    entity_category_a: core_models.EntityCategory,
    make_node,
    roi_category_a: evidence_models.StructureKind,
    assertion: evidence_models.Assertion,
) -> tuple[evidence_models.Structure, list[str]]:
    """One ROI that is evidence for two different entities."""
    structure = writer.ensure_structure(organization, roi_category_a, "roi-fanout", assertion)
    refs = [make_node(entity_category_a), make_node(entity_category_a)]

    for ref in refs:
        writer.create_link(
            organization,
            kind=evidence_models.Link.Kind.INFORMS,
            source_ref=str(structure.pk),
            target_ref=ref,
            assertion=assertion,
        )
    return structure, refs


def test_dirty_names_exactly_the_entities_the_structure_informs(
    graph_a: core_models.Graph,
    two_entities_one_structure: tuple[evidence_models.Structure, list[str]],
) -> None:
    """A new metric dirties both entities its structure supports — and no others."""
    structure, refs = two_entities_one_structure

    assert sorted(projector.dirty(graph_a, [structure.pk])) == sorted(refs)


def test_dirty_ignores_other_graphs_entities(
    organization: Organization,
    graph_a: core_models.Graph,
    graph_b: core_models.Graph,
    entity_category_b: core_models.EntityCategory,
    make_node,
    two_entities_one_structure: tuple[evidence_models.Structure, list[str]],
    assertion: evidence_models.Assertion,
) -> None:
    """Shared evidence must not drag another projection's nodes into the dirty set.

    A structure shared between two graphs dirties each graph's own nodes
    separately. Which graph a node belongs to is now decided by its term rather
    than by a prefix on its ref, so this asserts the same property against the
    mechanism that actually decides it.
    """
    structure, _ = two_entities_one_structure
    foreign_ref = make_node(entity_category_b)
    writer.create_link(
        organization,
        kind=evidence_models.Link.Kind.INFORMS,
        source_ref=str(structure.pk),
        target_ref=foreign_ref,
        assertion=assertion,
    )

    assert foreign_ref not in projector.dirty(graph_a, [structure.pk])
    assert projector.dirty(graph_b, [structure.pk]) == [foreign_ref]


def test_dirty_excludes_retracted_links(
    organization: Organization,
    graph_a: core_models.Graph,
    two_entities_one_structure: tuple[evidence_models.Structure, list[str]],
    assertion: evidence_models.Assertion,
) -> None:
    """A retracted INFORMS link stops propagating.

    Otherwise archiving the claim "this ROI supports that cell" would leave the
    cell being recomputed from evidence it no longer accepts.
    """
    structure, refs = two_entities_one_structure
    link = evidence_models.Link.objects.for_organization(organization).filter(target_ref=refs[0]).first()
    writer.retract(organization, link, assertion)

    assert projector.dirty(graph_a, [structure.pk]) == [refs[1]]


def test_bulk_ingest_folds_per_metric_but_projects_once(
    organization: Organization,
    graph_a: core_models.Graph,
    entity_category_a: core_models.EntityCategory,
    make_node,
    roi_category_a: evidence_models.StructureKind,
    length_category: evidence_models.MetricKind,
    assertion: evidence_models.Assertion,
) -> None:
    """The regression guard.

    A hundred metrics against one structure produce one state row and one dirty
    set. Under the old scheme this was a hundred recalculations, each re-reading
    the whole history.
    """
    structure = writer.ensure_structure(organization, roi_category_a, "roi-bulk", assertion)
    claim_ref = make_node(entity_category_a)
    writer.create_link(
        organization,
        kind=evidence_models.Link.Kind.INFORMS,
        source_ref=str(structure.pk),
        target_ref=claim_ref,
        assertion=assertion,
    )

    for index in range(100):
        metric = writer.record_metric(
            organization,
            structure,
            length_category,
            key="vector_length",
            value=float(index),
            assertion=assertion,
            observed_at=BASE_TIME + timedelta(minutes=index),
        )
        state_module.merge(metric, [claim_ref])

    states = evidence_models.State.objects.for_organization(organization).filter(claim_ref=claim_ref)
    assert states.count() == 1, "A hundred metrics fold into one state row, not a hundred"

    state = states.get()
    assert state.n == 100
    assert state.sum == pytest.approx(sum(range(100)))

    # And the whole ingest collapses to a single projection target.
    assert projector.dirty(graph_a, [structure.pk]) == [claim_ref]
