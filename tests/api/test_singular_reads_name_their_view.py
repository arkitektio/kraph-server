"""A singular node read is a view's answer, so the view is named.

`node(id:)` used to take no graph and answer from `drawings[0]` — whichever view
`projector.graphs_for_refs` happened to yield first — so a node drawn by two
graphs reported one of their labels, categories and derived properties with
nothing on the result saying which. The singular fetchers take a `graph` now and
go through the same membership-then-drawing path as `nodes(graph:)`:

- drawn in that view → the drawing;
- admitted but not yet drawn → the bare row shape (no derived properties), which
  `tests/api/test_write_payloads_are_claims.py` pins;
- not admitted by that view → refused, with `instance(id:)` as the claim-grain
  reader.

The stats test at the bottom pins the other half of the same audit: the `*Stats`
resolvers used to build `model.objects.all()`, which aggregated across
organizations for the core models and raised `UnscopedEvidenceAccess` outright
for `StructureKind`/`MetricKind` — two root fields that could never answer.
"""

import kante
import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext

from core import models as core_models
from tests.support import writes

NODE = """
    query GetNode($id: ID!, $graph: ID!) {
        node(id: $id, graph: $graph) { __typename id drawnIn { graph { id } } }
    }
"""

INSTANCE = """
    query GetInstance($id: ID!) {
        instance(id: $id) { id term { key } }
    }
"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_view_that_does_not_admit_the_node_refuses_it(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    minimal_schema,
    table_projector,
    authenticated_context,
) -> None:
    """Declared-in-A, not-in-B: A answers the drawing, B refuses, the claim answers either way.

    `node(id, g)` succeeds exactly when `nodes(graph: g)` could list the node —
    the singular and plural reads are answer-equivalent now, where the singular
    used to reach through every view and hand back an arbitrary one.
    """
    from graph_engine.materialize import materialize

    entity_id = await writes.create_entity(api_schema, simple_api_context, "AIS")

    @sync_to_async
    def person_graph() -> core_models.Graph:
        request = authenticated_context.request
        return materialize(
            minimal_schema,
            table_projector,
            user=request._user,
            organization=request._organization,
            membership=request.membership,
            name="person_graph",
        )

    other_view = await person_graph()

    held = await api_schema.execute(NODE, variable_values={"id": entity_id, "graph": str(test_graph.id)}, context_value=simple_api_context)
    assert held.errors is None, f"GraphQL errors: {held.errors}"
    assert held.data["node"]["__typename"] == "Entity"
    assert held.data["node"]["drawnIn"], "The write drew it, so this view answers with the drawing"

    refused = await api_schema.execute(NODE, variable_values={"id": entity_id, "graph": str(other_view.id)}, context_value=simple_api_context)
    assert refused.errors, "A view declaring no category for the word must refuse the node, not borrow another view's drawing"
    assert "does not hold" in str(refused.errors[0]), f"Refused for the wrong reason: {refused.errors[0]}"

    claim = await api_schema.execute(INSTANCE, variable_values={"id": entity_id}, context_value=simple_api_context)
    assert claim.errors is None, f"GraphQL errors: {claim.errors}"
    assert claim.data["instance"]["term"]["key"] == "AIS", "The claim is view-independent and stays readable"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_typed_fetchers_guard_the_kind(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """`entity(id:, graph:)` on an event id is refused, not wrapped.

    It used to hand whatever row the id named to the `Entity` type blindly, so an
    event's uuid came back wearing the wrong `__typename`.
    """
    event_id = await writes.create_event(api_schema, simple_api_context, "Mitosis")

    read = await api_schema.execute(
        "query GetEntity($id: ID!, $graph: ID!) { entity(id: $id, graph: $graph) { id } }",
        variable_values={"id": event_id, "graph": str(test_graph.id)},
        context_value=simple_api_context,
    )
    assert read.errors, "An event read through the entity fetcher must be refused"
    assert "not an entity" in str(read.errors[0]), f"Refused for the wrong reason: {read.errors[0]}"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stats_answer_and_stay_inside_the_organization(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """`structureKindStats` answers at all, and every stats field counts one tenant.

    The generated resolvers built `model.objects.all()`: a hard
    `UnscopedEvidenceAccess` for the evidence kinds — the raising default manager
    doing its job against an unscoped read — and a cross-tenant aggregate for the
    seven core models. They take a required `scope` now.
    """
    from authentikate.models import Membership, Organization
    from evidence import models as evidence_models

    # A structure kind in our organization, minted the way ingest mints one.
    await writes.create_entity(api_schema, simple_api_context, "AIS")

    @sync_to_async
    def foreign_rows() -> None:
        other, _ = Organization.objects.get_or_create(slug="a-tenant-next-door")
        membership = Membership.objects.filter(organization=other).first()
        if membership is None:
            membership = Membership.objects.create(user=test_graph.membership.user, organization=other)
        # `all_objects` because crossing tenants is the point of the fixture.
        evidence_models.StructureKind.all_objects.get_or_create(organization=other, identifier="ForeignROI")
        core_models.Graph.objects.get_or_create(
            name="NextDoorGraph",
            defaults=dict(
                membership=membership,
                organization=other,
                user=test_graph.user,
            ),
        )

    await foreign_rows()

    @sync_to_async
    def own_counts() -> tuple[int, int]:
        org = test_graph.organization
        return (
            evidence_models.StructureKind.objects.for_organization(org).count(),
            core_models.Graph.objects.filter(organization=org).count(),
        )

    own_kinds, own_graphs = await own_counts()

    result = await api_schema.execute(
        "query Stats { structureKindStats { count } graphStats { count } }",
        context_value=simple_api_context,
    )
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data["structureKindStats"]["count"] == own_kinds, "The evidence-kind stats answer, scoped to the caller's organization"
    assert result.data["graphStats"]["count"] == own_graphs, "The graph next door is not in this tenant's count"
