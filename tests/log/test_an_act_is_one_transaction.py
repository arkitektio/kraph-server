"""A set of claims made in one act is one assertion.

Not an ergonomic point. An `Assertion` records *who claimed something, with which
tool, when*, so a batch asserted together genuinely is one assertion — which is
what `create_entity` has always done internally, minting one and reusing it
across every structure, metric and link it writes.

Doing the same work through N sequential calls records the same act as N
assertions, and nothing can put them back together: `Assertion.action_id`, the
field that would tie them, is never populated by any write path. That is the
difference these tests measure.
"""

from __future__ import annotations
import kante
import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext
from core import models as core_models
from evidence import models as evidence_models
import asyncio
import contextlib
from typing import Any, AsyncIterator
from authentikate.models import Client
from channels.layers import get_channel_layer
from django.db import transaction
from kante.testing import build_ws_context
from evidence import channel, writer
from graph_engine.controller import GraphController
from graph_engine.input_models import ProvenanceContext
from tests.support.identity import static_identity as _static_identity
import datetime
from tests.support import writes
from evidence import identity
from tests.support.writes import ASSERT_SAME, assert_entity as _assert_entity
from tests.support import drawing


CREATE_ENTITY = """
    mutation CreateEntity($input: AssertEntityExistsInput!) {
        assertEntityExists(input: $input) { instance { id } }
    }
"""
CREATE_NATURAL_EVENT = """
    mutation CreateNaturalEvent($input: AssertNaturalEventExistsInput!) {
        assertNaturalEventExists(input: $input) { instance { id } }
    }
"""
ASSERT_PARTICIPATION = """
    mutation AssertParticipation($input: AssertParticipationInput!) {
        assertParticipation(input: $input) { link { id } }
    }
"""
ASSERT_PARTICIPATIONS = """
    mutation AssertParticipations($input: AssertParticipationsInput!) {
        assertParticipations(input: $input) { assertion { id } links { kind id } }
    }
"""
CLASSIFY_NODES = """
    mutation ClassifyNodes($input: ClassifyNodesInput!) {
        classifyNodes(input: $input) { assertion { id } instances { kind id } }
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
    return created.data["assertEntityExists"]["instance"]["id"]


async def _mitosis(api_schema: kante.Schema, ctx: HttpContext, graph: core_models.Graph) -> str:
    category = await core_models.NaturalEventCategory.objects.filter(graph=graph, key="Mitosis").afirst()
    assert category is not None
    created = await api_schema.execute(
        CREATE_NATURAL_EVENT,
        variable_values={"input": {"term": category.key, "inputs": [], "outputs": [], "supportingEvidence": []}},
        context_value=ctx,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    return created.data["assertNaturalEventExists"]["instance"]["id"]


@sync_to_async
def _assertion_count(graph: core_models.Graph) -> int:
    return evidence_models.Assertion.objects.for_organization(graph.organization).count()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_batch_of_participations_is_one_assertion(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Three participants asserted together are one act, so one assertion."""
    event = await _mitosis(api_schema, simple_api_context, test_graph)
    entities = [await _cell(api_schema, simple_api_context, test_graph) for _ in range(3)]

    before = await _assertion_count(test_graph)

    result = await api_schema.execute(
        ASSERT_PARTICIPATIONS,
        variable_values={
            "input": {
                "event": event,
                "participants": [{"entity": entity, "role": f"r{index}", "isInput": True} for index, entity in enumerate(entities)],
            }
        },
        context_value=simple_api_context,
    )
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    payload = result.data["assertParticipations"]
    assert len(payload["links"]) == 3

    # `kind`, which is the column the claim carries. It used to be `__typename` over a
    # polymorphic payload of drawing types, and the dispatch behind it read an edge
    # *label* — which for a participation is the event category's name and says nothing
    # about which side of the event it is.
    assert {link["kind"] for link in payload["links"]} == {"PARTICIPATES_AS_INPUT"}
    assert payload["assertion"]["id"], "One act, one assertion, and it is addressable"

    after = await _assertion_count(test_graph)
    assert after - before == 1, "One act, one assertion"

    @sync_to_async
    def links_share_it() -> int:
        links = evidence_models.Link.objects.for_organization(test_graph.organization).filter(kind=evidence_models.Link.Kind.PARTICIPATES_AS_INPUT)
        return len({link.assertion_id for link in links})

    assert await links_share_it() == 1, "And every claim in the batch points at it"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_same_work_one_at_a_time_is_three_assertions(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The contrast that makes the batch form worth having.

    Same three claims, same actor, same moment — but recorded as three separate
    acts, and no field ties them back together.
    """
    event = await _mitosis(api_schema, simple_api_context, test_graph)
    entities = [await _cell(api_schema, simple_api_context, test_graph) for _ in range(3)]

    before = await _assertion_count(test_graph)

    for index, entity in enumerate(entities):
        one = await api_schema.execute(
            ASSERT_PARTICIPATION,
            variable_values={"input": {"event": event, "entity": entity, "role": f"r{index}", "isInput": True}},
            context_value=simple_api_context,
        )
        assert one.errors is None, f"GraphQL errors: {one.errors}"

    after = await _assertion_count(test_graph)
    assert after - before == 3, "Three calls fragment one act into three assertions"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_bad_id_in_the_batch_writes_nothing(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """A batch is all-or-nothing, so half of it can never commit.

    The guarantee is the `transaction.atomic()` around the writes: removing it
    lets the assertion and the valid claim survive a batch that failed, and this
    test fails. Resolving every reference *before* the transaction is defensive
    on top of that — it fails earlier and does no AGE work first — but it is not
    what makes the batch atomic, and this test passes without it.
    """
    event = await _mitosis(api_schema, simple_api_context, test_graph)
    good = await _cell(api_schema, simple_api_context, test_graph)

    before = await _assertion_count(test_graph)

    @sync_to_async
    def link_count() -> int:
        return evidence_models.Link.objects.for_organization(test_graph.organization).filter(kind=evidence_models.Link.Kind.PARTICIPATES_AS_INPUT).count()

    links_before = await link_count()

    result = await api_schema.execute(
        ASSERT_PARTICIPATIONS,
        variable_values={
            "input": {
                "event": event,
                "participants": [
                    {"entity": good, "role": "a", "isInput": True},
                    {"entity": f"{test_graph.age_name}-999999999", "role": "b", "isInput": True},
                ],
            }
        },
        context_value=simple_api_context,
    )

    assert result.errors is not None, "A batch naming an entity that does not exist must fail"
    assert await _assertion_count(test_graph) == before, "And must not have minted an assertion"
    assert await link_count() == links_before, "Nor written the half of the batch that was valid"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_classifying_several_nodes_is_one_assertion(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Classification is additive and batchable, and was not reachable at all.

    `GraphController.classify` existed with zero callers — no resolver, no test —
    so the only way to say "this is actually a Soma" was `updateEntity`, which
    archived the node and minted a new uuid.
    """
    entities = [await _cell(api_schema, simple_api_context, test_graph) for _ in range(2)]

    @sync_to_async
    def soma_id() -> str:
        return str(core_models.EntityCategory.objects.get(graph=test_graph, key="Soma").pk)

    soma = await soma_id()
    before = await _assertion_count(test_graph)

    result = await api_schema.execute(
        CLASSIFY_NODES,
        variable_values={"input": {"classifications": [{"node": entity, "term": "Soma"} for entity in entities]}},
        context_value=simple_api_context,
    )
    assert result.errors is None, f"GraphQL errors: {result.errors}"

    assert await _assertion_count(test_graph) - before == 1, "One act, one assertion"

    @sync_to_async
    def claims() -> tuple[int, int]:
        # A classification names the organization's *word*, and the mutation now
        # says so: it takes the word, not a graph's category for it. The claim can
        # be read by any view declaring the same word, which is why binding it to
        # one view's row was wrong in the first place.
        term_id = core_models.Category.objects.get(pk=soma).term_id
        rows = evidence_models.Link.objects.for_organization(test_graph.organization).filter(kind=evidence_models.Link.Kind.CLASSIFIES, target_ref=str(term_id))
        nodes = evidence_models.Instance.objects.for_organization(test_graph.organization).count()
        return rows.count(), nodes

    claim_count, node_count = await claims()
    assert claim_count == 2, "Both claims recorded"
    assert node_count == 2, "And neither node was forked to carry one"


RETRACT_CLAIMS = """
    mutation RetractClaims($input: RetractLinksInput!) {
        retractLinks(input: $input) { assertion { id } links { kind id } }
    }
"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_retracting_claims_reports_them_as_one_act(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """One assertion covers the batch, and each claim comes back typed by its kind.

    `retractLinks` accepts `CLASSIFIES`, `RELATION`, `PARTICIPATES_*` and
    `INFORMS` links alike, and used to report every one of them as a
    `Measurement`. The dispatch reads the `Link` row's kind now.

    **`CLASSIFIES` used to be asserted as `Relation`, and this test said so on
    purpose** — there was no GraphQL type for a classification claim, so the cast
    picked the least wrong of the ones that existed, and pinning the substitution
    meant it could not drift on unnoticed. `Classification` exists now, so this
    failed and pointed at the decision, which is what the tripwire was for.
    """
    entity = await _cell(api_schema, simple_api_context, test_graph)

    @sync_to_async
    def classification_id() -> str:
        link = evidence_models.Link.objects.for_organization(test_graph.organization).filter(kind=evidence_models.Link.Kind.CLASSIFIES, source_ref=entity).first()
        assert link is not None, "Asserting an entity writes a CLASSIFIES claim"
        return str(link.pk)

    claim_id = await classification_id()

    result = await api_schema.execute(
        RETRACT_CLAIMS,
        variable_values={"input": {"ids": [claim_id]}},
        context_value=simple_api_context,
    )

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    payload = result.data["retractLinks"]

    assert payload["assertion"]["id"], "Retracting is itself a claim, and the batch is one act"
    assert len(payload["links"]) == 1
    assert payload["links"][0]["id"] == claim_id
    assert payload["links"][0]["kind"] == "CLASSIFIES", "A classification claim is its own kind of thing — it runs node → word, not node → node"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_retracting_nothing_is_refused(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """An empty batch has no assertion to report, so it is not an act.

    It used to answer with an empty list. The result is the assertion this call
    made, and a call that retracts nothing makes none — minting one would put a
    row in the log for something that did not happen.
    """
    result = await api_schema.execute(
        RETRACT_CLAIMS,
        variable_values={"input": {"ids": []}},
        context_value=simple_api_context,
    )

    assert result.errors, "Retracting an empty set must be refused rather than answered"


SUBSCRIPTION = """
    subscription AssertionRecorded {
        assertionRecorded { id seq subject instances { id } }
    }
"""
ASSERT_ENTITY = """
    mutation AssertEntityExists($input: AssertEntityExistsInput!) {
        assertEntityExists(input: $input) { assertion { id seq } instance { id } }
    }
"""


class _StubConsumer:
    """The three things `Channel.listen` reads off a consumer."""

    def __init__(self) -> None:
        self.channel_layer = get_channel_layer()
        self.channel_name = ""

    async def open(self) -> None:
        self.channel_name = await self.channel_layer.new_channel()

    @contextlib.asynccontextmanager
    async def listen_to_channel(self, type: str, *, timeout: float | None = None, groups: Any = ()) -> AsyncIterator[Any]:
        for group in groups:
            await self.channel_layer.group_add(group, self.channel_name)

        async def messages() -> Any:
            while True:
                message = await self.channel_layer.receive(self.channel_name)
                if message.get("type") == type:
                    yield message

        try:
            yield messages()
        finally:
            for group in groups:
                await self.channel_layer.group_discard(group, self.channel_name)


async def _subscribe(api_schema, organization=None):
    """Open the subscription in its own task and hand back what it receives.

    One task drives the generator from start to close: strawberry's extensions
    set contextvars on entry and reset them on exit, and a token reset from a
    different task than the one that set it is an error. Returns once the room
    is registered on the layer, so a write made right after is heard.
    """
    user, org, membership = await sync_to_async(_static_identity)()
    client, _ = await Client.objects.aget_or_create(client_id="oinsoins")
    consumer = _StubConsumer()
    await consumer.open()
    ctx = build_ws_context(consumer=consumer, user=user, organization=organization or org, client=client, membership=membership, token="test", connection_params={"token": "test"})
    received: asyncio.Queue[Any] = asyncio.Queue()

    async def run() -> None:
        stream = await api_schema.subscribe(SUBSCRIPTION, context_value=ctx)
        if not hasattr(stream, "__anext__"):
            await received.put(stream)
            return
        async for result in stream:
            await received.put(result)

    task = asyncio.create_task(run())
    room = channel.room(organization or org)
    for _ in range(200):
        await asyncio.sleep(0.01)
        if task.done() or room in getattr(consumer.channel_layer, "groups", {}):
            break
    if task.done():
        raise AssertionError(f"subscription did not start: {task.exception() or received.get_nowait()}")
    return task, received


async def _close(task: asyncio.Task) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_committed_write_is_announced(api_schema, simple_api_context, test_graph) -> None:
    task, received = await _subscribe(api_schema)
    try:
        result = await api_schema.execute(ASSERT_ENTITY, variable_values={"input": {"term": "AIS", "supportingEvidence": []}}, context_value=simple_api_context)
        assert result.errors is None, f"GraphQL errors: {result.errors}"
        written = result.data["assertEntityExists"]

        announced = await asyncio.wait_for(received.get(), timeout=5)
        assert announced.errors is None, f"GraphQL errors: {announced.errors}"
        act = announced.data["assertionRecorded"]
        assert act["id"] == written["assertion"]["id"]
        assert act["seq"] == written["assertion"]["seq"]
        assert [row["id"] for row in act["instances"]] == [written["instance"]["id"]], "the announced row is the full act, claims and all"
    finally:
        await _close(task)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_rolled_back_write_is_not_announced(api_schema, simple_api_context, test_graph) -> None:
    """The broadcast is on commit. An assertion recorded inside a transaction that
    then fails was never part of the log, and nobody hears about it."""
    organization = simple_api_context.request._organization
    before = await evidence_models.Assertion.all_objects.acount()
    task, received = await _subscribe(api_schema)
    try:

        def write_then_fail() -> None:
            controller = GraphController()
            with pytest.raises(RuntimeError):
                with transaction.atomic():
                    controller._create_assertion(organization, ProvenanceContext(subject="1", app_id="test"))
                    raise RuntimeError("something after the assertion failed")

        await sync_to_async(write_then_fail)()
        assert await evidence_models.Assertion.all_objects.acount() == before

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(received.get(), timeout=1)
    finally:
        await _close(task)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_act_whose_claims_fail_is_not_recorded(api_schema, simple_api_context, test_graph, monkeypatch) -> None:
    """The act is one transaction. A failure while writing the claims takes the
    assertion and its outbox row with it: the log never held an act that said
    nothing, and nobody hears about it."""
    from graph_engine import models as projection_models

    before = await evidence_models.Assertion.all_objects.acount()
    pending_before = await projection_models.PendingProjection.objects.acount()

    def refuse(*args, **kwargs):
        raise RuntimeError("the claim could not be written")

    monkeypatch.setattr(writer, "create_instance", refuse)
    task, received = await _subscribe(api_schema)
    try:
        result = await api_schema.execute(ASSERT_ENTITY, variable_values={"input": {"term": "AIS"}}, context_value=simple_api_context)
        assert result.errors, "the write fails"

        assert await evidence_models.Assertion.all_objects.acount() == before, "no act was recorded"
        assert await projection_models.PendingProjection.objects.acount() == pending_before, "and nothing is owed to the projection"

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(received.get(), timeout=1)
    finally:
        await _close(task)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_another_tenants_write_is_not_heard(api_schema, simple_api_context, test_graph, other_organization) -> None:  # noqa: F811
    task, received = await _subscribe(api_schema)
    try:

        def foreign_write() -> None:
            with transaction.atomic():
                assertion = writer.create_assertion(other_organization, subject="stranger", app_id="test")
                channel.announce(assertion)

        await sync_to_async(foreign_write)()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(received.get(), timeout=1)
    finally:
        await _close(task)


class _Actor:
    """The executing agent half of a token — `act` in the claim set."""

    def __init__(self) -> None:
        self.sub = "agent-user-sub"
        self.cid = "agent-client-id"


class _Token:
    """A verified provenance token, shaped as `kante.context.Provenance`.

    Hand-built rather than minted and signed: what is under test is that the
    claims reach the assertion, not that `authentikate` verifies a signature —
    which it has its own tests for, and which needs a running Rekuest to produce.
    """

    def __init__(self) -> None:
        self.iss = "rekuest"
        self.aud = ["kraph"]
        self.sub = "caller-sub"
        self.act = _Actor()
        self.iat = datetime.datetime(2026, 8, 14, tzinfo=datetime.timezone.utc)
        self.exp = datetime.datetime(2026, 8, 15, tzinfo=datetime.timezone.utc)
        self.jti = "token-id-once"
        self.tsk = "assignation-42"
        self.ptk = "assignation-41"
        self.rtk = "assignation-1"
        self.rcb = "the-human-who-asked"
        self.ahs = "sha256-of-the-canonical-args"
        self.aha = "canonical/v1"
        self.raw = "eyJ0aGlzIjoiaXMgYSBjcmVkZW50aWFsIn0"


@pytest.fixture
def provenanced_context(simple_api_context: HttpContext) -> HttpContext:
    """The ordinary test context, plus the token an assigned action would carry."""
    token = _Token()
    simple_api_context.request.set_provenance(token)  # type: ignore[arg-type]
    simple_api_context.request.set_extension("provenance", token)
    return simple_api_context


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_unprovenanced_write_still_records_a_claim(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """A human at a keyboard is not running an action, and must not be refused.

    The provenance path fails open on purpose. Requiring an assignation id would
    refuse a fact about the world on a bookkeeping technicality — the same
    argument `writer.ensure_term` makes about words no graph has declared.
    """
    entity_id = await writes.create_entity(api_schema, simple_api_context, "Cell")

    @sync_to_async
    def assertion_for() -> evidence_models.Assertion:
        node = evidence_models.Instance.objects.for_organization(test_graph.organization).select_related("assertion").get(pk=entity_id)
        return node.assertion

    assertion = await assertion_for()
    assert assertion.subject, "Who claimed it is always recorded"
    assert assertion.action_id is None, "There was no run, so there is no run to name"
    assert assertion.action_args == {}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_provenanced_write_records_the_run(
    api_schema: kante.Schema,
    provenanced_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The token's claims reach the assertion, without `KoherentExtension`.

    `action_id` is the assignation — "which run produced this" — and the args hash
    is kept beside it so the inputs can be recomputed and checked years later,
    which is the point of storing it on the claim rather than in a log line.
    """
    entity_id = await writes.create_entity(api_schema, provenanced_context, "Cell")

    @sync_to_async
    def assertion_for() -> evidence_models.Assertion:
        node = evidence_models.Instance.objects.for_organization(test_graph.organization).select_related("assertion").get(pk=entity_id)
        return node.assertion

    assertion = await assertion_for()

    assert assertion.action_id == "assignation-42", "The assignation is what identifies the run"
    assert assertion.action_args["args_hash"] == "sha256-of-the-canonical-args"
    assert assertion.action_args["args_hash_algorithm"] == "canonical/v1"

    # The causal chain, so "who ultimately asked for this" is answerable from the
    # assertion alone rather than by walking somebody else's task table.
    assert assertion.action_args["root_task"] == "assignation-1"
    assert assertion.action_args["parent_task"] == "assignation-41"
    assert assertion.action_args["assigner"] == "the-human-who-asked"
    assert assertion.action_args["agent"] == "agent-user-sub"
    assert assertion.action_args["agent_client_id"] == "agent-client-id"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_raw_token_is_never_stored(
    api_schema: kante.Schema,
    provenanced_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """It is a single-use credential, and an assertion outlives every use for one."""
    entity_id = await writes.create_entity(api_schema, provenanced_context, "Cell")

    @sync_to_async
    def stored() -> str:
        node = evidence_models.Instance.objects.for_organization(test_graph.organization).select_related("assertion").get(pk=entity_id)
        return repr(node.assertion.action_args)

    assert "eyJ0aGlzIjoiaXMgYSBjcmVkZW50aWFsIn0" not in await stored(), "The raw token must not be persisted"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_selector_can_filter_by_the_run(
    api_schema: kante.Schema,
    provenanced_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """What populating `action_id` buys: "count only what this analysis produced".

    Note the condition that is still dead. An `ACTION` condition has no
    source — a provenance token attests causation and carries no human-readable
    name for the action, and neither does `koherent.Task`, which is built from the
    same claims. Filtering by run means filtering on `action_id`.
    """
    await writes.create_entity(api_schema, provenanced_context, "Cell")

    @sync_to_async
    def counts() -> tuple[int, int]:
        assertions = evidence_models.Assertion.objects.for_organization(test_graph.organization)
        return (
            assertions.filter(action_id="assignation-42").count(),
            assertions.filter(action_name__isnull=False).count(),
        )

    by_run, named = await counts()
    assert by_run >= 1, "Evidence is attributable to the run that produced it"
    assert named == 0, "And nothing carries an action name, because nothing supplies one"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_this_is_ais_6_is_one_act(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """One call, one assertion, and the two instances end up one thing.

    The assertion is the unit of authorship — a set of claims made together by one
    actor is one assertion — and `Assertion.action_id`, the field that would tie
    two separate calls back together, is never populated. So if the sameness claim
    were a second call it could never be reassembled with the instance it belongs
    to.
    """
    established = await _assert_entity(api_schema, simple_api_context, "AIS")

    observed = await _assert_entity(api_schema, simple_api_context, "AIS", same_as=[established["instance"]["id"]])

    assert observed["instance"]["id"] != established["instance"]["id"], "The observation mints its own instance rather than reusing one"

    @sync_to_async
    def claims_under(assertion_id: str) -> dict[str, int]:
        links = evidence_models.Link.all_objects.filter(assertion_id=assertion_id)
        counted: dict[str, int] = {}
        for link in links:
            counted[str(link.kind)] = counted.get(str(link.kind), 0) + 1
        return counted

    counted = await claims_under(observed["assertion"]["id"])
    assert counted.get("classifies") == 1, "The instance is classified under the word"
    assert counted.get("same_as") == 1, "and claimed the same as the one already known — under the same assertion"

    @sync_to_async
    def component() -> list[str]:
        organization = test_graph.organization
        return identity.component_refs(organization, [observed["instance"]["id"]])[observed["instance"]["id"]]

    assert sorted(await component()) == sorted([observed["instance"]["id"], established["instance"]["id"]])


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_three_instances_claimed_together_are_one_assertion(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """ "These are all the same cell" is one statement, so it is one assertion.

    Recorded pairwise rather than star-shaped around the first id, because
    sameness has no primary — making the first argument the hub would let identity
    depend on argument order.
    """
    entities = [(await _assert_entity(api_schema, simple_api_context, "AIS"))["instance"]["id"] for _ in range(3)]

    result = await api_schema.execute(
        ASSERT_SAME,
        variable_values={"input": {"instances": entities}},
        context_value=simple_api_context,
    )
    assert result.errors is None, f"GraphQL errors: {result.errors}"

    assert len({claim["id"] for claim in result.data["assertSameInstance"]["links"]}) == 2, "n instances need n-1 claims to connect"

    @sync_to_async
    def component() -> list[str]:
        return identity.component_refs(test_graph.organization, [entities[0]])[entities[0]]

    assert sorted(await component()) == sorted(entities)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_protocol_event_with_inputs_succeeds_and_is_recorded_as_one(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
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
            assertProtocolEventExists(input: $input) { instance { id } }
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
        return [str(role) for role in drawing.edge_property_values(test_graph, "SUBJECTED_IN", "role")]

    assert await participation_edges() == ["a"], "A protocol event takes the labels its own docstring describes, not a natural event's"

    @sync_to_async
    def kinds() -> list[str]:
        return list(evidence_models.Instance.objects.for_organization(test_graph.organization).filter(term=category.term).values_list("kind", flat=True))

    assert await kinds() == ["protocol_event"], "A protocol event must be recorded as one"
