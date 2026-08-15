"""Fixtures for the projector.

Shares the evidence fixtures: the projector's whole job is turning those rows
into a graph, so it needs the same organizations, graphs and categories.

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


def _category(graph: core_models.Graph, key: str) -> core_models.EntityCategory:
    """A graph's category for a word, minting the organization's term for it.

    Created directly rather than through the manager because these tests never
    build a schema — but the term still has to exist, because that is what a
    claim names and what decides which views hold the node.
    """
    from evidence import writer

    return core_models.EntityCategory.objects.create(
        graph=graph,
        term=writer.ensure_term(graph.organization, core_models.EntityCategory.KIND, key),
        key=key,
        age_name=key,
        label=key,
    )


@pytest.fixture
def entity_category_a(graph_a: core_models.Graph) -> core_models.EntityCategory:
    """A word graph A declares, so nodes claimed under it belong to graph A."""
    return _category(graph_a, "AIS")


@pytest.fixture
def entity_category_b(graph_b: core_models.Graph) -> core_models.EntityCategory:
    """A **different** word, declared by graph B alone.

    Deliberately not "AIS". Two graphs declaring the same word now share the term,
    so a node claimed under it is in both — which is the point of the change, and
    `test_a_word_two_graphs_declare_is_seen_by_both` covers it. The fixtures that
    want *isolation* have to ask for two different words, or they would be
    asserting the opposite of what the model says.
    """
    return _category(graph_b, "Soma")


@pytest.fixture
def make_node(organization: Organization, assertion: evidence_models.Assertion):
    """Create a real node in a graph and hand back its ref.

    These tests used to fake a node with a string — `f"{graph.age_name}:{uuid}"` —
    and rely on the projector reading membership off that prefix. There is no
    prefix now: which graph shows a node is decided by its term, so the node has
    to actually exist for the question to have an answer. Faking it was always
    the weaker test; it asserted that a string parser worked.
    """

    def _make(category: core_models.Category) -> str:
        node = evidence_models.Node.objects.create_for_organization(
            organization=organization,
            kind=evidence_models.Node.Kind.ENTITY,
            # The node names the *word*, not this graph's category for it. Which
            # views show it follows from which of them declare that word.
            term=category.term,
            assertion=assertion,
        )
        return node.ref

    return _make


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


@pytest.fixture
def second_graph(test_graph: core_models.Graph, bio_graph_schema, age_engine, authenticated_context) -> core_models.Graph:
    """A second full projection over the same organization's evidence.

    Materialized from the same schema as `test_graph`, so both declare an AIS
    entity with a MEAN rollup over ROI — which is what makes "did both move?" a
    meaningful question.
    """
    from graph_engine.materialize import materialize

    request = authenticated_context.request
    return materialize(
        bio_graph_schema,
        age_engine,
        user=request._user,
        organization=request._organization,
        membership=request.membership,
        name="second_graph",
    )
