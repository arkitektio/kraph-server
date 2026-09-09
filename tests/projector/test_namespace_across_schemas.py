"""The namespace machinery against different shapes of schema.

`test_namespace.py` pins the mechanics over the bio fixture. These tests run
the same machinery over deliberately different views — the smallest possible
schema, open descriptors beside closed ones, the protocol lane with reagents,
and a **consensus pair**: two graphs declaring the same word, where one write
draws in both and each namespace answers only for its own view.
"""

import pytest
from asgiref.sync import sync_to_async

from core import models as core_models
from graph_engine import namespace as namespace_module
from tests.support import namespaces, writes


def _cat(graph, key):
    return core_models.Category.objects.get(graph=graph, key=key)


# ---------------------------------------------------------------------------
# Minimal: one word, no edges.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_smallest_schema_gets_a_working_namespace(api_schema, simple_api_context, minimal_graph, table_projector) -> None:
    @sync_to_async
    def the_spec():
        spec = namespace_module.namespace_spec(minimal_graph)
        return spec.vertex_labels, spec.edges, namespaces.property_graph_labels(minimal_graph.age_name)

    vertex_labels, edges, declared = await the_spec()
    assert vertex_labels == {"Specimen"}
    assert edges == (), "no relations, no events — no edge element tables"
    assert declared == {"Specimen"}

    specimen = await writes.create_entity(api_schema, simple_api_context, "Specimen")

    @sync_to_async
    def match():
        return namespaces.graph_table(minimal_graph, 'MATCH (s IS "Specimen") COLUMNS (s.__ref AS ref)')

    assert [row[0] for row in await match()] == [specimen]


# ---------------------------------------------------------------------------
# Open descriptors beside closed ones.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_open_descriptors_expand_and_closed_ones_do_not(interactome_graph, table_projector) -> None:
    spec = namespace_module.namespace_spec(interactome_graph)
    open_pairs = {(e.source_pk, e.target_pk) for e in spec.edges if e.label == "INTERACTS_WITH"}
    closed_pairs = {(e.source_pk, e.target_pk) for e in spec.edges if e.label == "BINDS"}

    protein, complex_, site = (_cat(interactome_graph, key).pk for key in ("Protein", "Complex", "Site"))
    assert open_pairs == {(a, b) for a in (protein, complex_, site) for b in (protein, complex_, site)}, "an open descriptor admits every entity pair"
    assert closed_pairs == {(protein, site)}, "a closed descriptor admits exactly what it names"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_open_relation_between_any_pair_renders(api_schema, simple_api_context, interactome_graph, table_projector) -> None:
    complex_ = await writes.create_entity(api_schema, simple_api_context, "Complex")
    site = await writes.create_entity(api_schema, simple_api_context, "Site")
    await writes.create_relation(api_schema, simple_api_context, "interacts_with", complex_, site)

    @sync_to_async
    def match():
        return namespaces.graph_table(
            interactome_graph,
            'MATCH (a)-[IS "INTERACTS_WITH"]->(b) COLUMNS (a.__label AS source, b.__label AS target)',
        )

    assert await match() == [("Complex", "Site")], "unlabelled endpoints span every vertex label, and the open pair is in the graph"


# ---------------------------------------------------------------------------
# The protocol lane: protocol events, added after materialize.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_protocol_event_categories_land_in_the_namespace(lab_graph, table_projector) -> None:
    # Created through the ORM *after* materialize — the label being present is
    # the category-write signal having refreshed the namespace.
    assert namespaces.property_graph_labels(lab_graph.age_name) == {"Sample", "Slide", "Fixation", "SUBJECTED_IN", "PRODUCED"}

    spec = namespace_module.namespace_spec(lab_graph)
    sample, slide, fixation = (_cat(lab_graph, key).pk for key in ("Sample", "Slide", "Fixation"))
    assert {(e.source_pk, e.target_pk) for e in spec.edges if e.label == "SUBJECTED_IN"} == {(sample, fixation)}, "the role's descriptor narrows the input side to Sample"
    assert {(e.source_pk, e.target_pk) for e in spec.edges if e.label == "PRODUCED"} == {(fixation, slide)}, "and the output side to Slide, in the drawn (event -> entity) direction"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_protocol_event_renders_as_two_hops(api_schema, simple_api_context, lab_graph, table_projector) -> None:
    sample = await writes.create_entity(api_schema, simple_api_context, "Sample")
    slide = await writes.create_entity(api_schema, simple_api_context, "Slide")
    await writes.create_event(
        api_schema,
        simple_api_context,
        "Fixation",
        protocol=True,
        inputs=[{"role": "specimen", "entityId": sample}],
        outputs=[{"role": "mounted", "entityId": slide}],
    )

    @sync_to_async
    def match():
        return namespaces.graph_table(
            lab_graph,
            'MATCH (s IS "Sample")-[i IS "SUBJECTED_IN"]->(f IS "Fixation")-[o IS "PRODUCED"]->(t IS "Slide") COLUMNS (s.__ref AS sample, i.__eprops ->> \'role\' AS in_role, o.__eprops ->> \'role\' AS out_role, t.__ref AS slide)',
        )

    assert await match() == [(sample, "specimen", "mounted", slide)]


# ---------------------------------------------------------------------------
# Consensus: two views, one word.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_shared_word_draws_in_every_declaring_view(api_schema, simple_api_context, cytology_graph, oncology_graph, table_projector) -> None:
    """One claim, two graphs: the write fans out, and each namespace answers
    for its own view — same ref, that view's own category."""
    cell = await writes.create_entity(api_schema, simple_api_context, "Cell")

    @sync_to_async
    def per_view():
        results = {}
        for graph in (cytology_graph, oncology_graph):
            rows = namespaces.graph_table(graph, 'MATCH (c IS "Cell") COLUMNS (c.__ref AS ref, c.__category_id AS category)')
            results[graph.name] = rows
        return results, _cat(cytology_graph, "Cell").pk, _cat(oncology_graph, "Cell").pk

    seen, cytology_cell, oncology_cell = await per_view()
    assert [row[0] for row in seen["cytology"]] == [cell]
    assert [row[0] for row in seen["oncology"]] == [cell]
    assert seen["cytology"][0][1] == cytology_cell
    assert seen["oncology"][0][1] == oncology_cell
    assert cytology_cell != oncology_cell, "the same claim is drawn under each view's own rule"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_word_only_one_view_declares_stays_in_that_view(api_schema, simple_api_context, cytology_graph, oncology_graph, table_projector) -> None:
    cell = await writes.create_entity(api_schema, simple_api_context, "Cell")
    tumor = await writes.create_entity(api_schema, simple_api_context, "Tumor")
    await writes.create_relation(api_schema, simple_api_context, "part_of", cell, tumor)

    @sync_to_async
    def check():
        oncology_rows = namespaces.graph_table(oncology_graph, 'MATCH (a IS "Cell")-[IS "PART_OF"]->(b IS "Tumor") COLUMNS (a.__ref AS cell, b.__ref AS tumor)')
        cytology_labels = namespaces.property_graph_labels(cytology_graph.age_name)
        return oncology_rows, cytology_labels

    oncology_rows, cytology_labels = await check()
    assert oncology_rows == [(cell, tumor)], "the declaring view draws and renders the relation"
    assert "PART_OF" not in cytology_labels and "Tumor" not in cytology_labels, "the other view's namespace has no such words"


@pytest.mark.django_db(transaction=True)
def test_render_labels_resolve_against_the_view_in_scope(cytology_graph, oncology_graph, table_projector) -> None:
    """The same plan means different things per view — and an undeclared word
    is refused by name, not silently empty."""
    from graph_engine import input_models
    from graph_engine.projection.table import compile_table_plan_sql
    from graph_engine.query_ir import TableQueryPlan

    plan = TableQueryPlan(
        matches=[input_models.MatchPathInput(title="p", nodes=["t"], relations=[], node_categories=["Tumor"])],
        returns=[input_models.ReturnStatementInput(path="p", node="t", property="id", alias="tumor_id")],
    )
    sql, _ = compile_table_plan_sql(table_projector, plan, graph=oncology_graph)
    assert f'"{oncology_graph.age_name}".graph' in sql

    with pytest.raises(ValueError, match="Tumor"):
        compile_table_plan_sql(table_projector, plan, graph=cytology_graph)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_same_metrics_read_differently_under_each_views_rule(api_schema, simple_api_context, cytology_graph, oncology_graph, table_projector) -> None:
    """Same claims, different knowledge — the derivation-rule half.

    One entity, two metric claims (`ROI.size` = 10 and 30). Cytology's rule for
    `Cell.size` is MEAN, oncology's is MAX: identical evidence, and each view's
    drawn vertex carries its own answer. Nothing view-specific is stored in the
    evidence — the divergence exists only in the drawings.
    """
    cell = await writes.create_entity(
        api_schema,
        simple_api_context,
        "Cell",
        evidence=[
            {"identifier": "ROI", "object": "roi-small", "metrics": [{"key": "size", "value": 10.0, "valueKind": "FLOAT"}]},
            {"identifier": "ROI", "object": "roi-large", "metrics": [{"key": "size", "value": 30.0, "valueKind": "FLOAT"}]},
        ],
    )

    @sync_to_async
    def sizes():
        results = {}
        for graph in (cytology_graph, oncology_graph):
            rows = namespaces.graph_table(graph, "MATCH (c IS \"Cell\") COLUMNS (c.__ref AS ref, (c.__props ->> 'size')::float AS size)")
            results[graph.name] = rows
        return results

    seen = await sizes()
    assert seen["cytology"] == [(cell, 20.0)], "cytology's rule is MEAN: (10 + 30) / 2"
    assert seen["oncology"] == [(cell, 30.0)], "oncology's rule is MAX, over the very same metric claims"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_view_reads_another_words_claims_under_its_own_name(api_schema, simple_api_context, cytology_graph, census_graph, table_projector) -> None:
    """Same claims, different knowledge — the definitional half.

    The census view declares no word of its own: its one category *derives*
    from `Cell` (a WORD condition in its definition). A claim written under `Cell` draws
    in cytology under the label `Cell` and in census under `ObservedCell` —
    one claim, two vocabularies, and neither view owns the evidence.
    """
    cell = await writes.create_entity(api_schema, simple_api_context, "Cell")

    @sync_to_async
    def per_view():
        census_labels = namespaces.property_graph_labels(census_graph.age_name)
        cytology_rows = namespaces.graph_table(cytology_graph, 'MATCH (c IS "Cell") COLUMNS (c.__ref AS ref, c.__label AS label)')
        census_rows = namespaces.graph_table(census_graph, 'MATCH (c IS "ObservedCell") COLUMNS (c.__ref AS ref, c.__label AS label)')
        return census_labels, cytology_rows, census_rows

    census_labels, cytology_rows, census_rows = await per_view()
    assert census_labels == {"ObservedCell"}, "the census namespace declares only its own word"
    assert cytology_rows == [(cell, "Cell")]
    assert census_rows == [(cell, "ObservedCell")], "the same claim, drawn under this view's own word"
