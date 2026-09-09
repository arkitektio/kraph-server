"""The namespace is a derived artifact: spec from the schema, DDL from the spec.

Spec tests pin the expansion rules of `graph_engine/namespace.py` — which element
tables one graph's categories declare, in which direction participation runs, and
the loud refusals (blowup cap, over-long labels, label collisions with the
participation constants). The round-trip tests then hold `refresh_namespace` /
`drop_namespace` to the spec against the live catalogs (RFC 0006).
"""

import pytest

from core import models as core_models
from graph_engine import namespace as namespace_module


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


# ---------------------------------------------------------------------------
# Round trips: the spec against the live catalogs.
# ---------------------------------------------------------------------------


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


UPDATE_GRAPH_VISUAL = """
    mutation UpdateGraphVisual($input: UpdateGraphVisualInput!) {
        updateGraphVisual(input: $input) { id }
    }
"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_moving_a_box_runs_no_ddl(api_schema, simple_api_context, test_graph, table_projector, monkeypatch) -> None:
    """Layout is presentation. `updateGraphVisual` used to `save()` each category,
    and the category-write signal then dropped and recreated the graph's whole
    Postgres schema once per moved box."""
    from asgiref.sync import sync_to_async

    from graph_engine.projection import table as table_module

    def refuse(*args, **kwargs):
        raise AssertionError("a layout change must not touch the namespace")

    monkeypatch.setattr(table_module.TableProjector, "refresh_namespace", refuse)

    category = await sync_to_async(core_models.Category.objects.get)(graph=test_graph, key="AIS")
    result = await api_schema.execute(
        UPDATE_GRAPH_VISUAL,
        variable_values={"input": {"id": str(test_graph.pk), "nodePositions": [{"category": str(category.pk), "positionX": 3.0, "positionY": 4.0}]}},
        context_value=simple_api_context,
    )
    assert result.errors is None, f"GraphQL errors: {result.errors}"

    await sync_to_async(category.refresh_from_db)()
    assert (category.position_x, category.position_y) == (3.0, 4.0)
