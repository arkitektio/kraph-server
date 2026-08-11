"""Fixtures for the relational evidence base.

Deliberately free of Apache AGE and of `materialize()`. These tests exercise the
evidence tables directly, so they need neither the docker AGE stack's graph
machinery nor a materialized schema — only Postgres. That independence is the
point: the evidence store has to be verifiable without the projection layer, or
it is not really the source of truth.
"""

from datetime import datetime, timezone

import pytest
from authentikate.models import Membership, Organization, User

from core import models as core_models
from core.enums import ValueKind
from evidence import models as evidence_models


@pytest.fixture
def organization(db: None, backend_stack: None) -> Organization:
    """The tenant most of these tests write evidence under."""
    org, _ = Organization.objects.get_or_create(slug="evidence-org")
    return org


@pytest.fixture
def other_organization(db: None, backend_stack: None) -> Organization:
    """A second tenant. Nothing it owns may ever be visible to `organization`."""
    org, _ = Organization.objects.get_or_create(slug="other-evidence-org")
    return org


@pytest.fixture
def user(db: None, backend_stack: None) -> User:
    """A user to own the graphs categories still hang off."""
    user, _ = User.objects.get_or_create(username="evidence-user", sub="evidence-sub")
    return user


def _make_graph(name: str, organization: Organization, user: User) -> core_models.Graph:
    """A Graph row with no AGE namespace behind it.

    Graphs exist here only because categories still hang off one before the
    ontology re-parents to the organization. No projection is ever built from
    them in these tests.
    """
    membership, _ = Membership.objects.get_or_create(user=user, organization=organization)
    return core_models.Graph.objects.create(
        name=name,
        age_name=f"{name}_{organization.slug}".replace("-", "_"),
        user=user,
        membership=membership,
        organization=organization,
    )


@pytest.fixture
def graph_a(organization: Organization, user: User) -> core_models.Graph:
    """One projection over the organization's evidence."""
    return _make_graph("graph_a", organization, user)


@pytest.fixture
def graph_b(organization: Organization, user: User) -> core_models.Graph:
    """A second projection over the *same* organization's evidence."""
    return _make_graph("graph_b", organization, user)


@pytest.fixture
def roi_kind(organization: Organization) -> evidence_models.StructureKind:
    """The ROI term. One per organization — there is no per-graph variant to have."""
    return evidence_models.StructureKind.all_objects.create(
        organization=organization,
        identifier="@mikro/roi",
    )


# Both graphs now reach the *same* term. Kept as separate fixture names so tests
# that used to assert two categories can assert one, which is the point.
@pytest.fixture
def roi_category_a(roi_kind: evidence_models.StructureKind) -> evidence_models.StructureKind:
    """The ROI term as reached from graph A."""
    return roi_kind


@pytest.fixture
def roi_category_b(roi_kind: evidence_models.StructureKind) -> evidence_models.StructureKind:
    """The same term, reached from graph B. Deliberately identical to `roi_category_a`."""
    return roi_kind


@pytest.fixture
def length_category(organization: Organization, roi_kind: evidence_models.StructureKind) -> evidence_models.MetricKind:
    """A float-valued measurement term describing an ROI."""
    return evidence_models.MetricKind.all_objects.create(
        organization=organization,
        structure_kind=roi_kind,
        key="vector_length",
        value_kind=ValueKind.FLOAT.value,
    )


@pytest.fixture
def assertion(organization: Organization) -> evidence_models.Assertion:
    """A provenance row every other fixture can hang evidence off."""
    return evidence_models.Assertion.objects.create_for_organization(
        organization=organization,
        subject="tester",
        app_id="pytest",
        action_name="record_evidence",
        asserted_at=datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc),
    )
