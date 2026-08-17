"""Dirty tracking, and the O(N x P) regression it exists to prevent.

The old design re-derived an entity's properties once per fact written. Ingesting
a thousand measurements against one ROI meant a thousand recalculations, each
re-reading every measurement seen so far — quadratic in the evidence and linear
again in the number of projections.

The replacement separates two steps that used to be one. Folding a metric into
its state vector is O(1) and happens per metric. Writing the derived value onto
the graph happens once per *dirty set*, however many metrics produced it.
"""

from datetime import datetime, timedelta, timezone

import pytest
from authentikate.models import Organization

from core import models as core_models
from evidence import models as evidence_models
from evidence import state as state_module
from evidence import writer
from graph_engine import projector

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
            measured_at=BASE_TIME + timedelta(minutes=index),
        )
        state_module.merge(metric, [claim_ref])

    states = evidence_models.State.objects.for_organization(organization).filter(claim_ref=claim_ref)
    assert states.count() == 1, "A hundred metrics fold into one state row, not a hundred"

    state = states.get()
    assert state.n == 100
    assert state.sum == pytest.approx(sum(range(100)))

    # And the whole ingest collapses to a single projection target.
    assert projector.dirty(graph_a, [structure.pk]) == [claim_ref]
