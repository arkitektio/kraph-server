"""Evidence must never be readable without naming an organization.

This is one half of the tenancy decision. Structures and metrics used to live in
a per-graph Apache AGE namespace, where a query against graph A *physically could
not* read graph B's rows. Sharing evidence across projections gives that
structural guarantee up, so the guard that replaces it has to be tested as
carefully as the thing it replaced: one forgotten filter is a cross-tenant leak.

The companion test is `test_cross_projection_visibility.py`, which asserts the
opposite direction — that evidence *is* shared within an organization. Together
they are the whole `graph_id` decision.
"""

import pytest
from django.db import models

from evidence import models as evidence_models
from evidence.managers import UnscopedEvidenceAccess
from authentikate.models import Organization
from core import models as core_models

EVIDENCE_MODELS = [
    evidence_models.Assertion,
    evidence_models.Structure,
    evidence_models.Metric,
    evidence_models.Link,
    evidence_models.LifecycleEvent,
]


@pytest.mark.parametrize("model", EVIDENCE_MODELS, ids=lambda m: m.__name__)
def test_unscoped_access_raises(model: type[models.Model]) -> None:
    """`Model.objects.all()` must fail rather than span tenants."""
    with pytest.raises(UnscopedEvidenceAccess):
        model.objects.all()


@pytest.mark.parametrize("model", EVIDENCE_MODELS, ids=lambda m: m.__name__)
def test_unscoped_filter_raises(model: type[models.Model]) -> None:
    """A filter that happens to omit `organization` must fail too.

    This is the realistic mistake — not `.all()`, but a filter that looks
    perfectly reasonable and is missing one term.
    """
    with pytest.raises(UnscopedEvidenceAccess):
        model.objects.filter(pk=None)


@pytest.mark.parametrize("model", EVIDENCE_MODELS, ids=lambda m: m.__name__)
def test_scoped_access_returns_a_queryset(model: type[models.Model], organization: Organization) -> None:
    """`for_organization` is the supported entry point and must work."""
    assert isinstance(model.objects.for_organization(organization), models.QuerySet)


def test_structures_of_one_organization_are_invisible_to_another(organization: Organization, other_organization: Organization, roi_category_a: core_models.StructureCategory, assertion: evidence_models.Assertion) -> None:
    """The leak this whole mechanism exists to prevent."""
    evidence_models.Structure.objects.create_for_organization(
        organization=organization,
        category=roi_category_a,
        identifier="@mikro/roi",
        object="roi-1",
        assertion=assertion,
    )

    assert evidence_models.Structure.objects.for_organization(organization).count() == 1
    assert evidence_models.Structure.objects.for_organization(other_organization).count() == 0


def test_all_objects_is_the_only_unrestricted_path(organization: Organization, roi_category_a: core_models.StructureCategory, assertion: evidence_models.Assertion) -> None:
    """The escape hatch exists and is deliberately awkward to reach for.

    Django's own internals (cascade deletion, reverse descriptors) need an
    unrestricted manager, so one has to exist. It is named `all_objects` rather
    than `objects` precisely so that reaching for it is a visible choice that
    shows up in review and in grep.
    """
    evidence_models.Structure.objects.create_for_organization(
        organization=organization,
        category=roi_category_a,
        identifier="@mikro/roi",
        object="roi-1",
        assertion=assertion,
    )

    assert evidence_models.Structure.all_objects.count() == 1


def test_django_internals_use_the_unrestricted_manager(organization: Organization, roi_category_a: core_models.StructureCategory, assertion: evidence_models.Assertion) -> None:
    """Reverse accessors must not trip the guard.

    If `_base_manager` / `_default_manager` resolved to the raising manager, this
    cascade would explode instead of deleting — which is how a well-meaning
    scoping guard breaks the framework it lives in.
    """
    structure = evidence_models.Structure.objects.create_for_organization(
        organization=organization,
        category=roi_category_a,
        identifier="@mikro/roi",
        object="roi-1",
        assertion=assertion,
    )

    assert list(assertion.structures.all()) == [structure]
    roi_category_a.delete()
    assert evidence_models.Structure.all_objects.count() == 0
