"""Who took part in an event is evidence, and must survive a reproject.

It was not recorded anywhere. `create_natural_event` bound the participating
entity as `ent` and never used it, so no edge between an entity and an event was
ever written — the participation queries in `api/queries/` asked for a shape
nothing produced. What it did write was a role *vertex* `MERGE`d with no
properties, which every event in the graph then shared, and the role name was
discarded by `get_age_input_role_edge_name`, which took a role and returned a
constant.

Protocol events could not get that far: `ProtocolEventCategory` defined neither
role-name method, so any protocol event with an input raised `AttributeError` —
after the vertex, the `Node` row, the `Assertion` and the state merges had
already committed. A torn write with no rollback.
"""

import kante
import uuid

import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext

from core import models as core_models
from evidence import models as evidence_models
from graph_engine.controller import GraphController

CREATE_ENTITY = """
    mutation CreateEntity($input: AssertEntityExistsInput!) {
        assertEntityExists(input: $input) { entity { id } }
    }
"""

CREATE_NATURAL_EVENT = """
    mutation CreateNaturalEvent($input: AssertNaturalEventExistsInput!) {
        assertNaturalEventExists(input: $input) { naturalEvent { id } }
    }
"""


async def _cell(api_schema: kante.Schema, ctx: HttpContext, graph: core_models.Graph) -> str:
    category = await core_models.EntityCategory.objects.filter(graph=graph, key="Cell").afirst()
    assert category is not None
    created = await api_schema.execute(
        CREATE_ENTITY,
        variable_values={"input": {"term": category.key, "supportingEvidence": []}},
        context_value=ctx,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    return created.data["assertEntityExists"]["entity"]["id"]


async def _mitosis(api_schema: kante.Schema, ctx: HttpContext, graph: core_models.Graph, source: str, target: str) -> str:
    category = await core_models.NaturalEventCategory.objects.filter(graph=graph, key="Mitosis").afirst()
    assert category is not None, "The bio schema declares a Mitosis event with Cell in and out"
    created = await api_schema.execute(
        CREATE_NATURAL_EVENT,
        variable_values={
            "input": {
                "term": category.key,
                "inputs": [{"role": "a", "entityId": source}],
                "outputs": [{"role": "b", "entityId": target}],
                "supportingEvidence": [],
            }
        },
        context_value=ctx,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    return created.data["assertNaturalEventExists"]["naturalEvent"]["id"]


def _participations(age_engine, graph: core_models.Graph) -> list[tuple[str, str]]:
    """Every projected participation edge, as (label, role).

    Two queries rather than one `UNION ALL`: AGE rejects the union with "column
    name 'label' specified more than once", and the point here is the edges, not
    the query.
    """
    found: list[tuple[str, str]] = []
    for label in ("WENT_THROUGH", "CAME_OUT_OF"):
        rows = age_engine.execute(graph, f"MATCH ()-[r:{label}]->() RETURN r.role as role", {})
        found.extend((label, str(row["role"])) for row in rows)
    return sorted(found)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_participation_is_projected_with_its_role(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    age_engine,
) -> None:
    """Both entities reach the event, on the right side, carrying their role."""
    source = await _cell(api_schema, simple_api_context, test_graph)
    target = await _cell(api_schema, simple_api_context, test_graph)
    await _mitosis(api_schema, simple_api_context, test_graph, source, target)

    @sync_to_async
    def edges() -> list[tuple[str, str]]:
        return _participations(age_engine, test_graph)

    assert await edges() == [("CAME_OUT_OF", "b"), ("WENT_THROUGH", "a")], "An input and an output edge, each naming the role the schema gave it"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_participation_is_evidence(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The claim is a row, keyed on durable refs, before it is ever an edge."""
    source = await _cell(api_schema, simple_api_context, test_graph)
    target = await _cell(api_schema, simple_api_context, test_graph)
    await _mitosis(api_schema, simple_api_context, test_graph, source, target)

    @sync_to_async
    def links() -> list[tuple[str, str, str]]:
        rows = evidence_models.Link.objects.for_organization(test_graph.organization).filter(kind__in=("participates_as_input", "participates_as_output"))
        return sorted((row.kind, str(row.role), str(row.source_ref)) for row in rows)

    recorded = await links()
    assert len(recorded) == 2, "Both participations must be recorded as evidence"
    assert [(kind, role) for kind, role, _ in recorded] == [("participates_as_input", "a"), ("participates_as_output", "b")]
    for _, _, source_ref in recorded:
        # A bare uuid, not an AGE vertex id and not a graph-prefixed composite.
        # `UUID()` raising is the assertion.
        uuid.UUID(source_ref)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_participation_survives_a_rebuild(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    age_engine,
) -> None:
    """The honesty test, for participation.

    Nothing about who took part in an event was replayable, because nothing about
    it was recorded — so a reproject silently returned a graph where every event
    had lost its participants.
    """
    source = await _cell(api_schema, simple_api_context, test_graph)
    target = await _cell(api_schema, simple_api_context, test_graph)
    await _mitosis(api_schema, simple_api_context, test_graph, source, target)

    @sync_to_async
    def drop_then_rebuild() -> dict:
        controller = GraphController(engine=age_engine)
        age_engine.drop_graph(test_graph.age_name, cascade=True)
        age_engine.create_graph(age_name=test_graph.age_name)
        return controller.rebuild_projection(test_graph)

    result = await drop_then_rebuild()
    assert result["participations"] == 2, "Both participations must be reconstructed from evidence.Link alone"

    @sync_to_async
    def edges() -> list[tuple[str, str]]:
        return _participations(age_engine, test_graph)

    assert await edges() == [("CAME_OUT_OF", "b"), ("WENT_THROUGH", "a")], "And be present in AGE afterwards, not merely counted"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_protocol_event_with_inputs_succeeds_and_is_recorded_as_one(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    age_engine,
) -> None:
    """Protocol events raised `AttributeError` mid-write and were mislabelled.

    `ProtocolEventCategory` defined neither role-name method, and the `Node` row
    hardcoded `NATURAL_EVENT` regardless of the category — so `Node.Kind
    .PROTOCOL_EVENT`, which exists, was never written by anything.
    """
    # Created directly rather than through `materialize`: `GraphExtensionsInput`
    # has no field for a protocol event, so a schema cannot declare one and this
    # path would otherwise be untestable — which is a large part of why it stayed
    # broken.
    @sync_to_async
    def a_protocol_category() -> core_models.ProtocolEventCategory:
        return core_models.ProtocolEventCategory.objects.create(
            graph=test_graph,
            age_name="Fixation",
            key="Fixation",
            label="Fixation",
            source_entity_roles=[{"key": "Cell", "role": "a"}],
            target_entity_roles=[],
        )

    category = await a_protocol_category()
    source = await _cell(api_schema, simple_api_context, test_graph)

    created = await api_schema.execute(
        """
        mutation CreateProtocolEvent($input: AssertProtocolEventExistsInput!) {
            assertProtocolEventExists(input: $input) { protocolEvent { id } }
        }
        """,
        variable_values={
            "input": {
                "term": category.key,
                "inputs": [{"role": "a", "entityId": source}],
                "outputs": [],
                "supportingEvidence": [],
            }
        },
        context_value=simple_api_context,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"

    @sync_to_async
    def participation_edges() -> list[str]:
        rows = age_engine.execute(test_graph, "MATCH ()-[r:SUBJECTED_IN]->() RETURN r.role as role", {})
        return [str(row["role"]) for row in rows]

    assert await participation_edges() == ["a"], "A protocol event takes the labels its own docstring describes, not a natural event's"

    @sync_to_async
    def kinds() -> list[str]:
        return list(evidence_models.Node.objects.for_organization(test_graph.organization).filter(term=category.term).values_list("kind", flat=True))

    assert await kinds() == ["protocol_event"], "A protocol event must be recorded as one"


ASSERT_PARTICIPATION = """
    mutation AssertParticipation($input: AssertParticipationInput!) {
        assertParticipation(input: $input) { participation { id } }
    }
"""

ARCHIVE_PARTICIPATION = """
    mutation ArchiveParticipation($input: RetractParticipationInput!) {
        retractParticipation(input: $input) { participation { id } }
    }
"""


def _assertion_count(age_engine, graph: core_models.Graph, label: str) -> list[int]:
    rows = age_engine.execute(graph, f"MATCH ()-[r:{label}]->() RETURN r.__assertion_count as c", {})
    return sorted(int(row["c"]) for row in rows)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_two_observers_can_claim_the_same_participation(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    age_engine,
) -> None:
    """Who took part is contestable, so agreement is countable.

    Two claims, one edge — the same shape relations already use. Before
    `assertParticipation` the only way to say anything about participants was
    `updateNaturalEvent`, which archived the event and made a new one, so a
    second opinion produced a second event.
    """
    source = await _cell(api_schema, simple_api_context, test_graph)
    target = await _cell(api_schema, simple_api_context, test_graph)
    event = await _mitosis(api_schema, simple_api_context, test_graph, source, target)

    again = await api_schema.execute(
        ASSERT_PARTICIPATION,
        variable_values={"input": {"event": event, "entity": source, "role": "a", "isInput": True}},
        context_value=simple_api_context,
    )
    assert again.errors is None, f"GraphQL errors: {again.errors}"

    @sync_to_async
    def state() -> tuple[int, list[tuple[str, str]], list[int]]:
        claims = evidence_models.Link.objects.for_organization(test_graph.organization).filter(kind=evidence_models.Link.Kind.PARTICIPATES_AS_INPUT)
        return claims.count(), _participations(age_engine, test_graph), _assertion_count(age_engine, test_graph, "WENT_THROUGH")

    claim_count, edges, counts = await state()

    assert claim_count == 2, "Both observers' claims are kept"
    assert edges == [("CAME_OUT_OF", "b"), ("WENT_THROUGH", "a")], "And collapse to one edge per participation"
    assert counts == [2], "The edge records how many live claims stand behind it"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_retracting_one_participation_claim_keeps_the_edge(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    age_engine,
) -> None:
    """One observer withdrawing does not undo the other's claim."""
    source = await _cell(api_schema, simple_api_context, test_graph)
    target = await _cell(api_schema, simple_api_context, test_graph)
    event = await _mitosis(api_schema, simple_api_context, test_graph, source, target)

    second = await api_schema.execute(
        ASSERT_PARTICIPATION,
        variable_values={"input": {"event": event, "entity": source, "role": "a", "isInput": True}},
        context_value=simple_api_context,
    )
    assert second.errors is None, f"GraphQL errors: {second.errors}"

    archived = await api_schema.execute(
        ARCHIVE_PARTICIPATION,
        variable_values={"input": {"id": second.data["assertParticipation"]["participation"]["id"]}},
        context_value=simple_api_context,
    )
    assert archived.errors is None, f"GraphQL errors: {archived.errors}"

    @sync_to_async
    def state() -> tuple[list[tuple[str, str]], list[int], int]:
        events = evidence_models.Claim.objects.for_organization(test_graph.organization).filter(target_type="link")
        return _participations(age_engine, test_graph), _assertion_count(age_engine, test_graph, "WENT_THROUGH"), events.count()

    edges, counts, lifecycle_rows = await state()

    assert edges == [("CAME_OUT_OF", "b"), ("WENT_THROUGH", "a")], "The surviving claim keeps the edge"
    assert counts == [1], "And the agreement count falls to it"
    assert lifecycle_rows == 1, "Retraction is a lifecycle row, never a delete"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_retracting_the_last_participation_claim_removes_the_edge(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    age_engine,
) -> None:
    """With no live claim the edge states nothing, and a replay must agree."""
    source = await _cell(api_schema, simple_api_context, test_graph)
    target = await _cell(api_schema, simple_api_context, test_graph)
    await _mitosis(api_schema, simple_api_context, test_graph, source, target)

    @sync_to_async
    def the_input_claim() -> str:
        return str(evidence_models.Link.objects.for_organization(test_graph.organization).get(kind=evidence_models.Link.Kind.PARTICIPATES_AS_INPUT).pk)

    claim_id = await the_input_claim()

    archived = await api_schema.execute(ARCHIVE_PARTICIPATION, variable_values={"input": {"id": claim_id}}, context_value=simple_api_context)
    assert archived.errors is None, f"GraphQL errors: {archived.errors}"

    @sync_to_async
    def after() -> list[tuple[str, str]]:
        return _participations(age_engine, test_graph)

    assert await after() == [("CAME_OUT_OF", "b")], "The retracted input participation is gone; the output one stands"

    @sync_to_async
    def rebuild() -> tuple[dict, list[tuple[str, str]]]:
        result = GraphController(engine=age_engine).rebuild_projection(test_graph)
        return result, _participations(age_engine, test_graph)

    result, edges = await rebuild()
    assert result["participations"] == 1, "A replay must not resurrect a retracted participation"
    assert edges == [("CAME_OUT_OF", "b")]


ASSERT_PARTICIPATION = """
    mutation AssertParticipation($input: AssertParticipationInput!) {
        assertParticipation(input: $input) {
            participation { __typename id }
            drawings { graph { id } category { id } edge { __typename id } }
        }
    }
"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("is_input", [True, False], ids=["input", "output"])
async def test_a_participation_reports_the_view_that_drew_it(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    age_engine,
    is_input: bool,
) -> None:
    """Both sides of a participation must be findable, and this is the test that says so.

    **The failure this exists to catch is silent.** Reading a drawing back asks
    AGE for the edge, and the reader used to build that pattern itself, wrongly
    in two ways at once:

    - it matched `[r:{category.age_name}]`, but a participation's label is not the
      category's `age_name` — it is `AGE_INPUT_EDGE` / `AGE_OUTPUT_EDGE` off the
      *event's* category;
    - it matched `(source)-[r]->(target)`, but `participation_key` stores the
      entity as source and the event as target on **both** sides, while an output
      participation is drawn event → entity.

    Neither mistake raises. `MATCH` simply finds nothing, `drawings` comes back
    empty, and empty is a legitimate answer everywhere else — so without
    parametrising over both directions this would pass while output
    participations were permanently invisible. `projector.edge_pattern_for` is
    now the single source of the label and the direction, shared with the writer.
    """
    entity = await _cell(api_schema, simple_api_context, test_graph)
    other = await _cell(api_schema, simple_api_context, test_graph)
    event = await _mitosis(api_schema, simple_api_context, test_graph, other, other)

    result = await api_schema.execute(
        ASSERT_PARTICIPATION,
        variable_values={"input": {"event": event, "entity": entity, "role": "extra", "isInput": is_input}},
        context_value=simple_api_context,
    )

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    payload = result.data["assertParticipation"]

    assert payload["participation"]["id"], "The claim has an identity"

    # `__typename`, not just `id`. `id` lives on the `Edge` interface, so it
    # resolves whatever concrete type the dispatch picked — which is how this
    # test could pass while every participation came back as a `Relation`. The
    # label a participation edge carries is the *event category's* `age_name`
    # ("Mitosis"), so nothing readable from the label could ever have said
    # "participation"; the kind comes off the `Link` row instead.
    expected = "InputParticipation" if is_input else "OutputParticipation"
    assert payload["participation"]["__typename"] == expected, f"A participation must be typed by the side it names, got {payload['participation']['__typename']}"

    assert payload["drawings"], f"The graph draws this participation, so the result must say so (isInput={is_input})"
    assert payload["drawings"][0]["graph"]["id"] == str(test_graph.id)
    assert payload["drawings"][0]["category"]["id"], "and name the category it was drawn under"
    assert payload["drawings"][0]["edge"]["__typename"] == expected, "and the drawing agrees about what it drew"
