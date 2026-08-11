"""One real-world datum is one structure row, however many projections use it.

This is the storage-and-ingest half of moving evidence off `graph_id`. Under the
old per-graph AGE namespaces, referencing the same Mikro ROI while building two
graphs produced two structure vertices and required the metrics to be ingested
twice. The uniqueness constraint here is what makes that one row.
"""

import pytest
from django.db import IntegrityError, transaction

from evidence import models as evidence_models
from authentikate.models import Organization
from core import models as core_models


def test_same_object_from_two_projections_is_one_row(organization: Organization, roi_category_a: core_models.StructureCategory, roi_category_b: core_models.StructureCategory, assertion: evidence_models.Assertion) -> None:
    """The headline: two graphs, one structure.

    The categories differ — they are still graph-scoped at this point — but
    identity is `(organization, identifier, object)`, so the second write is a
    constraint violation rather than a duplicate.
    """
    evidence_models.Structure.objects.create_for_organization(
        organization=organization,
        category=roi_category_a,
        identifier="@mikro/roi",
        object="roi-42",
        assertion=assertion,
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        evidence_models.Structure.objects.create_for_organization(
            organization=organization,
            category=roi_category_b,
            identifier="@mikro/roi",
            object="roi-42",
            assertion=assertion,
        )

    assert evidence_models.Structure.objects.for_organization(organization).count() == 1


def test_different_objects_are_different_structures(organization: Organization, roi_category_a: core_models.StructureCategory, assertion: evidence_models.Assertion) -> None:
    """Identity is per external object, not per identifier."""
    for object_id in ("roi-1", "roi-2"):
        evidence_models.Structure.objects.create_for_organization(
            organization=organization,
            category=roi_category_a,
            identifier="@mikro/roi",
            object=object_id,
            assertion=assertion,
        )

    assert evidence_models.Structure.objects.for_organization(organization).count() == 2


def test_different_identifiers_over_the_same_object_are_distinct(organization: Organization, roi_category_a: core_models.StructureCategory, assertion: evidence_models.Assertion) -> None:
    """An image and an ROI can share an id string without being the same thing.

    `object` is only unique within an `identifier` namespace, which is why both
    columns are in the constraint.
    """
    evidence_models.Structure.objects.create_for_organization(
        organization=organization,
        category=roi_category_a,
        identifier="@mikro/roi",
        object="7",
        assertion=assertion,
    )
    evidence_models.Structure.objects.create_for_organization(
        organization=organization,
        category=roi_category_a,
        identifier="@mikro/image",
        object="7",
        assertion=assertion,
    )

    assert evidence_models.Structure.objects.for_organization(organization).count() == 2


def test_dedup_does_not_span_organizations(organization: Organization, other_organization: Organization, roi_category_a: core_models.StructureCategory, assertion: evidence_models.Assertion) -> None:
    """Two tenants may each hold a structure for the same object id.

    They are not the same datum — the id strings live in different namespaces —
    and collapsing them would be the leak, not the feature.
    """
    other_assertion = evidence_models.Assertion.objects.create_for_organization(
        organization=other_organization,
        subject="tester",
        app_id="pytest",
        asserted_at=assertion.asserted_at,
    )

    for org, assertion_row in ((organization, assertion), (other_organization, other_assertion)):
        evidence_models.Structure.objects.create_for_organization(
            organization=org,
            category=roi_category_a,
            identifier="@mikro/roi",
            object="roi-42",
            assertion=assertion_row,
        )

    assert evidence_models.Structure.objects.for_organization(organization).count() == 1
    assert evidence_models.Structure.objects.for_organization(other_organization).count() == 1
