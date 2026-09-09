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
from datetime import datetime, timezone
from core.enums import ValueKind
import kante
from asgiref.sync import sync_to_async
from kante.context import HttpContext
from core import models as core_models
from evidence import writer as evidence_writer
from tests.support import writes
from evidence import writer


EVIDENCE_MODELS = [
    evidence_models.Assertion,
    evidence_models.Structure,
    evidence_models.Metric,
    evidence_models.Link,
    evidence_models.Standing,
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


def test_structures_of_one_organization_are_invisible_to_another(organization: Organization, other_organization: Organization, roi_category_a: evidence_models.StructureKind, assertion: evidence_models.Assertion) -> None:
    """The leak this whole mechanism exists to prevent."""
    evidence_models.Structure.objects.create_for_organization(
        organization=organization,
        kind=roi_category_a,
        identifier="@mikro/roi",
        object="roi-1",
        assertion=assertion,
    )

    assert evidence_models.Structure.objects.for_organization(organization).count() == 1
    assert evidence_models.Structure.objects.for_organization(other_organization).count() == 0


def test_all_objects_is_the_only_unrestricted_path(organization: Organization, roi_category_a: evidence_models.StructureKind, assertion: evidence_models.Assertion) -> None:
    """The escape hatch exists and is deliberately awkward to reach for.

    Django's own internals (cascade deletion, reverse descriptors) need an
    unrestricted manager, so one has to exist. It is named `all_objects` rather
    than `objects` precisely so that reaching for it is a visible choice that
    shows up in review and in grep.
    """
    evidence_models.Structure.objects.create_for_organization(
        organization=organization,
        kind=roi_category_a,
        identifier="@mikro/roi",
        object="roi-1",
        assertion=assertion,
    )

    assert evidence_models.Structure.all_objects.count() == 1


def test_django_internals_use_the_unrestricted_manager(organization: Organization, roi_category_a: evidence_models.StructureKind, assertion: evidence_models.Assertion) -> None:
    """Reverse accessors must not trip the guard.

    If `_base_manager` / `_default_manager` resolved to the raising manager, the
    collector Django runs before a delete would raise `UnscopedEvidenceAccess`
    instead of finding the related rows — which is how a well-meaning scoping
    guard breaks the framework it lives in.

    The delete used to cascade, and this asserted the structure was gone.
    `Structure.kind` is `PROTECT` now, so the same traversal produces a
    `ProtectedError` instead: the collector still had to walk the reverse
    accessor to know what was in the way, which is the property under test, and
    the evidence survives, which is the property that changed.
    """
    from django.db.models import ProtectedError

    structure = evidence_models.Structure.objects.create_for_organization(
        organization=organization,
        kind=roi_category_a,
        identifier="@mikro/roi",
        object="roi-1",
        assertion=assertion,
    )

    assert list(assertion.structures.all()) == [structure]

    with pytest.raises(ProtectedError):
        roi_category_a.delete()

    assert evidence_models.Structure.all_objects.count() == 1, "Deleting vocabulary must not delete the evidence expressed in it"


OBSERVED_AT = datetime(2026, 3, 3, 10, 0, tzinfo=timezone.utc)


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
        observed_at=OBSERVED_AT,
        asserted_at=OBSERVED_AT,
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
            observed_at=OBSERVED_AT,
            asserted_at=source.asserted_at,
            assertion=source,
        )

    selected = evidence_models.Metric.objects.for_organization(organization).filter(
        assertion__subject="AI_Model_X",
        asserted_at__lt=OBSERVED_AT,
    )

    assert [m.value for m in selected] == [1.0]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_claim_cannot_reach_into_another_organization(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """A write refuses a reference belonging to a different tenant.

    Membership alone stopped being enough when the organization started coming from
    the request instead of from the row the caller named. `_resolve_instance` authorizes
    against the *node's* organization, so a user who belongs to two would pass that
    check for a node in either — and the resulting `Link` would sit in one tenant
    naming rows in the other, invisible to every query scoped to its own endpoints.

    Built by hand rather than through a second authenticated context, because the
    point is the controller's guard and not the auth extension's.
    """
    from authentikate.models import Membership, Organization

    from graph_engine import controller as controller_module

    source = await writes.create_entity(api_schema, simple_api_context, "Cell")

    @sync_to_async
    def foreign_node() -> str:
        other, _ = Organization.objects.get_or_create(slug="a-different-tenant")
        # The caller is a member of *both* tenants. That is the whole scenario:
        # `_assert_can_access` passes for rows in either, so membership alone cannot
        # stop a claim in one from naming rows in the other. Without this line the
        # write is refused for lack of membership and the guard under test never runs.
        Membership.objects.get_or_create(user=simple_api_context.request._user, organization=other)
        assertion = evidence_writer.create_assertion(other, subject="someone-else", app_id="elsewhere")
        term = evidence_writer.ensure_term(other, "ENTITY", "Cell")
        node = evidence_models.Instance.objects.create_for_organization(
            organization=other,
            kind=evidence_models.Instance.Kind.ENTITY,
            term=term,
            assertion=assertion,
        )
        return str(node.pk)

    outsider = await foreign_node()

    @sync_to_async
    def attempt() -> str:
        controller = controller_module.GraphController(projector=None)
        try:
            controller._resolve_instance(outsider, None, organization=test_graph.organization)
        except PermissionError as error:
            return str(error)
        return ""

    refusal = await attempt()
    assert "another organization" in refusal, "A node from another tenant must be refused, not linked"

    # And through a real mutation, not only the guard in isolation: the guard
    # existing proves nothing if a call site forgets to pass the organization, and a
    # test that only calls `_resolve_instance` stays green when one does.
    attempted = await api_schema.execute(
        """
        mutation CreateRelation($input: AssertRelationExistsInput!) {
            assertRelationExists(input: $input) { link { id } }
        }
        """,
        variable_values={"input": {"term": "IS_CONNECTED_TO", "sourceId": source, "targetId": outsider}},
        context_value=simple_api_context,
    )
    assert attempted.errors, "createRelation must refuse an endpoint from another tenant"
    assert "another organization" in str(attempted.errors[0]), f"Refused for the wrong reason: {attempted.errors[0]}"

    # And the same node is fine when the write is made in its own organization.
    @sync_to_async
    def allowed() -> bool:
        from authentikate.models import Organization as Org

        controller = controller_module.GraphController(projector=None)
        other = Org.objects.get(slug="a-different-tenant")
        return controller._resolve_instance(outsider, None, organization=other) is not None

    assert await allowed(), "The guard is about the tenant, not about the node"
    assert source, "The in-tenant write that set this up still succeeded"


ASSERT_ENTITY = """
    mutation AssertEntityExists($input: AssertEntityExistsInput!) {
        assertEntityExists(input: $input) {
            assertion { id seq }
            instance { id }
        }
    }
"""


ASSERTIONS = """
    query Assertions($filters: AssertionFilter, $pagination: LogPaginationInput) {
        assertions(filters: $filters, pagination: $pagination) { id seq subject appId }
    }
"""


ASSERTION = """
    query Assertion($id: ID!) {
        assertion(id: $id) {
            id
            seq
            actionArgs
            instances { id term { key } }
            links { id kind }
            metrics { id }
            structures { id }
            standings { id stands target { __typename ... on Instance { id } ... on Link { id } } }
            comments { id }
        }
    }
"""


CHANGES = """
    query Changes($afterSeq: Int!, $limit: Int) {
        changes(afterSeq: $afterSeq, limit: $limit) {
            assertions { id seq }
            nextSeq
            horizon
        }
    }
"""


STANDINGS = """
    query Standings($id: ID, $filters: StandingFilter) {
        standings(id: $id, filters: $filters) {
            id
            stands
            target { __typename ... on Instance { id } ... on Link { id } }
        }
    }
"""


async def _execute(api_schema, ctx, document: str, variables: dict | None = None) -> dict:
    result = await api_schema.execute(document, variable_values=variables or {}, context_value=ctx)
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    return result.data


async def _assert_entity(api_schema, ctx, term: str = "AIS", evidence: list | None = None) -> dict:
    data = await _execute(api_schema, ctx, ASSERT_ENTITY, {"input": {"term": term, "supportingEvidence": evidence or []}})
    return data["assertEntityExists"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_log_is_tenant_scoped(api_schema, simple_api_context, test_graph, other_organization) -> None:  # noqa: F811
    foreign = await sync_to_async(writer.create_assertion)(other_organization, subject="1", app_id="test")
    own = await _assert_entity(api_schema, simple_api_context)

    listed = (await _execute(api_schema, simple_api_context, ASSERTIONS))["assertions"]
    assert str(foreign.pk) not in [row["id"] for row in listed]

    feed = (await _execute(api_schema, simple_api_context, CHANGES, {"afterSeq": 0}))["changes"]
    assert str(foreign.pk) not in [row["id"] for row in feed["assertions"]]
    assert own["assertion"]["id"] in [row["id"] for row in feed["assertions"]]

    result = await api_schema.execute(ASSERTION, variable_values={"id": str(foreign.pk)}, context_value=simple_api_context)
    assert result.errors, "another tenant's assertion is refused by id"

    positions = (await _execute(api_schema, simple_api_context, STANDINGS, {"filters": {"subjects": ["1"]}}))["standings"]
    assert all(row["target"]["id"] != str(foreign.pk) for row in positions)
