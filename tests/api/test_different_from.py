"""Saying "no, these are two" (RFC 0019).

`SAME_AS` says two observations are one individual. Until now nothing could say
the opposite: a merge could only be undone by retracting the claim that made
it, which is a position on somebody *else's* claim, not a claim of one's own.
`DIFFERENT_FROM` is that claim — the mirror of `SAME_AS`, made under the same
rule (a category that trusts a `SAME_AS` trusts a `DIFFERENT_FROM`, both are
`SAMENESS`), with one deterministic effect on the fold: a standing, trusted
`DIFFERENT_FROM(a, b)` **vetoes every direct `SAME_AS` between a and b**, in
either orientation. A conflict through a third instance (a~b, b~c, a≠c) is not
resolved by the fold — the component stays merged and the panel reports the
difference under `conflicts`, so a person can decide which claim to retract.
"""

import pytest
from asgiref.sync import sync_to_async

from core import models as core_models
from evidence import identity, models as evidence_models
from graph_engine.controller import GraphController
from tests import claims, drawing
from tests.api.test_category_trust import BEFORE, _example_graph
from tests.api.test_entity_identity import ASSERT_SAME, _assert_entity

ASSERT_DIFFERENT = """
    mutation AssertDifferentInstance($input: AssertDifferentInstanceInput!) {
        assertDifferentInstance(input: $input) {
            assertion { id }
            links { kind id source { ... on Instance { id } } target { ... on Instance { id } } }
        }
    }
"""

RETRACT_DIFFERENT = """
    mutation RetractDifferentInstance($input: RetractDifferentInstanceInput!) {
        retractDifferentInstance(input: $input) { assertion { id } links { id } }
    }
"""

NODE = """
    query Node($id: ID!, $graph: ID!) {
        node(id: $id, graph: $graph) {
            id
            members
            sameAs { __typename id }
            differentFrom { __typename id source { ... on Entity { id } } target { ... on Entity { id } } }
            conflicts { __typename id }
        }
    }
"""

INSTANCE = """
    query Instance($id: ID!) {
        instance(id: $id) { id differentFrom { __typename id } }
    }
"""

LINK = """
    query Link($id: ID!) {
        link(id: $id) { id kind source { ... on Instance { id } } target { ... on Instance { id } } }
    }
"""


async def _execute(api_schema, ctx, document: str, variables: dict) -> dict:
    result = await api_schema.execute(document, variable_values=variables, context_value=ctx)
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    return result.data


async def _same(api_schema, ctx, refs: list[str]) -> str:
    return (await _execute(api_schema, ctx, ASSERT_SAME, {"input": {"instances": refs}}))["assertSameInstance"]["links"][0]["id"]


async def _different(api_schema, ctx, refs: list[str]) -> dict:
    return (await _execute(api_schema, ctx, ASSERT_DIFFERENT, {"input": {"instances": refs}}))["assertDifferentInstance"]


async def _node(api_schema, ctx, graph: core_models.Graph, ref: str) -> dict:
    return (await _execute(api_schema, ctx, NODE, {"id": ref, "graph": str(graph.pk)}))["node"]


@sync_to_async
def _drawn(graph: core_models.Graph, *refs: str):
    """Vertex count, then each ref's representative and members — the view's fold."""
    return drawing.vertex_count(graph, "AIS"), [(drawing.representative_of(graph, ref), drawing.members_of(graph, ref)) for ref in refs]


@sync_to_async
def _cached(graph: core_models.Graph, *refs: str) -> dict[str, list[str]]:
    """The organization-grain identity cache's answer."""
    return {ref: sorted(members) for ref, members in identity.component_refs(graph.organization, list(refs)).items()}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_difference_vetoes_the_direct_sameness(api_schema, simple_api_context, test_graph: core_models.Graph) -> None:
    """Two merged observations come apart when somebody says they are two — in
    the view's drawing and in the organization's cache — and the claim that
    merged them is still in the log, not retracted, only outweighed."""
    a = (await _assert_entity(api_schema, simple_api_context, "AIS"))["instance"]["id"]
    b = (await _assert_entity(api_schema, simple_api_context, "AIS", same_as=[a]))["instance"]["id"]
    assert (await _drawn(test_graph, a))[0] == 1, "precondition: merged"

    made = await _different(api_schema, simple_api_context, [a, b])
    (link,) = made["links"]
    assert link["kind"] == "DIFFERENT_FROM", "the write returns the claim, as `assertSameInstance` does"
    assert {link["source"]["id"], link["target"]["id"]} == {a, b}

    count, folds = await _drawn(test_graph, a, b)
    assert count == 2, "the veto splits the individual"
    assert folds == [(a, [a]), (b, [b])], "each observation is its own vertex again"
    assert await _cached(test_graph, a, b) == {a: [a], b: [b]}, "and the organization-grain cache agrees"

    node = await _node(api_schema, simple_api_context, test_graph, a)
    assert node["id"] == a and node["members"] == [a]
    assert [d["id"] for d in node["differentFrom"]] == [link["id"]]
    assert node["differentFrom"][0]["__typename"] == "Difference"
    assert node["conflicts"] == [], "a direct veto is resolved by the fold, not reported as a conflict"
    assert [s["id"] for s in node["sameAs"]] != [], "the vetoed sameness is still a standing claim the panel shows"

    instance = (await _execute(api_schema, simple_api_context, INSTANCE, {"id": b}))["instance"]
    assert [d["id"] for d in instance["differentFrom"]] == [link["id"]], "readable at claim grain too"

    read = (await _execute(api_schema, simple_api_context, LINK, {"id": link["id"]}))["link"]
    assert read["kind"] == "DIFFERENT_FROM" and {read["source"]["id"], read["target"]["id"]} == {a, b}, "`link(id:)` reads it at claim grain; both ends dispatch to `Instance`"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_difference_asserted_first_prevents_the_merge(api_schema, simple_api_context, test_graph: core_models.Graph) -> None:
    """Order does not matter: the sameness claim written after the difference is
    recorded but does not union."""
    a = (await _assert_entity(api_schema, simple_api_context, "AIS"))["instance"]["id"]
    b = (await _assert_entity(api_schema, simple_api_context, "AIS"))["instance"]["id"]
    await _different(api_schema, simple_api_context, [a, b])

    same_id = await _same(api_schema, simple_api_context, [a, b])

    count, folds = await _drawn(test_graph, a, b)
    assert count == 2
    assert folds == [(a, [a]), (b, [b])]
    assert await _cached(test_graph, a, b) == {a: [a], b: [b]}

    @sync_to_async
    def recorded() -> bool:
        return evidence_models.Link.all_objects.filter(pk=same_id, kind=evidence_models.Link.Kind.SAME_AS).exists()  # cross-org read: a test looking at the log

    assert await recorded(), "the sameness claim is in the log regardless — a veto is a fold rule, not a refusal"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_conflict_through_a_third_instance_stays_merged_and_is_reported(api_schema, simple_api_context, test_graph: core_models.Graph) -> None:
    """a~b, b~c, a≠c: no direct sameness is vetoed, so the fold keeps one
    individual of three, and `conflicts` names the difference that disagrees."""
    a = (await _assert_entity(api_schema, simple_api_context, "AIS"))["instance"]["id"]
    b = (await _assert_entity(api_schema, simple_api_context, "AIS", same_as=[a]))["instance"]["id"]
    c = (await _assert_entity(api_schema, simple_api_context, "AIS", same_as=[b]))["instance"]["id"]
    representative = min(a, b, c)

    made = await _different(api_schema, simple_api_context, [a, c])
    difference = made["links"][0]["id"]

    count, folds = await _drawn(test_graph, a, c)
    assert count == 1, "the fold does not guess which sameness to drop"
    assert folds == [(representative, sorted([a, b, c]))] * 2
    assert await _cached(test_graph, a, c) == {a: sorted([a, b, c]), c: sorted([a, b, c])}

    for member in (a, b, c):
        node = await _node(api_schema, simple_api_context, test_graph, member)
        assert [x["id"] for x in node["conflicts"]] == [difference], f"the conflict is reported on every member ({member})"
        assert node["conflicts"][0]["__typename"] == "Difference"
    assert [x["id"] for x in (await _node(api_schema, simple_api_context, test_graph, b))["differentFrom"]] == [difference], "the panel answers for the individual, so b — party to no difference itself — reports the one about the thing it is a member of"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_retracting_the_difference_restores_the_union(api_schema, simple_api_context, test_graph: core_models.Graph) -> None:
    a = (await _assert_entity(api_schema, simple_api_context, "AIS"))["instance"]["id"]
    b = (await _assert_entity(api_schema, simple_api_context, "AIS", same_as=[a]))["instance"]["id"]
    made = await _different(api_schema, simple_api_context, [a, b])
    assert (await _drawn(test_graph, a))[0] == 2, "precondition: split"

    retracted = (await _execute(api_schema, simple_api_context, RETRACT_DIFFERENT, {"input": {"id": made["links"][0]["id"]}}))["retractDifferentInstance"]
    assert retracted["links"][0]["id"] == made["links"][0]["id"]

    count, folds = await _drawn(test_graph, a, b)
    assert count == 1
    assert folds == [(min(a, b), sorted([a, b]))] * 2
    assert await _cached(test_graph, a, b) == {a: sorted([a, b]), b: sorted([a, b])}
    node = await _node(api_schema, simple_api_context, test_graph, a)
    assert node["differentFrom"] == [], "a retracted difference no longer stands"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_difference_the_category_does_not_trust_is_ignored(api_schema, simple_api_context, table_projector) -> None:
    """Sameness is the view's rule (RFC 0024), and so is its negation: this view
    trusts Peter, so a stranger's `DIFFERENT_FROM` changes nothing in it —
    while Peter's own splits it."""
    graph_id = await _example_graph(api_schema, simple_api_context, "difference-trust")

    @sync_to_async
    def build_and_read():
        graph = core_models.Graph.objects.get(pk=graph_id)
        # Sameness is the view's rule (RFC 0024): this view counts Peter's merges.
        graph.sameness_rule = {"rules": [{"when": [{"field": "SUBJECT", "operator": "IS", "value": "peter"}]}]}
        graph.save(update_fields=["sameness_rule"])
        org = graph.organization
        a = claims.mint(org, "AIS", "peter", asserted_at=BEFORE)
        b = claims.mint(org, "AIS", "peter", asserted_at=BEFORE)
        claims.same(org, a, b, "peter", asserted_at=BEFORE)
        controller = GraphController(projector=table_projector)
        controller.rebuild_projection(graph)
        merged = drawing.vertex_count(graph, "AIS"), drawing.members_of(graph, a)
        claims.different(org, a, b, "stranger", asserted_at=BEFORE)
        controller.rebuild_projection(graph)
        ignored = drawing.vertex_count(graph, "AIS"), drawing.members_of(graph, a)
        claims.different(org, a, b, "peter", asserted_at=BEFORE)
        controller.rebuild_projection(graph)
        trusted = drawing.vertex_count(graph, "AIS"), drawing.members_of(graph, a)
        return merged, ignored, trusted, a, b

    merged, ignored, trusted, a, b = await build_and_read()
    assert merged == (1, sorted([a, b]))
    assert ignored == (1, sorted([a, b])), "the stranger's veto is not one this view counts"
    assert trusted == (2, [a]), "Peter's is"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_difference_needs_two_distinct_instances(api_schema, simple_api_context, test_graph: core_models.Graph) -> None:
    a = (await _assert_entity(api_schema, simple_api_context, "AIS"))["instance"]["id"]
    result = await api_schema.execute(ASSERT_DIFFERENT, variable_values={"input": {"instances": [a, a]}}, context_value=simple_api_context)
    assert result.errors is not None, "an instance cannot be different from itself"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_rebuild_identity_check_agrees_under_the_veto(api_schema, simple_api_context, test_graph: core_models.Graph) -> None:
    """`manage.py rebuild_identity --check` recomputes the cache from the claims
    and must reach the same answer the write path did, veto included."""
    from io import StringIO

    from django.core.management import call_command

    a = (await _assert_entity(api_schema, simple_api_context, "AIS"))["instance"]["id"]
    b = (await _assert_entity(api_schema, simple_api_context, "AIS", same_as=[a]))["instance"]["id"]
    c = (await _assert_entity(api_schema, simple_api_context, "AIS", same_as=[b]))["instance"]["id"]
    await _different(api_schema, simple_api_context, [a, c])
    await _different(api_schema, simple_api_context, [b, c])

    assert await _cached(test_graph, a, b, c) == {a: sorted([a, b]), b: sorted([a, b]), c: [c]}, "b≠c is direct and cuts b~c; a≠c is then no conflict"

    @sync_to_async
    def check() -> str:
        out = StringIO()
        call_command("rebuild_identity", "--check", "--organization", test_graph.organization.slug, stdout=out)
        return out.getvalue()

    assert "fold agrees with the claims" in await check()
