"""The two grains of trust (RFC 0009/0011).

Labels and connections answer at organization grain — "what does the log say",
whoever said it. Components and sameness answer per **view** since RFC 0011:
rule-driven, within each node's category (`KIND SAMENESS`), pinned by
`tests/api/test_category_trust.py::test_existence_and_sameness_are_distinct_rules`.
This file holds the organization-grain half of that record — the claim-grain
reads keep the cached org-wide fold — and the metric lane at category grain.
"""

import kante
import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext

from core import models as core_models
from evidence import identity as identity_module
from evidence import models as evidence_models
from evidence import panel, writer
from tests import claims, rules, writes

CREATE_GRAPH = """
    mutation G($input: CreateGraphInput!) {
        createGraph(input: $input) { id }
    }
"""


async def _graph_declaring(api_schema, ctx, word: str, *, name: str, definition: dict | None = None) -> str:
    entity: dict = {"key": word}
    if definition is not None:
        entity["definition"] = definition
    payload: dict = {"name": name, "definition": {"extensions": {"entities": [entity]}}}
    made = await api_schema.execute(CREATE_GRAPH, variable_values={"input": payload}, context_value=ctx)
    assert made.errors is None, f"GraphQL errors: {made.errors}"
    return made.data["createGraph"]["id"]


def _merge_as(organization, left: str, right: str, subject: str) -> None:
    """A sameness claim by a named annotator, folded into the org-grain cache
    exactly as the controller folds it."""
    assertion = writer.create_assertion(organization, subject=subject, app_id="pytest")
    writer.create_link(organization, kind=evidence_models.Link.Kind.SAME_AS, source_ref=left, target_ref=right, assertion=assertion)
    identity_module.merge(organization, left, right)


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
async def test_the_component_of_a_primitive_view_unions_its_categorys_merges(api_schema: kante.Schema, simple_api_context: HttpContext, table_projector, backend_stack) -> None:
    everyone_id = await _graph_declaring(api_schema, simple_api_context, "ApiCell", name="api-everyone")
    curator_id = await _graph_declaring(
        api_schema,
        simple_api_context,
        "ApiCell",
        name="api-curator",
        definition=rules.definition(rules.rule(rules.word("ApiCell"), rules.by("curator", "1"))),
    )

    a = await writes.create_entity(api_schema, simple_api_context, "ApiCell")
    b = await writes.create_entity(api_schema, simple_api_context, "ApiCell")

    @sync_to_async
    def merge():
        organization = core_models.Graph.objects.get(pk=everyone_id).organization
        _merge_as(organization, a, b, "bot")

    await merge()

    async def component_in(graph_id: str) -> list[str]:
        result = await api_schema.execute(
            "query($id: ID!, $graph: ID!) { node(id: $id, graph: $graph) { ... on Entity { component } } }",
            variable_values={"id": a, "graph": graph_id},
            context_value=simple_api_context,
        )
        assert result.errors is None, f"GraphQL errors: {result.errors}"
        return sorted(result.data["node"]["component"])

    assert await component_in(everyone_id) == sorted([a, b]), "a primitive category trusts every merger — within the category"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_narrowing_a_categorys_trust_takes_derived_values_and_windows_with_it(api_schema: kante.Schema, simple_api_context: HttpContext, table_projector, backend_stack) -> None:
    """The metric lane, end to end, at category grain (RFC 0009).

    A Probe measured through two ROIs derives `size` and an observation window
    when its category trusts the measurers. Rebuilt under clauses naming only
    the curator, the INFORMS links and metrics stop counting: the node stays —
    the curator classified it — but its derived knowledge is gone. This pins the
    leaks RFC 0008 closed staying closed under the per-category fold: informs
    routing, the scoped state, and `_observation_window` all follow the clauses.
    """
    graph_id = await _graph_declaring(api_schema, simple_api_context, "Probe", name="metric-lane")

    @sync_to_async
    def declare_property():
        category = core_models.EntityCategory.objects.get(graph_id=graph_id, key="Probe")
        category.property_definitions = [
            {"key": "size", "value_kind": "FLOAT", "derivation": "ROLLUP", "rule": {"source_node": "ROI", "key": "size", "aggregation": "MEAN"}}
        ]
        category.save()

    await declare_property()

    # The baseline goes through the write path so the cached state vector is
    # maintained — the primitive category's fast path is exactly what is being
    # narrowed away below.
    ref = await writes.create_entity(
        api_schema,
        simple_api_context,
        "Probe",
        evidence=[
            {"identifier": "ROI", "object": "probe-roi-1", "metrics": [{"key": "size", "value": 10.0, "valueKind": "FLOAT"}]},
            {"identifier": "ROI", "object": "probe-roi-2", "metrics": [{"key": "size", "value": 30.0, "valueKind": "FLOAT"}]},
        ],
    )

    @sync_to_async
    def narrow_and_read():
        from graph_engine.controller import GraphController
        from tests import drawing

        graph = core_models.Graph.objects.get(pk=graph_id)
        category = core_models.EntityCategory.objects.get(graph=graph, key="Probe")
        controller = GraphController(projector=table_projector)
        controller.rebuild_projection(graph)
        before = drawing.vertex_properties(graph, ref)

        # The curator also classified it, so narrowing to the curator keeps the
        # node while dropping the request identity's measurements and routing.
        claims.classify(graph, ref, category, "curator")
        category.definition = rules.definition(rules.rule(rules.word("Probe"), rules.by("curator")))
        category.save()
        controller.rebuild_projection(graph)
        after = drawing.vertex_properties(graph, ref)
        return before, after

    before, after = await narrow_and_read()
    assert before.get("size") == pytest.approx(20.0), f"trusting everyone: mean size — got {before}"
    assert before.get("valid_from") is not None, "and a real observation window"
    assert after.get("id") == ref, "the node stands — the curator classified it"
    assert after.get("size") is None, f"but the untrusted measurements no longer derive a size — got {after}"
    assert after.get("valid_from") is None, "and the observation window they stretched is gone with them"
