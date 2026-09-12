"""The namespace is derived from the view: spec from the definition, DDL from the spec (RFC 0006).

Spec tests pin the expansion rules of `graph_engine/namespace.py`; the
round-trip tests hold `refresh_namespace` / `drop_namespace` to the spec against
the live catalogs; and the handle that names the schema is output only, never
an address.
"""

import pytest
from core import models as core_models
from graph_engine import namespace as namespace_module
from asgiref.sync import sync_to_async
from tests.support import drawing, namespaces, reads, writes
import re


def _cat(graph, key):
    return core_models.Category.objects.get(graph=graph, key=key)
@pytest.mark.django_db(transaction=True)
def test_spec_declares_one_vertex_element_per_node_category(test_graph, table_projector) -> None:
    spec = namespace_module.namespace_spec(test_graph)
    assert spec.schema_name == test_graph.age_name
    assert spec.vertex_labels == {"AIS", "Soma", "Cell", "Mitosis"}
    by_label = {vertex.label: vertex for vertex in spec.vertices}
    assert by_label["AIS"].category_pk == _cat(test_graph, "AIS").pk
    assert by_label["AIS"].view_name == f"v{_cat(test_graph, 'AIS').pk}"
@pytest.mark.django_db(transaction=True)
def test_spec_expands_relations_per_admitted_endpoint_pair(test_graph, table_projector) -> None:
    spec = namespace_module.namespace_spec(test_graph)
    cell = _cat(test_graph, "Cell").pk
    ais = _cat(test_graph, "AIS").pk
    soma = _cat(test_graph, "Soma").pk

    connected = [(e.source_pk, e.target_pk) for e in spec.edges if e.label == "IS_CONNECTED_TO"]
    assert connected == [(cell, cell)], "Cell->Cell is the only admitted pair"

    part_of = sorted((e.source_pk, e.target_pk) for e in spec.edges if e.label == "PART_OF")
    assert part_of == sorted([(ais, cell), (soma, cell)]), "one element table per admitted pair"
@pytest.mark.django_db(transaction=True)
def test_spec_participation_encodes_the_drawn_direction(test_graph, table_projector) -> None:
    spec = namespace_module.namespace_spec(test_graph)
    cell = _cat(test_graph, "Cell").pk
    mitosis = _cat(test_graph, "Mitosis").pk

    went_through = [(e.source_pk, e.target_pk) for e in spec.edges if e.label == "WENT_THROUGH"]
    came_out = [(e.source_pk, e.target_pk) for e in spec.edges if e.label == "CAME_OUT_OF"]
    # Inputs run entity -> event; outputs run event -> entity — the writer
    # already flips outputs when drawing, so the spec never flips on read.
    assert went_through == [(cell, mitosis)]
    assert came_out == [(mitosis, cell)]
@pytest.mark.django_db(transaction=True)
def test_spec_gives_measurement_and_structure_relation_categories_nothing(test_graph, table_projector) -> None:
    # Nothing draws them, so a label would declare an element table that is
    # empty by construction.
    labels = {e.label for e in namespace_module.namespace_spec(test_graph).edges}
    assert labels == {"IS_CONNECTED_TO", "PART_OF", "WENT_THROUGH", "CAME_OUT_OF"}
@pytest.mark.django_db(transaction=True)
def test_spec_refuses_an_overlong_label_by_name(test_graph, table_projector) -> None:
    long = "L" * 80
    core_models.Category.objects.filter(pk=_cat(test_graph, "AIS").pk).update(age_name=long)
    with pytest.raises(namespace_module.NamespaceSpecError, match="63 bytes"):
        namespace_module.namespace_spec(test_graph)
@pytest.mark.django_db(transaction=True)
def test_spec_refuses_a_vertex_label_that_is_a_participation_edge_label(test_graph, table_projector) -> None:
    core_models.Category.objects.filter(pk=_cat(test_graph, "AIS").pk).update(age_name="WENT_THROUGH")
    with pytest.raises(namespace_module.NamespaceSpecError, match="participation"):
        namespace_module.namespace_spec(test_graph)
@pytest.mark.django_db(transaction=True)
def test_spec_open_descriptors_expand_and_the_cap_refuses_loudly(test_graph, table_projector, monkeypatch) -> None:
    # Open both descriptors on one relation: every entity-like pair appears.
    relation = _cat(test_graph, "IS_CONNECTED_TO")
    core_models.Category.objects.filter(pk=relation.pk).update(source_definition={}, target_definition={})
    spec = namespace_module.namespace_spec(test_graph)
    open_pairs = [e for e in spec.edges if e.label == "IS_CONNECTED_TO"]
    assert len(open_pairs) == 9, "3 entity categories x 3, the open expansion"

    monkeypatch.setattr(namespace_module, "NAMESPACE_MAX_ELEMENT_TABLES", 5)
    with pytest.raises(namespace_module.NamespaceSpecError, match="IS_CONNECTED_TO"):
        namespace_module.namespace_spec(test_graph)
def _schema_exists(name: str) -> bool:
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", [name])
        return cursor.fetchone() is not None
def _property_graph_labels(schema: str) -> set[str]:
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT pgl.pgllabel
              FROM pg_propgraph_label pgl
              JOIN pg_class c ON c.oid = pgl.pglpgid
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE c.relkind = 'g' AND c.relname = 'graph' AND n.nspname = %s
            """,
            [schema],
        )
        return {row[0] for row in cursor.fetchall()}
@pytest.mark.django_db(transaction=True)
def test_materialize_builds_the_namespace_with_exactly_the_declared_labels(test_graph, table_projector) -> None:
    schema = str(test_graph.age_name)
    assert _schema_exists(schema), "materialize must leave the per-graph schema behind"
    assert _property_graph_labels(schema) == {
        "AIS",
        "Soma",
        "Cell",
        "Mitosis",
        "IS_CONNECTED_TO",
        "PART_OF",
        "WENT_THROUGH",
        "CAME_OUT_OF",
    }
@pytest.mark.django_db(transaction=True)
def test_a_category_write_refreshes_the_namespace(test_graph, table_projector) -> None:
    core_models.EntityCategory.objects.create(graph=test_graph, age_name="Axon", key="Axon", label="Axon")
    assert "Axon" in _property_graph_labels(str(test_graph.age_name)), "the post_save signal must re-derive the namespace"

    core_models.Category.objects.filter(graph=test_graph, key="Axon").delete()
    assert "Axon" not in _property_graph_labels(str(test_graph.age_name)), "the post_delete signal must re-derive it too"
@pytest.mark.django_db(transaction=True)
def test_refresh_is_idempotent_and_deleting_the_graph_drops_the_schema(test_graph, table_projector) -> None:
    table_projector.refresh_namespace(test_graph)
    table_projector.refresh_namespace(test_graph)
    schema = str(test_graph.age_name)
    assert _schema_exists(schema)

    core_models.Graph.objects.filter(pk=test_graph.pk).delete()
    assert not _schema_exists(schema), "no FK cascade reaches DDL; the pre_delete signal is what drops the schema"
@pytest.mark.django_db(transaction=True)
def test_the_property_graph_answers_for_the_drawing(test_graph, table_projector) -> None:
    from django.db import connection

    ais = _cat(test_graph, "AIS")
    ref = "00000000-0000-0000-0000-00000000a15e"
    table_projector.draw_node(test_graph, ref, [(ais.age_name, ais.pk)], "ENTITY", [ref])

    with connection.cursor() as cursor:
        cursor.execute(f'SELECT ref FROM GRAPH_TABLE ("{test_graph.age_name}".graph MATCH (a IS "AIS") COLUMNS (a.__ref AS ref))')
        assert [row[0] for row in cursor.fetchall()] == [ref]
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
HANDLE = re.compile(r"^g[0-9a-f]{32}$")
def test_two_graphs_with_one_name_get_distinct_random_handles(transactional_db, table_projector, minimal_schema, authenticated_context) -> None:
    """Same name, same organization, twice — two handles, neither derived from the name."""
    from graph_engine.materialize import materialize

    request = authenticated_context.request
    kwargs = dict(user=request._user, organization=request._organization, membership=request.membership, name="Twins")

    first = materialize(minimal_schema, table_projector, **kwargs)
    second = materialize(minimal_schema, table_projector, **kwargs)

    assert first.pk != second.pk
    assert first.age_name != second.age_name
    for graph in (first, second):
        assert HANDLE.match(graph.age_name), f"{graph.age_name!r} is not an opaque handle"
        assert "twins" not in graph.age_name.lower(), "the handle must not be derived from the name"
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_graph_argument_is_a_primary_key_not_the_handle(api_schema, simple_api_context, test_graph: core_models.Graph) -> None:
    """`graph: "<age_name>"` is refused; the same read by id succeeds."""
    entity_id = await writes.create_entity(api_schema, simple_api_context, "AIS")

    by_handle = await api_schema.execute(reads.NODE, variable_values={"id": entity_id, "graph": str(test_graph.age_name)}, context_value=simple_api_context)
    assert by_handle.errors, "the namespace handle must not address a graph"
    assert "by its id" in str(by_handle.errors[0]), f"Refused for the wrong reason: {by_handle.errors[0]}"

    by_id = await api_schema.execute(reads.NODE, variable_values={"id": entity_id, "graph": str(test_graph.pk)}, context_value=simple_api_context)
    assert by_id.errors is None, f"GraphQL errors: {by_id.errors}"
    assert by_id.data["node"]["id"] == entity_id
@pytest.mark.django_db(transaction=True)
def test_a_graph_row_needs_no_handle_to_be_created(test_graph: core_models.Graph) -> None:
    """The default supplies it, so fixtures and callers never invent one."""
    graph = core_models.Graph.objects.create(
        name="Handle-less",
        user=test_graph.user,
        membership=test_graph.membership,
        organization=test_graph.organization,
    )
    assert HANDLE.match(graph.age_name)
@pytest.mark.django_db(transaction=True)
def test_deleting_a_graph_row_drops_its_namespace(test_graph: core_models.Graph, table_projector) -> None:
    table_projector.draw_node(test_graph, "00000000-0000-0000-0000-000000000001", [("Cell", None)], "ENTITY", ["00000000-0000-0000-0000-000000000001"])
    assert drawing.vertex_count(test_graph) == 1
    core_models.Graph.objects.filter(pk=test_graph.pk).delete()
    assert drawing.vertex_count(test_graph) == 0, "a deleted view takes its drawing with it, on every deletion path"
