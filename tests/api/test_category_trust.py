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

from datetime import datetime, timezone

import kante
import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext

from core import models as core_models
from graph_engine.controller import GraphController
from tests import claims, drawing

CREATE_GRAPH = """
    mutation G($input: CreateGraphInput!) {
        createGraph(input: $input) { id }
    }
"""

DEC5 = datetime(2026, 12, 5, tzinfo=timezone.utc)
BEFORE = datetime(2026, 11, 1, tzinfo=timezone.utc)
AFTER = datetime(2026, 12, 20, tzinfo=timezone.utc)

DEFINITION = {
    "systemVersion": "2.0.0",
    "extensions": {
        "entities": [
            {
                "key": "AIS",
                "definition": {
                    "rules": [
                        {
                            "when": [
                                {"field": "WORD", "operator": "IS", "value": "AIS"},
                                {"field": "SUBJECT", "operator": "IS", "value": "peter"},
                                {"field": "ASSERTED_AT", "operator": "BEFORE", "value": DEC5.isoformat()},
                            ],
                            "unless": [{"when": [{"field": "APP", "operator": "IS", "value": "sloppy-import"}]}],
                        },
                        {
                            "when": [
                                {"field": "WORD", "operator": "IS", "value": "AxonInitialSegment"},
                                {"field": "SUBJECT", "operator": "IS", "value": "karl"},
                                {"field": "ASSERTED_AT", "operator": "SINCE", "value": DEC5.isoformat()},
                            ]
                        },
                    ]
                },
                "propertyDefinitions": [
                    {
                        "key": "avg_length",
                        "valueKind": "FLOAT",
                        "derivation": "ROLLUP",
                        "rule": {
                            "sourceNode": "ROI",
                            "key": "vector_length",
                            "aggregation": "MEAN",
                            "evidence": {"rules": [{"when": [{"field": "APP", "operator": "IS", "value": "segmenter-v3"}]}]},
                        },
                    }
                ],
            },
            {"key": "Cell"},
        ],
        "relations": [
            {
                "key": "IS_CONNECTED_TO",
                "source": {"keys": ["Cell"]},
                "target": {"keys": ["Cell"]},
                "definition": {
                    "rules": [
                        {
                            "when": [
                                {"field": "WORD", "operator": "IS", "value": "IS_CONNECTED_TO"},
                                {"field": "SUBJECT", "operator": "IS", "value": "karl"},
                                {"field": "ASSERTED_AT", "operator": "SINCE", "value": DEC5.isoformat()},
                            ]
                        }
                    ]
                },
            }
        ],
        "events": [
            {
                "key": "Mitosis",
                "kind": "INTRINSIC",
                "definition": {
                    "rules": [
                        {
                            "when": [
                                {"field": "WORD", "operator": "IS", "value": "Mitosis"},
                                {"field": "APP", "operator": "IS", "value": "event-annotator"},
                            ]
                        }
                    ]
                },
                "inputs": [{"key": "Cell", "role": "mother", "descriptor": {"keys": ["Cell"]}}],
                "outputs": [{"key": "Cell", "role": "daughter", "descriptor": {"keys": ["Cell"]}}],
            }
        ],
    },
}


async def _example_graph(api_schema: kante.Schema, ctx: HttpContext, name: str) -> str:
    made = await api_schema.execute(CREATE_GRAPH, variable_values={"input": {"name": name, "definition": DEFINITION}}, context_value=ctx)
    assert made.errors is None, f"GraphQL errors: {made.errors}"
    return made.data["createGraph"]["id"]


def _rebuild(graph_id: str, table_projector) -> core_models.Graph:
    graph = core_models.Graph.objects.get(pk=graph_id)
    GraphController(projector=table_projector).rebuild_projection(graph)
    return graph


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
                        # Peter and Karl decide what exists and what classifies —
                        # but not what is the same (the KIND carve-out).
                        {"when": [
                            {"field": "WORD", "operator": "IN", "value": ["AIS", "AxonInitialSegment"]},
                            {"field": "SUBJECT", "operator": "IN", "value": ["peter", "karl"]},
                            {"field": "KIND", "operator": "NOT_IN", "value": ["SAMENESS"]},
                        ]},
                        # Only the curator may say two of these are one individual.
                        {"when": [
                            {"field": "KIND", "operator": "IS", "value": "SAMENESS"},
                            {"field": "SUBJECT", "operator": "IS", "value": "curator"},
                        ]},
                    ]
                },
            },
            {"key": "Cell"},
        ],
    },
}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_existence_and_sameness_are_distinct_rules(api_schema, simple_api_context, table_projector) -> None:
    """The motivating scenario (RFC 0011): Peter may retract, only the curator may merge."""
    made = await api_schema.execute(CREATE_GRAPH, variable_values={"input": {"name": "kinds-apart", "definition": SAMENESS_DEFINITION}}, context_value=simple_api_context)
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

        merge_as(a1, a2, "curator")   # trusted, same category, two words
        merge_as(b1, b2, "peter")     # carved out of SAMENESS
        merge_as(a1, cell, "curator") # cross-category — never unions in a view

        curator_component = panel.components_for(org, [a1], graph=graph)[a1]
        peters_component = panel.components_for(org, [b1], graph=graph)[b1]
        org_component = panel.components_for(org, [b1])[b1]

        # Existence stays Peter's: his retraction removes his node.
        claims.retract_node(org, b2, "peter")
        GraphController(projector=table_projector).rebuild_projection(graph)
        after_retraction = drawing.vertices_with_ref(graph, b2)
        # The curator's retraction counts for nothing but sameness.
        claims.retract_node(org, b1, "curator")
        GraphController(projector=table_projector).rebuild_projection(graph)
        curator_cannot_retract = drawing.vertices_with_ref(graph, b1)

        return curator_component, peters_component, org_component, after_retraction, curator_cannot_retract, a1, a2, cell

    curator_component, peters_component, org_component, after_retraction, curator_cannot_retract, a1, a2, cell = await story()
    assert sorted(curator_component) == sorted([a1, a2]), "the curator's merge unions two words of ONE category — and never the Cell"
    assert cell not in curator_component, "no cross-category sameness: identity lives within a kind"
    assert peters_component == [str(peters_component[0])] and len(peters_component) == 1, "Peter is carved out of SAMENESS, so his merge does not union here"
    assert len(org_component) == 2, "the organization-grain fold still unions everything — the view disagrees, the log does not"
    assert after_retraction == 0, "Peter still decides existence"
    assert curator_cannot_retract == 1, "the curator's rule covers SAMENESS only — their retraction counts for nothing"
