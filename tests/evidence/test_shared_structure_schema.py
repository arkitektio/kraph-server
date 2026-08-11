"""Two graphs measuring the same datum share one term.

This file used to assert the opposite, and that inversion is the point of the
change rather than a side effect of it.

Before, structure and metric categories hung off a graph. A structure introduced
by graph A carried A's category, so a measurement recorded through graph B
resolved against A's schema — gated on A's permissions, and filing any
auto-created metric category under A where B could not see it. The old tests here
documented that as expected behaviour and pinned it in place.

Now the vocabulary belongs to the organization. `@mikro/roi` is an identifier
owned by the service that produces the datum, so there is exactly one term for it
and both graphs see the same one. There is no acting graph to resolve against and
no per-graph copy to disagree with.
"""

import pytest
from authentikate.models import Organization

from core import models as core_models
from core.enums import ValueKind
from evidence import models as evidence_models
from evidence import writer


@pytest.fixture
def shared_structure(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
    assertion: evidence_models.Assertion,
) -> evidence_models.Structure:
    """One structure, first referenced while building graph A."""
    return writer.ensure_structure(organization, roi_kind, "roi-shared", assertion)


def test_both_graphs_resolve_the_same_structure_kind(
    organization: Organization,
    graph_a: core_models.Graph,
    graph_b: core_models.Graph,
) -> None:
    """The term is the organization's, so resolving it twice returns one row.

    Two graphs, two calls, one `StructureKind`. This previously produced two rows
    identical in everything but which graph owned them.
    """
    from_a = writer.ensure_structure_kind(organization, "@mikro/roi")
    from_b = writer.ensure_structure_kind(organization, "@mikro/roi")

    assert from_a.pk == from_b.pk
    assert evidence_models.StructureKind.objects.for_organization(organization).filter(identifier="@mikro/roi").count() == 1


def test_a_structure_reached_from_either_graph_is_the_same_row(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
    shared_structure: evidence_models.Structure,
    assertion: evidence_models.Assertion,
) -> None:
    """And it carries the one term, so "whose category is this" has no meaning."""
    again = writer.ensure_structure(organization, roi_kind, "roi-shared", assertion)

    assert again.pk == shared_structure.pk
    assert again.kind_id == roi_kind.pk


def test_a_measurement_recorded_by_either_graph_uses_one_term(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
    shared_structure: evidence_models.Structure,
    assertion: evidence_models.Assertion,
) -> None:
    """The defect this file used to document, now impossible.

    Whichever graph records the measurement, `ensure_metric_kind` resolves the
    same organization-level term — so the second graph can see what the first
    recorded, which is the whole reason evidence is shared.
    """
    from_a = writer.ensure_metric_kind(organization, roi_kind, "vector_length", ValueKind.FLOAT)
    from_b = writer.ensure_metric_kind(organization, roi_kind, "vector_length", ValueKind.FLOAT)

    assert from_a.pk == from_b.pk

    metric = writer.record_metric(
        organization,
        shared_structure,
        from_b,
        key="vector_length",
        value=45.2,
        assertion=assertion,
    )
    assert metric.kind_id == from_a.pk


def test_a_contradicting_value_kind_is_rejected(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
) -> None:
    """One term, one type — and a disagreement is surfaced rather than resolved.

    With separate per-graph categories, one graph could call `vector_length` a
    number and another a string, and both would "work" while storing the same
    measurement in different columns. Merged into one term, that is a real
    conflict, so it raises and names both kinds.
    """
    writer.ensure_metric_kind(organization, roi_kind, "vector_length", ValueKind.FLOAT)

    with pytest.raises(ValueError) as excinfo:
        writer.ensure_metric_kind(organization, roi_kind, "vector_length", ValueKind.STRING)

    message = str(excinfo.value)
    assert "FLOAT" in message and "STRING" in message, "The error must name both kinds to be actionable"


def test_the_same_key_on_different_structures_is_a_different_term(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
) -> None:
    """`vector_length` on an ROI and on a Mask are separate quantities.

    Identity is `(organization, structure_kind, key)`. The old table enforced
    `(graph, key)` while the lookup used `(graph, key, structure_category)`, so
    two metrics named `area` on different structures collided at the database
    level.
    """
    mask_kind = writer.ensure_structure_kind(organization, "@mikro/mask")

    on_roi = writer.ensure_metric_kind(organization, roi_kind, "area", ValueKind.FLOAT)
    on_mask = writer.ensure_metric_kind(organization, mask_kind, "area", ValueKind.FLOAT)

    assert on_roi.pk != on_mask.pk


def test_kinds_never_cross_organizations(
    organization: Organization,
    other_organization: Organization,
) -> None:
    """Sharing is within a tenant. It has to stop at the tenant boundary."""
    writer.ensure_structure_kind(organization, "@mikro/roi")
    writer.ensure_structure_kind(other_organization, "@mikro/roi")

    assert evidence_models.StructureKind.objects.for_organization(organization).count() == 1
    assert evidence_models.StructureKind.objects.for_organization(other_organization).count() == 1
    assert evidence_models.StructureKind.all_objects.filter(identifier="@mikro/roi").count() == 2
