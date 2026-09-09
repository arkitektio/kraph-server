"""Trust is the category's rule (RFC 0009): the discussed example, end to end.

There is no `Graph.selector` any more. A category's `definition` — the union of
clauses RFC 0007 built — is the complete rule for its word in a view:

- which CLASSIFIES claims admit a node (as before),
- whose EXISTENCE standings count for its nodes,
- for a relation or event category, whose LINK claims draw its edges,
- and, by default, whose measurements its properties fold — overridden per
  property by `rule.evidence`, which is the property's own metric rule.

Sameness stays organization grain: a view cannot veto a merge claim.

This file is the acceptance test for the design discussion: the definition
below is the example agreed there, verbatim in spirit.
"""

import pytest
from asgiref.sync import sync_to_async

from core import models as core_models
from graph_engine.controller import GraphController
from tests.support import claims, drawing
from tests.support.graphs import AFTER, BEFORE, example_graph as _example_graph, rebuild as _rebuild
from tests.support.writes import CREATE_GRAPH

@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_classification_admits_per_clause(api_schema, simple_api_context, table_projector) -> None:
    """Peter's word before Dec 5 and Karl's word after — nothing else."""
    graph_id = await _example_graph(api_schema, simple_api_context, "trust-classification")

    @sync_to_async
    def build_and_read():
        graph = core_models.Graph.objects.get(pk=graph_id)
        org = graph.organization
        drawn = claims.mint(org, "AIS", "peter", asserted_at=BEFORE)
        too_late = claims.mint(org, "AIS", "peter", asserted_at=AFTER)
        karls = claims.mint(org, "AxonInitialSegment", "karl", asserted_at=AFTER)
        too_early = claims.mint(org, "AxonInitialSegment", "karl", asserted_at=BEFORE)
        sloppy = claims.mint(org, "AIS", "peter", asserted_at=BEFORE, app_id="sloppy-import")
        _rebuild(graph_id, table_projector)
        return {ref: drawing.vertices_with_ref(graph, ref) for ref in (drawn, too_late, karls, too_early, sloppy)}, drawn, too_late, karls, too_early, sloppy

    counts, drawn, too_late, karls, too_early, sloppy = await build_and_read()
    assert counts[drawn] == 1, "Peter's AIS before Dec 5 is rule 1"
    assert counts[karls] == 1, "Karl's AxonInitialSegment after Dec 5 is rule 2"
    assert counts[too_late] == 0, "Peter after Dec 5 falls outside his rule"
    assert counts[too_early] == 0, "Karl before Dec 5 falls outside his"
    assert counts[sloppy] == 0, "the `unless` group blocks Peter's claim through the sloppy import"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_existence_folds_under_the_categorys_clauses(api_schema, simple_api_context, table_projector) -> None:
    """A retraction counts only when a clause of the node's category covers it."""
    graph_id = await _example_graph(api_schema, simple_api_context, "trust-existence")

    @sync_to_async
    def build_and_read():
        graph = core_models.Graph.objects.get(pk=graph_id)
        org = graph.organization
        retracted = claims.mint(org, "AIS", "peter", asserted_at=BEFORE)
        survives = claims.mint(org, "AIS", "peter", asserted_at=BEFORE)
        # Peter retracting inside his clause's window counts; the same retraction
        # asserted after Dec 5 is outside every clause and counts for nothing.
        claims.retract_node(org, retracted, "peter", asserted_at=BEFORE)
        claims.retract_node(org, survives, "peter", asserted_at=AFTER)
        _rebuild(graph_id, table_projector)
        return drawing.vertices_with_ref(graph, retracted), drawing.vertices_with_ref(graph, survives)

    retracted_count, survives_count = await build_and_read()
    assert retracted_count == 0, "a covered retraction removes the node from this view"
    assert survives_count == 1, "a retraction no clause covers counts for nothing here"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_relation_edges_fold_under_the_relation_categorys_clauses(api_schema, simple_api_context, table_projector) -> None:
    """Only Karl's post-Dec-5 connectivity claims draw IS_CONNECTED_TO edges."""
    graph_id = await _example_graph(api_schema, simple_api_context, "trust-relations")

    @sync_to_async
    def build_and_read():
        graph = core_models.Graph.objects.get(pk=graph_id)
        org = graph.organization
        a = claims.mint(org, "Cell", "peter", asserted_at=BEFORE)
        b = claims.mint(org, "Cell", "peter", asserted_at=BEFORE)
        c = claims.mint(org, "Cell", "peter", asserted_at=BEFORE)
        claims.relate(org, "IS_CONNECTED_TO", a, b, "karl", asserted_at=AFTER)
        claims.relate(org, "IS_CONNECTED_TO", b, c, "peter", asserted_at=AFTER)
        claims.relate(org, "IS_CONNECTED_TO", c, a, "karl", asserted_at=BEFORE)
        _rebuild(graph_id, table_projector)
        return (
            drawing.edges_between(graph, a, b, "IS_CONNECTED_TO"),
            drawing.edges_between(graph, b, c, "IS_CONNECTED_TO"),
            drawing.edges_between(graph, c, a, "IS_CONNECTED_TO"),
        )

    karls_late, peters, karls_early = await build_and_read()
    assert karls_late == 1, "Karl after Dec 5 is the relation category's clause"
    assert peters == 0, "Peter is not trusted for this relation"
    assert karls_early == 0, "Karl before Dec 5 falls outside the clause"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_participations_fold_under_the_event_categorys_clauses(api_schema, simple_api_context, table_projector) -> None:
    """The event category's clauses govern its participation edges too."""
    graph_id = await _example_graph(api_schema, simple_api_context, "trust-participations")

    @sync_to_async
    def build_and_read():
        graph = core_models.Graph.objects.get(pk=graph_id)
        org = graph.organization
        mother = claims.mint(org, "Cell", "peter", asserted_at=BEFORE)
        event = claims.mint(org, "Mitosis", "anyone", app_id="event-annotator", kind="NATURAL_EVENT")
        claims.participate(org, "Mitosis", mother, event, "anyone", app_id="event-annotator", role="mother")
        # A participation claimed through an app the event's clause does not
        # name is not drawn — same word, untrusted tool.
        other = claims.mint(org, "Cell", "peter", asserted_at=BEFORE)
        claims.participate(org, "Mitosis", other, event, "anyone", app_id="freehand", role="mother")
        _rebuild(graph_id, table_projector)
        return (
            drawing.edges_between(graph, mother, event),
            drawing.edges_between(graph, other, event),
        )

    trusted, untrusted = await build_and_read()
    assert trusted == 1, "a participation claimed through the trusted app draws"
    assert untrusted == 0, "one claimed through any other app does not"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_metrics_fold_under_rule_evidence(api_schema, simple_api_context, table_projector) -> None:
    """`rule.evidence` is the property's own metric rule; INFORMS routing stays
    the category's (who may attach evidence to this node)."""
    graph_id = await _example_graph(api_schema, simple_api_context, "trust-metrics")

    @sync_to_async
    def build_and_read():
        graph = core_models.Graph.objects.get(pk=graph_id)
        org = graph.organization
        ais = claims.mint(org, "AIS", "peter", asserted_at=BEFORE)
        # Routing (INFORMS) by Peter inside his clause; the numbers by the
        # pipeline app the rule names — and one by a rival app, excluded.
        claims.measure(org, ais, obj="roi-1", key="vector_length", value=10.0, subject="pipeline", app_id="segmenter-v3", inform_subject="peter", inform_asserted_at=BEFORE)
        claims.measure(org, ais, obj="roi-2", key="vector_length", value=30.0, subject="pipeline", app_id="segmenter-v3", inform_subject="peter", inform_asserted_at=BEFORE)
        claims.measure(org, ais, obj="roi-3", key="vector_length", value=1000.0, subject="pipeline", app_id="rival-tool", inform_subject="peter", inform_asserted_at=BEFORE)
        _rebuild(graph_id, table_projector)
        return drawing.vertex_properties(graph, ais)

    properties = await build_and_read()
    assert properties.get("avg_length") == pytest.approx(20.0), f"only the named app's numbers fold: {properties}"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_informs_routing_folds_under_the_categorys_clauses(api_schema, simple_api_context, table_projector) -> None:
    """Evidence routed to a node by somebody its category does not trust is not counted."""
    graph_id = await _example_graph(api_schema, simple_api_context, "trust-informs")

    @sync_to_async
    def build_and_read():
        graph = core_models.Graph.objects.get(pk=graph_id)
        org = graph.organization
        ais = claims.mint(org, "AIS", "peter", asserted_at=BEFORE)
        # The numbers come from the trusted app either way; only the INFORMS
        # claim's author differs.
        claims.measure(org, ais, obj="roi-good", key="vector_length", value=20.0, subject="pipeline", app_id="segmenter-v3", inform_subject="peter", inform_asserted_at=BEFORE)
        claims.measure(org, ais, obj="roi-smuggled", key="vector_length", value=9000.0, subject="pipeline", app_id="segmenter-v3", inform_subject="stranger", inform_asserted_at=BEFORE)
        _rebuild(graph_id, table_projector)
        return drawing.vertex_properties(graph, ais)

    properties = await build_and_read()
    assert properties.get("avg_length") == pytest.approx(20.0), f"a stranger cannot route evidence under a trusted node: {properties}"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_graph_refuses_a_selector(api_schema, simple_api_context) -> None:
    """`selector` is gone: trust lives in the definition now."""
    made = await api_schema.execute(
        CREATE_GRAPH,
        variable_values={"input": {"name": "no-selectors", "definition": {"extensions": {"entities": [{"key": "X"}]}}, "selector": {"assertionFilter": {"subjects": ["peter"]}}}},
        context_value=simple_api_context,
    )
    assert made.errors is not None, "a selector must be refused, not silently dropped"


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

#: Only the curator may say two things are one — the view's rule, not a category's (RFC 0024).
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
            from evidence import writer

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
        GraphController(projector=table_projector).rebuild_projection(graph)
        after_retraction = drawing.vertices_with_ref(graph, b2)
        # The curator decides sameness only — their retraction counts for nothing.
        claims.retract_node(org, b1, "curator")
        GraphController(projector=table_projector).rebuild_projection(graph)
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
