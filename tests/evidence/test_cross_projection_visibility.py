"""Evidence written while building one projection is visible to another.

The other half of the `graph_id` decision. `test_org_scoping.py` proves evidence
never crosses an organization; this proves it *does* cross a graph — which is the
entire point of moving the tenancy key up. If both pass, the base relation and
the view no longer share a scope.

Read these together. Either one alone describes a system that is either leaky or
useless.
"""

from datetime import datetime, timezone

from core.enums import ValueKind
from evidence import models as evidence_models
from authentikate.models import Organization
from core import models as core_models

MEASURED_AT = datetime(2026, 3, 3, 10, 0, tzinfo=timezone.utc)


def test_a_metric_recorded_under_one_graph_is_readable_under_another(organization: Organization, roi_category_a: evidence_models.StructureKind, roi_category_b: evidence_models.StructureKind, length_category: evidence_models.MetricKind, assertion: evidence_models.Assertion) -> None:
    """The win that does not need entity identity.

    Experiment A records a length for an ROI. A projection built for experiment
    B, over the same organization, sees that metric without re-ingesting it.
    Under per-graph AGE namespaces this was impossible by construction.
    """
    structure = evidence_models.Structure.objects.create_for_organization(
        organization=organization,
        kind=roi_category_a,
        identifier="@mikro/roi",
        object="roi-42",
        assertion=assertion,
    )
    evidence_models.Metric.objects.create_for_organization(
        organization=organization,
        structure=structure,
        kind=length_category,
        key="vector_length",
        value_kind=ValueKind.FLOAT.value,
        value_num=45.2,
        measured_at=MEASURED_AT,
        asserted_at=MEASURED_AT,
        assertion=assertion,
    )

    # Experiment B resolves the same real-world datum through its own category.
    # It finds the existing row rather than creating a parallel one.
    seen_from_b = evidence_models.Structure.objects.for_organization(organization).get(
        identifier=roi_category_b.identifier,
        object="roi-42",
    )

    assert seen_from_b.pk == structure.pk
    assert [m.value for m in seen_from_b.metrics.all()] == [45.2]


def test_provenance_scoping_is_a_filter_not_a_fork(organization: Organization, roi_category_a: evidence_models.StructureKind, length_category: evidence_models.MetricKind) -> None:
    """'Only what AI_Model_X asserted before March 3rd' is a WHERE clause.

    Under per-graph silos this needed a separate graph. Over shared evidence it
    is an indexed filter, which is what makes `Graph.selector` — and the `as_of`
    that falls out of it — cheap enough to be routine.
    """
    early = datetime(2026, 3, 1, tzinfo=timezone.utc)
    late = datetime(2026, 3, 5, tzinfo=timezone.utc)

    trusted = evidence_models.Assertion.objects.create_for_organization(organization=organization, subject="AI_Model_X", app_id="mikro", asserted_at=early)
    later_revision = evidence_models.Assertion.objects.create_for_organization(organization=organization, subject="AI_Model_X", app_id="mikro", asserted_at=late)
    someone_else = evidence_models.Assertion.objects.create_for_organization(organization=organization, subject="AI_Model_Y", app_id="mikro", asserted_at=early)

    structure = evidence_models.Structure.objects.create_for_organization(
        organization=organization,
        kind=roi_category_a,
        identifier="@mikro/roi",
        object="roi-42",
        assertion=trusted,
    )
    for value, source in ((1.0, trusted), (2.0, later_revision), (3.0, someone_else)):
        evidence_models.Metric.objects.create_for_organization(
            organization=organization,
            structure=structure,
            kind=length_category,
            key="vector_length",
            value_kind=ValueKind.FLOAT.value,
            value_num=value,
            measured_at=MEASURED_AT,
            asserted_at=source.asserted_at,
            assertion=source,
        )

    selected = evidence_models.Metric.objects.for_organization(organization).filter(
        assertion__subject="AI_Model_X",
        asserted_at__lt=MEASURED_AT,
    )

    assert [m.value for m in selected] == [1.0]
