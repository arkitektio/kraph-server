"""Identity is the view's function of the log (RFC 0024, A5/C3).

One answer per view to how many things are here: the view's `samenessRule`
decides whose merges count, across every category it draws, and changing it
refolds the individuals.
"""

import pytest
from asgiref.sync import sync_to_async
from core import models as core_models
from tests.support import claims, drawing, graphs, rules, writes
import uuid
import kante
from kante.context import HttpContext
from evidence import identity, models as evidence_models
from tests.support.writes import ASSERT_SAME, RETRACT_SAME
from evidence import panel
from tests.support.graphs import graph_declaring as _graph_declaring, merge_as as _merge_as
from tests.support.graphs import BEFORE, example_graph as _example_graph
from tests.support.writes import CREATE_GRAPH
from evidence import writer


CREATE_GRAPH_WITH_RULE = """
    mutation Create($input: CreateGraphInput!) {
        createGraph(input: $input) { id samenessRule { rules { when { field operator value } } } }
    }
"""
UPDATE_GRAPH = """
    mutation Update($input: UpdateGraphInput!) {
        updateGraph(input: $input) { id samenessRule { rules { when { field operator value } } } }
    }
"""
NODE = """
    query N($id: ID!, $graph: ID!) { node(id: $id, graph: $graph) { id members drawnLabels } }
"""
SCHEMA = {"extensions": {"entities": [{"key": "Cell"}, {"key": "Nucleus"}]}}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_views_rule_decides_and_reaches_across_categories(api_schema, simple_api_context, table_projector) -> None:
    made = await api_schema.execute(CREATE_GRAPH_WITH_RULE, variable_values={"input": {"name": "view-identity", "definition": SCHEMA, "samenessRule": {"rules": [{"when": [{"field": "SUBJECT", "operator": "IS", "value": "curator"}]}]}}}, context_value=simple_api_context)
    assert made.errors is None, f"GraphQL errors: {made.errors}"
    graph_id = made.data["createGraph"]["id"]
    assert made.data["createGraph"]["samenessRule"]["rules"][0]["when"][0]["value"] == "curator"

    @sync_to_async
    def story():
        graph = core_models.Graph.objects.get(pk=graph_id)
        org = graph.organization
        cell, nucleus, other = claims.mint(org, "Cell", "peter"), claims.mint(org, "Nucleus", "peter"), claims.mint(org, "Cell", "peter")
        claims.same(org, cell, nucleus, "curator")  # trusted, across categories
        claims.same(org, cell, other, "peter")  # not trusted here

        graphs.rebuild(graph, table_projector)
        return graph, cell, nucleus, other, drawing.members_of(graph, cell), drawing.labels_of(graph, cell), drawing.members_of(graph, other)

    graph, cell, nucleus, other, members, labels, others = await story()
    assert members == sorted([cell, nucleus]), "the curator's merge unions a Cell and a Nucleus: the view holds one thing"
    assert labels == {"Cell", "Nucleus"}
    assert others == [other], "Peter's merge is not this view's"

    read = await api_schema.execute(NODE, variable_values={"id": nucleus, "graph": graph_id}, context_value=simple_api_context)
    assert read.errors is None, f"GraphQL errors: {read.errors}"
    assert sorted(read.data["node"]["members"]) == sorted([cell, nucleus])

    # Widen the rule to everyone: Peter's merge now counts, and the drawing is refolded.
    updated = await api_schema.execute(UPDATE_GRAPH, variable_values={"input": {"id": graph_id, "samenessRule": {"rules": []}}}, context_value=simple_api_context)
    assert updated.errors is None, f"GraphQL errors: {updated.errors}"
    assert updated.data["updateGraph"]["samenessRule"] is None, "no rules means everyone, read back as null"
    assert await sync_to_async(drawing.members_of)(graph, cell) == sorted([cell, nucleus, other])
    versions = await sync_to_async(lambda: core_models.GraphSchema.objects.filter(graph=graph).count())()
    assert versions >= 2, "a sameness rule change is a version of the view"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_noticing_later_that_two_instances_are_one(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The standalone claim, for the case that is genuinely its own act."""
    first = await writes.assert_entity(api_schema, simple_api_context, "AIS")
    second = await writes.assert_entity(api_schema, simple_api_context, "AIS")

    result = await api_schema.execute(
        ASSERT_SAME,
        variable_values={"input": {"instances": [first["instance"]["id"], second["instance"]["id"]]}},
        context_value=simple_api_context,
    )
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    payload = result.data["assertSameInstance"]

    assert len(payload["links"]) == 1
    claim = payload["links"][0]

    # `kind`, which is the column the claim carries. It used to be `__typename` over
    # a payload of drawing types, where a sameness claim had no type of its own and
    # `cast_edge_to_graphql_type` reported anything it did not recognise as a
    # `Relation` — the exact defect participations had.
    assert claim["kind"] == "SAME_AS"
    assert {claim["source"]["id"], claim["target"]["id"]} == {first["instance"]["id"], second["instance"]["id"]}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_retracting_sameness_splits_the_component(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Taking it back has to actually take it back.

    Union-find has no un-union, so the component is rebuilt from the claims that
    survive rather than adjusted — and this is the test that says the rebuild
    reaches the API.
    """
    first = await writes.assert_entity(api_schema, simple_api_context, "AIS")
    second = await writes.assert_entity(api_schema, simple_api_context, "AIS", same_as=[first["instance"]["id"]])

    @sync_to_async
    def sameness_id() -> str:
        link = evidence_models.Link.all_objects.filter(kind=evidence_models.Link.Kind.SAME_AS).first()
        assert link is not None
        return str(link.pk)

    result = await api_schema.execute(
        RETRACT_SAME,
        variable_values={"input": {"id": await sameness_id()}},
        context_value=simple_api_context,
    )
    assert result.errors is None, f"GraphQL errors: {result.errors}"

    @sync_to_async
    def components() -> tuple[list[str], list[str]]:
        organization = test_graph.organization
        return (
            identity.component_refs(organization, [first["instance"]["id"]])[first["instance"]["id"]],
            identity.component_refs(organization, [second["instance"]["id"]])[second["instance"]["id"]],
        )

    left, right = await components()
    assert left == [first["instance"]["id"]], "Each is its own thing again"
    assert right == [second["instance"]["id"]]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_structure_cannot_be_claimed_the_same_as_anything(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Structures are never "the same".

    A structure is a pointer to an external datum, already idempotent by
    `(identifier, object)` — so two of them are either one row or two different
    data, and a sameness claim about them is really a claim about the entities
    they inform. Refusing is better than folding a claim no reader can act on.
    """
    entity = (await writes.assert_entity(api_schema, simple_api_context, "AIS"))["instance"]["id"]

    created = await api_schema.execute(
        """
        mutation AssertStructureExists($input: AssertStructureExistsInput!) {
            assertStructureExists(input: $input) { structure { id } }
        }
        """,
        variable_values={"input": {"identifier": "@mikro/roi", "object": f"roi-{uuid.uuid4().hex[:8]}", "metrics": []}},
        context_value=simple_api_context,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    structure = created.data["assertStructureExists"]["structure"]["id"]

    refused = await api_schema.execute(
        ASSERT_SAME,
        variable_values={"input": {"instances": [entity, structure]}},
        context_value=simple_api_context,
    )
    assert refused.errors, "A structure is not an entity and cannot be merged with one"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_node_cannot_be_claimed_the_same_as_itself(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """A node is trivially itself, so the claim carries no information."""
    entity = (await writes.assert_entity(api_schema, simple_api_context, "AIS"))["instance"]["id"]

    result = await api_schema.execute(
        ASSERT_SAME,
        variable_values={"input": {"instances": [entity, entity]}},
        context_value=simple_api_context,
    )
    assert result.errors, "Claiming a node is the same as itself must be refused"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_claim_grain_sameness_is_organization_grain(api_schema: kante.Schema, simple_api_context: HttpContext, table_projector, backend_stack) -> None:
    """With no view in scope, the fold is the organization's cached answer.

    The bot's merge shows here whoever a view might refuse it — the log unions
    every standing claim, and the panel keeps merges visible and contestable.
    The *view's* answer is the per-category walk (RFC 0011), pinned in the
    flagship trust tests.
    """
    await _graph_declaring(api_schema, simple_api_context, "TrustCell", name="trusting-everyone")
    await _graph_declaring(
        api_schema,
        simple_api_context,
        "TrustCell",
        name="trusting-curator",
        definition=rules.definition(rules.rule(rules.word("TrustCell"), rules.by("curator"))),
    )

    a = await writes.create_entity(api_schema, simple_api_context, "TrustCell")
    b = await writes.create_entity(api_schema, simple_api_context, "TrustCell")
    c = await writes.create_entity(api_schema, simple_api_context, "TrustCell")

    @sync_to_async
    def fold():
        organization = core_models.Graph.objects.get(name="trusting-everyone").organization
        _merge_as(organization, a, b, "bot")
        _merge_as(organization, b, c, "curator")
        return panel.components_for(organization, [a])[a], panel.sameness_for(organization, [a, b, c])

    component, sameness = await fold()
    assert component == sorted([a, b, c]), "the organization-grain fold unions every standing claim, whoever made it"
    assert sameness.get(a), "and the bot's claim shows in the panel — visible and contestable, not hidden"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_sameness_the_category_does_not_trust_draws_two_vertices(api_schema, simple_api_context, table_projector) -> None:
    """Sameness is the view's rule (RFC 0024): this view trusts Peter, so a stranger's merge changes nothing here."""
    graph_id = await _example_graph(api_schema, simple_api_context, "individual-trust")

    @sync_to_async
    def build_and_read():
        graph = core_models.Graph.objects.get(pk=graph_id)
        # Sameness is the view's rule (RFC 0024): this view counts Peter's merges.
        graph.sameness_rule = {"rules": [{"when": [{"field": "SUBJECT", "operator": "IS", "value": "peter"}]}]}
        graph.save(update_fields=["sameness_rule"])
        org = graph.organization
        a = claims.mint(org, "AIS", "peter", asserted_at=BEFORE)
        b = claims.mint(org, "AIS", "peter", asserted_at=BEFORE)
        claims.same(org, a, b, "stranger", asserted_at=BEFORE)
        graphs.rebuild(graph, table_projector)
        ignored = drawing.vertex_count(graph, "AIS"), drawing.members_of(graph, a)
        claims.same(org, a, b, "peter", asserted_at=BEFORE)
        graphs.rebuild(graph, table_projector)
        return ignored, (drawing.vertex_count(graph, "AIS"), drawing.members_of(graph, a)), a, b

    ignored, trusted, a, b = await build_and_read()
    assert ignored == (2, [a]), "the stranger's claim is not one this view counts"
    assert trusted == (1, sorted([a, b])), "Peter's is"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_sameness_claim_survives_in_the_log_when_a_view_ignores_it(api_schema, simple_api_context, test_graph: core_models.Graph) -> None:
    """The organization-grain cache still folds every standing claim; only the drawing is per view."""
    from evidence import identity

    a = await writes.create_entity(api_schema, simple_api_context, "AIS")
    b = await writes.create_entity(api_schema, simple_api_context, "AIS")
    await writes.merge(api_schema, simple_api_context, [a, b])

    @sync_to_async
    def cached():
        links = evidence_models.Link.objects.for_organization(test_graph.organization).filter(kind=evidence_models.Link.Kind.SAME_AS).count()
        return links, identity.component_refs(test_graph.organization, [a])[a]

    links, component = await cached()
    assert links == 1 and sorted(component) == sorted([a, b])


SAMENESS_DEFINITION = {
    "systemVersion": "1.0.0",
    "extensions": {
        "entities": [
            {
                "key": "Axon",
                "definition": {
                    "rules": [
                        # Peter and Karl decide what exists and what classifies.
                        {
                            "when": [
                                {"field": "WORD", "operator": "IN", "value": ["AIS", "AxonInitialSegment"]},
                                {"field": "SUBJECT", "operator": "IN", "value": ["peter", "karl"]},
                            ]
                        },
                    ]
                },
            },
            {"key": "Cell"},
        ],
    },
}


CURATOR_MERGES = {"rules": [{"when": [{"field": "SUBJECT", "operator": "IS", "value": "curator"}]}]}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_existence_and_sameness_are_distinct_rules(api_schema, simple_api_context, table_projector) -> None:
    """The motivating scenario (RFC 0011, restated by RFC 0024): Peter may
    retract, only the curator may merge — and merging is the view's rule, so
    it reaches across categories: a thing the view holds is one thing."""
    made = await api_schema.execute(CREATE_GRAPH, variable_values={"input": {"name": "kinds-apart", "definition": SAMENESS_DEFINITION, "samenessRule": CURATOR_MERGES}}, context_value=simple_api_context)
    assert made.errors is None, f"GraphQL errors: {made.errors}"
    graph_id = made.data["createGraph"]["id"]

    @sync_to_async
    def story():
        from evidence import identity, panel

        graph = core_models.Graph.objects.get(pk=graph_id)
        org = graph.organization

        a1 = claims.mint(org, "AIS", "peter")
        a2 = claims.mint(org, "AxonInitialSegment", "karl")
        b1 = claims.mint(org, "AIS", "peter")
        b2 = claims.mint(org, "AIS", "peter")
        cell = claims.mint(org, "Cell", "anyone")

        def merge_as(left, right, subject):
            from evidence import models as evidence_models

            writer.create_link(org, kind=evidence_models.Link.Kind.SAME_AS, source_ref=left, target_ref=right, assertion=writer.create_assertion(org, subject=subject, app_id="pytest"))
            # The org-grain cache folds every claim, exactly as the controller does.
            identity.merge(org, left, right)

        merge_as(a1, a2, "curator")  # trusted: two words of one category
        merge_as(b1, b2, "peter")  # not the curator: the view does not count it
        merge_as(a1, cell, "curator")  # trusted, across categories: one thing, drawn under both

        curator_component = panel.components_for(org, [a1], graph=graph)[a1]
        peters_component = panel.components_for(org, [b1], graph=graph)[b1]
        org_component = panel.components_for(org, [b1])[b1]

        # Existence stays Peter's: his retraction removes his node.
        claims.retract_node(org, b2, "peter")
        graphs.rebuild(graph, table_projector)
        after_retraction = drawing.vertices_with_ref(graph, b2)
        # The curator decides sameness only — their retraction counts for nothing.
        claims.retract_node(org, b1, "curator")
        graphs.rebuild(graph, table_projector)
        curator_cannot_retract = drawing.vertices_with_ref(graph, b1)
        drawn_labels = drawing.labels_of(graph, a1)

        return curator_component, peters_component, org_component, after_retraction, curator_cannot_retract, a1, a2, cell, drawn_labels

    curator_component, peters_component, org_component, after_retraction, curator_cannot_retract, a1, a2, cell, drawn_labels = await story()
    assert sorted(curator_component) == sorted([a1, a2, cell]), "the curator's merges union across words and across categories: the view holds one thing"
    assert drawn_labels == {"Axon", "Cell"}, "drawn once, under every category that admits a member"
    assert peters_component == [str(peters_component[0])] and len(peters_component) == 1, "Peter is not trusted on sameness here, so his merge does not union"
    assert len(org_component) == 2, "the trust-everyone fold still unions everything — the view disagrees, the log does not"
    assert after_retraction == 0, "Peter still decides existence"
    assert curator_cannot_retract == 1, "the curator's word counts for sameness only — their retraction counts for nothing"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_category_may_not_rule_on_sameness(api_schema, simple_api_context) -> None:
    """KIND SAMENESS in a category definition is refused (RFC 0024)."""
    definition = {"extensions": {"entities": [{"key": "X", "definition": {"rules": [{"when": [{"field": "WORD", "operator": "IS", "value": "X"}, {"field": "KIND", "operator": "NOT_IN", "value": ["SAMENESS"]}]}]}}]}}
    made = await api_schema.execute(CREATE_GRAPH, variable_values={"input": {"name": "no-category-sameness", "definition": definition}}, context_value=simple_api_context)
    assert made.errors is not None and "samenessRule" in str(made.errors[0]), "a category's rule may not name SAMENESS; the view's rule does"


