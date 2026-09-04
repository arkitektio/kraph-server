"""The database, not just `resolve_categories`, decides what ends up in a graph.

A composite foreign key ties every drawn vertex's `(graph, category_pk)` to a
`core_category` row of the *same* graph (graph_engine migration
`0005_vertex_category_fk`, RFC 0006). These tests pin the three behaviors the
code relies on: a foreign or invented category is refused at the row level, a
deleted category cascades exactly its own drawings (edges going by the existing
vertex cascade — the DETACH), and a NULL `category_pk` still passes, because
rows an older projector drew carry it and `manage.py reproject` is their repair,
not an IntegrityError.
"""

import uuid

import pytest
from django.db import IntegrityError, transaction

from core import models as core_models
from graph_engine import models as graph_engine_models


def _category(graph: core_models.Graph, key: str) -> core_models.Category:
    return core_models.Category.objects.get(graph=graph, key=key)


@pytest.mark.django_db(transaction=True)
def test_a_category_of_another_graph_is_refused(test_graph, bio_graph, table_projector) -> None:
    foreign = _category(bio_graph, "AIS")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            graph_engine_models.ProjectionVertex.objects.create(
                graph=test_graph, ref=uuid.uuid4(), label="AIS", category_pk=foreign.pk, kind="ENTITY"
            )


@pytest.mark.django_db(transaction=True)
def test_an_invented_category_id_is_refused(test_graph, table_projector) -> None:
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            graph_engine_models.ProjectionVertex.objects.create(
                graph=test_graph, ref=uuid.uuid4(), label="AIS", category_pk=999999, kind="ENTITY"
            )


@pytest.mark.django_db(transaction=True)
def test_updating_a_vertex_onto_a_foreign_category_is_refused(test_graph, bio_graph, table_projector) -> None:
    own = _category(test_graph, "AIS")
    foreign = _category(bio_graph, "AIS")
    ref = uuid.uuid4()
    table_projector.draw_node(test_graph, str(ref), own.age_name, own.pk, "ENTITY", [str(ref)])
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            graph_engine_models.ProjectionVertex.objects.filter(graph=test_graph, ref=ref).update(category_pk=foreign.pk)


@pytest.mark.django_db(transaction=True)
def test_deleting_a_category_cascades_its_drawings_and_only_its_drawings(test_graph, table_projector) -> None:
    ais = _category(test_graph, "AIS")
    cell = _category(test_graph, "Cell")
    ais_ref, cell_ref = uuid.uuid4(), uuid.uuid4()
    table_projector.draw_node(test_graph, str(ais_ref), ais.age_name, ais.pk, "ENTITY", [str(ais_ref)])
    table_projector.draw_node(test_graph, str(cell_ref), cell.age_name, cell.pk, "ENTITY", [str(cell_ref)])
    assert table_projector.draw_edge(test_graph, str(ais_ref), str(cell_ref), "TOUCHES", {})

    core_models.Category.objects.filter(pk=ais.pk).delete()

    vertices = graph_engine_models.ProjectionVertex.objects.filter(graph=test_graph)
    assert not vertices.filter(ref=ais_ref).exists(), "the deleted category's vertex must go with it"
    assert vertices.filter(ref=cell_ref).exists(), "another category's vertex must stay"
    assert not graph_engine_models.ProjectionEdge.objects.filter(graph=test_graph).exists(), "edges touching the erased vertex go by cascade — the DETACH"
    members = graph_engine_models.ProjectionMember.objects.filter(graph=test_graph)
    assert not members.filter(ref=ais_ref).exists(), "the erased vertex's member rows go by the same SQL-level cascade (migration 0007)"
    assert members.filter(ref=cell_ref).exists()


@pytest.mark.django_db(transaction=True)
def test_a_null_category_still_passes(test_graph, table_projector) -> None:
    # Rows an older projector drew have no category stamp; the constraint is
    # MATCH SIMPLE, so they survive until a reproject re-draws them.
    ref = str(uuid.uuid4())
    table_projector.draw_node(test_graph, ref, "Cell", None, "ENTITY", [ref])
