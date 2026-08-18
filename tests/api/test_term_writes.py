"""A write names a word; a graph is a view that may or may not draw it.

`docs/LOG.md`'s second axiom is that tenancy is the organization and never the
graph. The evidence layer honoured that from the start — nothing in `evidence/`
carries a graph foreign key, and membership is computed by
`evidence.selector.instances_for` rather than stored — but the write API did not: to
claim "there is an AIS here" you had to name some graph's `EntityCategory` for the
word "AIS", which the controller then reduced to that category's term and its
graph's organization before writing anything.

These tests hold the surface to the axiom. A claim can be made under a word no view
declares; it is recorded; and it appears in a view the moment one declares the word
and asks for the history.
"""

import uuid

import kante
import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext

from core import models as core_models
from evidence import models as evidence_models
from evidence import writer as evidence_writer
from graph_engine import input_models
from tests import writes

CREATE_ENTITY_CATEGORY = """
    mutation CreateEntityCategory($input: CreateEntityCategoryInput!) {
        createEntityCategory(input: $input) { id key }
    }
"""

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
async def test_a_view_that_declares_the_word_later_can_pick_the_claim_up(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    age_engine,
) -> None:
    """Org-scoped write, then materialization — the whole point of the change.

    `materialize` created the categories and the AGE namespace and stopped, so a
    graph declaring a word the organization had already used came up empty and
    stayed that way until an operator ran `manage.py reproject`. `backfill` is that
    step, offered at the moment the declaration is made.
    """
    word = f"Latecomer_{uuid.uuid4().hex[:8]}"
    entity_id = await writes.create_entity(api_schema, simple_api_context, word)

    @sync_to_async
    def drawn_in(graph: core_models.Graph) -> int:
        rows = age_engine.execute(graph, "MATCH (n) WHERE n.id = $nid RETURN n", {"nid": entity_id})
        return len(rows)

    assert await drawn_in(test_graph) == 0, "Nothing draws it yet"

    # Declaring the word alone does not project the history — the flag is opt-in
    # because the work is proportional to the organization's evidence.
    quiet = await api_schema.execute(
        CREATE_ENTITY_CATEGORY,
        variable_values={"input": {"graph": str(test_graph.pk), "key": word, "backfill": False}},
        context_value=simple_api_context,
    )
    assert quiet.errors is None, f"GraphQL errors: {quiet.errors}"
    assert await drawn_in(test_graph) == 0, "Declared, but the history was not asked for"

    asked = await api_schema.execute(
        CREATE_ENTITY_CATEGORY,
        variable_values={"input": {"graph": str(test_graph.pk), "key": word, "backfill": True}},
        context_value=simple_api_context,
    )
    assert asked.errors is None, f"GraphQL errors: {asked.errors}"
    assert await drawn_in(test_graph) == 1, "The claim that predated the view is now drawn in it"


def test_create_graph_offers_the_history(api_schema: kante.Schema) -> None:
    """`createGraph` takes `backfill`, and it defaults to off."""
    field = api_schema._schema.type_map["CreateGraphInput"].fields["backfill"]

    assert field is not None, "createGraph must be able to project the evidence its words admit"
    assert field.default_value is False, "and must not do it unasked — the work is O(the organization)"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_new_graph_can_be_a_view_over_history(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    bio_graph_schema: input_models.GraphDefinitionInput,
    age_engine,
) -> None:
    """A graph materialized after the claim holds it.

    Goes through `materialize` rather than the `createGraph` mutation, which
    forwards to it verbatim: re-encoding the whole bio schema as GraphQL variables
    would make this a test of camelCasing. The mutation's own wiring is held up by
    `test_create_graph_offers_the_history` above.
    """
    entity_id = await writes.create_entity(api_schema, simple_api_context, "Cell")

    @sync_to_async
    def hindsight() -> tuple[core_models.Graph, core_models.Graph]:
        from graph_engine.materialize import materialize

        request = simple_api_context.request
        common = dict(
            user=request._user,
            organization=request._organization,
            membership=request.membership,
        )
        quiet = materialize(bio_graph_schema, age_engine, name=f"quiet_{uuid.uuid4().hex[:6]}", **common)
        asked = materialize(bio_graph_schema, age_engine, name=f"asked_{uuid.uuid4().hex[:6]}", backfill=True, **common)
        return quiet, asked

    quiet, asked = await hindsight()

    @sync_to_async
    def drawn_in(graph: core_models.Graph) -> int:
        return len(age_engine.execute(graph, "MATCH (n) WHERE n.id = $nid RETURN n", {"nid": entity_id}))

    assert await drawn_in(quiet) == 0, "A new view declaring the word comes up empty unless asked"
    assert await drawn_in(asked) == 1, "And holds the organization's history when it is"


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


RELATION_BY_ID = """
    query Relation($id: ID!) {
        relation(id: $id) { id }
    }
"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_edge_can_be_read_back_by_the_id_it_was_given(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The id `createRelation` hands out is the id `relation(id:)` accepts.

    It was not. `RetrievedEdge.unique_id` returns the `Link` primary key for any
    row-backed edge — every relation, measurement and structure relation — and the
    resolver split that id on the first hyphen to recover a graph name and an
    integer AGE edge id. On a uuid that produced
    `invalid literal for int() with base 10: '2269-48bc-b049-53535f3be517'`, on the
    very identity the mutation had just returned.

    It was never fixable by parsing more carefully: an AGE edge carries no claim
    id, because `project_edges` merges every assertion of one proposition onto one
    edge. The claim's identity lives in Postgres, so the read has to go there.
    """
    source = await writes.create_entity(api_schema, simple_api_context, "Cell")
    target = await writes.create_entity(api_schema, simple_api_context, "Cell")
    relation_id = await writes.create_relation(api_schema, simple_api_context, "IS_CONNECTED_TO", source, target)

    result = await api_schema.execute(RELATION_BY_ID, variable_values={"id": relation_id}, context_value=simple_api_context)

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data["relation"]["id"] == relation_id, "The claim reads back as itself"


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
        controller = controller_module.GraphController(engine=None)
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

        controller = controller_module.GraphController(engine=None)
        other = Org.objects.get(slug="a-different-tenant")
        return controller._resolve_instance(outsider, None, organization=other) is not None

    assert await allowed(), "The guard is about the tenant, not about the node"
    assert source, "The in-tenant write that set this up still succeeded"


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
