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

import uuid

import kante
import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext

from core import models as core_models
from evidence import models as evidence_models

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

ASSERT_PARTICIPATION = """
    mutation AssertParticipation($input: AssertParticipationInput!) {
        assertParticipation(input: $input) { participation { id } }
    }
"""

ASSERT_PARTICIPATIONS = """
    mutation AssertParticipations($input: AssertParticipationsInput!) {
        assertParticipations(input: $input) { assertion { id } edges { __typename id } }
    }
"""

CLASSIFY_NODES = """
    mutation ClassifyNodes($input: ClassifyNodesInput!) {
        classifyNodes(input: $input) { assertion { id } nodes { __typename id } }
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


async def _mitosis(api_schema: kante.Schema, ctx: HttpContext, graph: core_models.Graph) -> str:
    category = await core_models.NaturalEventCategory.objects.filter(graph=graph, key="Mitosis").afirst()
    assert category is not None
    created = await api_schema.execute(
        CREATE_NATURAL_EVENT,
        variable_values={"input": {"term": category.key, "inputs": [], "outputs": [], "supportingEvidence": []}},
        context_value=ctx,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    return created.data["assertNaturalEventExists"]["naturalEvent"]["id"]


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
    assert len(payload["edges"]) == 3

    # `__typename`, because the payload is polymorphic and `id` alone resolves
    # whatever type the dispatch picked. These are all inputs, so all of them must
    # come back as inputs — the kind is read off the `Link` row, since a
    # participation edge's label is the *event category's* name.
    assert {edge["__typename"] for edge in payload["edges"]} == {"InputParticipation"}
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
        nodes = evidence_models.Node.objects.for_organization(test_graph.organization).count()
        return rows.count(), nodes

    claim_count, node_count = await claims()
    assert claim_count == 2, "Both claims recorded"
    assert node_count == 2, "And neither node was forked to carry one"


RETRACT_CLAIMS = """
    mutation RetractClaims($input: RetractClaimsInput!) {
        retractClaims(input: $input) { assertion { id } edges { __typename id } }
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

    `retractClaims` accepts `CLASSIFIES`, `RELATION`, `PARTICIPATES_*` and
    `INFORMS` links alike, and used to report every one of them as a
    `Measurement`. The dispatch reads the `Link` row's kind now.

    **`CLASSIFIES` is asserted as `Relation` on purpose, and that is the wrong
    answer.** There is no GraphQL type for a classification claim, so the cast
    picks the least wrong of the types that exist. Pinning it here means the day
    somebody adds a proper type, this test fails and points at the decision
    instead of letting the substitution drift on unnoticed.
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
    payload = result.data["retractClaims"]

    assert payload["assertion"]["id"], "Retracting is itself a claim, and the batch is one act"
    assert len(payload["edges"]) == 1
    assert payload["edges"][0]["id"] == claim_id
    assert payload["edges"][0]["__typename"] == "Relation", "No type exists for a classification claim yet; see cast_edge_to_graphql_type"


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
