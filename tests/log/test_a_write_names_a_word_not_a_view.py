"""A write names a word; a view may or may not draw it (A4, A6).

A claim can be made under a word no view declares; it is recorded; and it
appears in a view the moment one declares the word and asks for the history.
Tenancy is the organization, never the graph.

History: the write API used to require some graph's category for the word,
which the controller reduced to that category's term before writing anything.
"""

import uuid
import kante
import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext
from core import models as core_models
from evidence import models as evidence_models
from tests.support import writes


WRITE_INPUTS = [
    "AssertEntityExistsInput",
    "AssertNaturalEventExistsInput",
    "AssertProtocolEventExistsInput",
    "AssertRelationExistsInput",
    "AssertMeasurementExistsInput",
    "AssertStructureRelationExistsInput",
    "ClassificationInput",
]
@pytest.mark.parametrize("type_name", WRITE_INPUTS)
def test_no_write_input_names_a_category(api_schema: kante.Schema, type_name: str) -> None:
    """The SDL itself, so a category cannot come back by accident.

    Every one of these took a graph-scoped `*Category` id. A schema assertion is
    the cheap guard: a resolver that starts resolving categories again has to change
    an input to do it. Same shape as `test_graphless_ingest`, for the same reason.
    """
    fields = api_schema._schema.type_map[type_name].fields

    assert "term" in fields, f"{type_name} must name the organization's word"
    for leaked in ("category", "entityCategory", "eventCategory", "graph"):
        assert leaked not in fields, f"{type_name} still names a view through `{leaked}`"
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_claim_under_a_word_no_view_declares_is_recorded(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The headline: a fact does not need a view to exist before it can be stated.

    This used to be an error. `create_entity` ended by reading the entity back out
    of the graph the caller had named and raising "no category in {age_name} admits
    it" when that graph drew nothing — after the `Node` row and the `CLASSIFIES`
    claim had already been committed. The claim was durable and the caller was told
    it had failed.
    """
    word = f"Ephemeral_{uuid.uuid4().hex[:8]}"

    entity_id = await writes.create_entity(api_schema, simple_api_context, word)
    assert entity_id, "The claim is accepted and has an identity"

    @sync_to_async
    def recorded() -> tuple[int, int, int]:
        organization = test_graph.organization
        nodes = evidence_models.Instance.objects.for_organization(organization).filter(pk=entity_id).count()
        terms = evidence_models.Term.objects.for_organization(organization).filter(kind="ENTITY", key=word).count()
        categories = core_models.Category.objects.filter(term__key=word).count()
        return nodes, terms, categories

    nodes, terms, categories = await recorded()
    assert nodes == 1, "The node is in the log"
    assert terms == 1, "And the word was minted for the organization, as structure kinds are"
    assert categories == 0, "But no view has a rule for it, which is the state under test"
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_classifying_an_event_claims_an_event_word(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The word's kind comes from the node, not from the caller.

    `Term`'s identity is `(organization, kind, key)`, so "Mitosis" as an event and
    "Mitosis" as an entity are two words. If a client could state the kind, it could
    claim an `ENTITY` word about an event — a `CLASSIFIES` link no category is ever
    keyed on, so a write that succeeds and is readable by nothing.
    """
    event_id = await writes.create_event(api_schema, simple_api_context, "Mitosis")
    word = f"Division_{uuid.uuid4().hex[:8]}"

    classified = await api_schema.execute(
        """
        mutation ClassifyNodes($input: ClassifyNodesInput!) {
            classifyNodes(input: $input) { instances { kind id } }
        }
        """,
        variable_values={"input": {"classifications": [{"node": event_id, "term": word}]}},
        context_value=simple_api_context,
    )
    assert classified.errors is None, f"GraphQL errors: {classified.errors}"

    @sync_to_async
    def minted_kinds() -> list[str]:
        return list(evidence_models.Term.objects.for_organization(test_graph.organization).filter(key=word).values_list("kind", flat=True))

    assert await minted_kinds() == ["NATURAL_EVENT"], "The kind follows the node it is claimed about"

    # And the payload agrees. `classifyNodes` used to wrap every classified node in
    # `Entity` regardless of what it was, so classifying an event reported it as an
    # entity — visible only if you asked for `__typename`, since `id` is on the `Node`
    # interface and resolves either way. The claim carries its own `kind` now, so the
    # question needs no type name to ask.
    assert classified.data["classifyNodes"]["instances"][0]["kind"] == "NATURAL_EVENT", "A classified event comes back as an event"
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_edge_under_an_undeclared_word_is_recorded_too(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Not only nodes. A relation names a word on the same terms.

    Worth its own test because the edge path returns through `from_link` and
    `_category_for_term`, not through `node_result`, so "no view declares this"
    reaches the client down a different route — as a null `category` on an edge
    that has no projection anywhere.
    """
    word = f"ADJACENT_TO_{uuid.uuid4().hex[:8]}"
    source = await writes.create_entity(api_schema, simple_api_context, "Cell")
    target = await writes.create_entity(api_schema, simple_api_context, "Cell")

    relation_id = await writes.create_relation(api_schema, simple_api_context, word, source, target)

    @sync_to_async
    def recorded() -> tuple[int, int]:
        organization = test_graph.organization
        links = evidence_models.Link.objects.for_organization(organization).filter(pk=relation_id).count()
        categories = core_models.Category.objects.filter(term__key=word).count()
        return links, categories

    links, categories = await recorded()
    assert links == 1, "The relation claim is in the log"
    assert categories == 0, "Under a word no view has a rule for"
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_attesting_a_node_no_view_draws_does_not_fail(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The path the change opened: create under an undeclared word, archive, attest.

    `attest*` returned `projected_instance`, which raises when every view declaring the
    node's word refused it. That was unreachable while a write had to name a
    category some graph owned. It is routine now, and raising would report a failure
    for a `Standing(stands=True)` that was durably written a moment earlier — the same
    defect this change removed from `createEntity`.
    """
    word = f"Unseen_{uuid.uuid4().hex[:8]}"
    entity_id = await writes.create_entity(api_schema, simple_api_context, word)

    archived = await api_schema.execute(
        "mutation Archive($input: RetractEntityInput!) { retractEntity(input: $input) { instance { id } } }",
        variable_values={"input": {"id": entity_id}},
        context_value=simple_api_context,
    )
    assert archived.errors is None, f"GraphQL errors: {archived.errors}"

    attested = await api_schema.execute(
        "mutation Attest($input: AttestEntityInput!) { attestEntity(input: $input) { instance { id } } }",
        variable_values={"input": {"id": entity_id}},
        context_value=simple_api_context,
    )
    assert attested.errors is None, f"GraphQL errors: {attested.errors}"
    assert attested.data["attestEntity"]["instance"]["id"] == entity_id, "The node comes back as the log has it"
