"""A definition is a union of clauses: word x annotator x time, per clause.

The headline scenario (RFC 0007): "in this graph, 'Cell' means what Peter
called 'Cell' and what Karl called 'StemCell' after Dec 5" — several people's
words subsumed under one label, without the cross-product the flat form smears
across every clause (Karl's Cells, Peter's StemCells). The literal view beside
it sees the same five claims under their own words: same evidence, different
knowledge, now across annotator and time as well as aggregation.
"""

from datetime import datetime, timezone

import pytest
from asgiref.sync import sync_to_async

from core import models as core_models
from graph_engine import input_models
from graph_engine.controller import GraphController
from graph_engine.materialize import materialize
from tests import claims, namespaces, writes

PETER = "peter"
KARL = "karl"
DEC_1 = datetime(2026, 12, 1, tzinfo=timezone.utc)
DEC_10 = datetime(2026, 12, 10, tzinfo=timezone.utc)


async def _five_claims(api_schema, ctx, literal_graph) -> dict[str, str]:
    """Five entities, one annotator claim each — the shared evidence.

    Creation mints the word under the request's own subject (which no clause
    names); the annotator claims are writer-level so subject and belief time
    are chosen, not inherited.
    """
    c1 = await writes.create_entity(api_schema, ctx, "Cell")
    c2 = await writes.create_entity(api_schema, ctx, "Cell")
    c3 = await writes.create_entity(api_schema, ctx, "StemCell")
    c4 = await writes.create_entity(api_schema, ctx, "StemCell")
    c5 = await writes.create_entity(api_schema, ctx, "StemCell")

    @sync_to_async
    def annotate():
        cell = core_models.Category.objects.get(graph=literal_graph, key="Cell")
        stem = core_models.Category.objects.get(graph=literal_graph, key="StemCell")
        claims.classify(literal_graph, c1, cell, PETER)
        claims.classify(literal_graph, c2, cell, KARL)
        claims.classify(literal_graph, c3, stem, PETER)
        claims.classify(literal_graph, c4, stem, KARL, asserted_at=DEC_1)
        claims.classify(literal_graph, c5, stem, KARL, asserted_at=DEC_10)

    await annotate()
    return {"c1": c1, "c2": c2, "c3": c3, "c4": c4, "c5": c5}


def _rebuild(table_projector, graph) -> None:
    GraphController(projector=table_projector).rebuild_projection(graph)


def _defined_graph(request, name: str, key: str, definition: input_models.CategoryDefinitionInput) -> core_models.Graph:
    """One graph whose single category's meaning is declared **in the schema** —
    the definition document carries the predicate (RFC 0007)."""
    return materialize(
        input_models.GraphDefinitionInput(
            system_version="1.0.0",
            extensions=input_models.GraphExtensionsInput(entities=[input_models.EntityDefinitionInput(key=key, definition=definition)]),
        ),
        None,
        user=request._user,
        organization=request._organization,
        membership=request.membership,
        name=name,
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_category_subsumes_word_annotator_time_clauses(api_schema, simple_api_context, subsumption_graph, literal_graph, table_projector) -> None:
    refs = await _five_claims(api_schema, simple_api_context, literal_graph)

    @sync_to_async
    def views():
        _rebuild(table_projector, subsumption_graph)
        subsumed = namespaces.graph_table(subsumption_graph, 'MATCH (c IS "Cell") COLUMNS (c.__ref AS ref, c.__label AS label)')
        literal_cells = namespaces.graph_table(literal_graph, 'MATCH (c IS "Cell") COLUMNS (c.__ref AS ref)')
        literal_stems = namespaces.graph_table(literal_graph, 'MATCH (s IS "StemCell") COLUMNS (s.__ref AS ref)')
        return subsumed, literal_cells, literal_stems

    subsumed, literal_cells, literal_stems = await views()
    assert {row[0] for row in subsumed} == {refs["c1"], refs["c5"]}, "Peter's Cell and Karl's post-Dec-5 StemCell, nothing else"
    assert {row[1] for row in subsumed} == {"Cell"}, "both drawn under this view's one word"
    assert {row[0] for row in literal_cells} == {refs["c1"], refs["c2"]}, "the literal view keeps every claim under its own word"
    assert {row[0] for row in literal_stems} == {refs["c3"], refs["c4"], refs["c5"]}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_clauses_do_not_cross_multiply(api_schema, simple_api_context, subsumption_graph, literal_graph, table_projector, authenticated_context) -> None:
    """The exact wrong answers the flat form gives, pinned on both sides.

    Karl's Cell, Peter's StemCell and Karl's early StemCell each combine a word
    from one clause with an annotator or a time from another. The clause form
    excludes all three; the flat encoding of the same intent admits every one.
    """
    refs = await _five_claims(api_schema, simple_api_context, literal_graph)
    request = authenticated_context.request

    @sync_to_async
    def both_encodings():
        _rebuild(table_projector, subsumption_graph)
        subsumed = {row[0] for row in namespaces.graph_table(subsumption_graph, 'MATCH (c IS "Cell") COLUMNS (c.__ref AS ref)')}

        flat_graph = _defined_graph(
            request,
            "flat-cross-product",
            "Cell",
            # One asserted_as list, one subject list: the binding is lost.
            input_models.CategoryDefinitionInput(asserted_as=["Cell", "StemCell"], assertion_filter=input_models.AssertionFilterInput(subjects=[PETER, KARL])),
        )
        _rebuild(table_projector, flat_graph)
        flat = {row[0] for row in namespaces.graph_table(flat_graph, 'MATCH (c IS "Cell") COLUMNS (c.__ref AS ref)')}
        return subsumed, flat

    subsumed, flat = await both_encodings()
    for wrong in ("c2", "c3", "c4"):
        assert refs[wrong] not in subsumed, f"{wrong} combines clauses and must not be admitted"
    assert flat == set(refs.values()), "the flat cross-product admits all five — the reason clauses exist"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_flat_since_bound_admits_only_later_claims(api_schema, simple_api_context, literal_graph, table_projector, authenticated_context) -> None:
    refs = await _five_claims(api_schema, simple_api_context, literal_graph)
    request = authenticated_context.request

    @sync_to_async
    def late_stems():
        graph = _defined_graph(
            request,
            "late-stems",
            "LateStem",
            input_models.CategoryDefinitionInput(asserted_as=["StemCell"], assertion_filter=input_models.AssertionFilterInput(subjects=[KARL]), since=datetime(2026, 12, 5, tzinfo=timezone.utc)),
        )
        _rebuild(table_projector, graph)
        return {row[0] for row in namespaces.graph_table(graph, 'MATCH (s IS "LateStem") COLUMNS (s.__ref AS ref)')}

    assert await late_stems() == {refs["c5"]}, "Dec 1 is before the bound, Dec 10 after — `since` is the lower half `as_of` never had"
