"""Identity is the view's function of the log (RFC 0024).

One answer per view to how many things are here: the view's `samenessRule`
decides whose merges count, across every category it draws, and changing it
refolds the individuals.
"""

import pytest
from asgiref.sync import sync_to_async

from core import models as core_models
from evidence import models as evidence_models
from evidence import writer
from tests import claims, drawing

CREATE_GRAPH = """
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
    made = await api_schema.execute(CREATE_GRAPH, variable_values={"input": {"name": "view-identity", "definition": SCHEMA, "samenessRule": {"rules": [{"when": [{"field": "SUBJECT", "operator": "IS", "value": "curator"}]}]}}}, context_value=simple_api_context)
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
        from graph_engine.controller import GraphController

        GraphController(projector=table_projector).rebuild_projection(graph)
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
def test_the_standing_cache_is_total(test_graph) -> None:
    """RFC 0024: the trust-everyone fold caches an instance's standing like any
    claim's. What a view says is still its category's rule."""
    from evidence import claims as claims_module

    org = test_graph.organization
    node = claims.mint(org, "AIS", "peter")
    assert claims_module.current(org, "node", node) is True
    writer.retract(org, evidence_models.Instance.all_objects.get(pk=node), writer.create_assertion(org, subject="peter", app_id="pytest"))
    assert claims_module.current(org, "node", node) is False
    assert not claims_module.standing(evidence_models.Instance.objects.for_organization(org).filter(pk=node), "node").exists()
