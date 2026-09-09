"""The database refuses a drawing under a category the view does not declare (A7, RFC 0006).

A composite foreign key ties every drawn label's `(graph, category_pk)` to a
category of the same view; a deleted category cascades exactly its own labels,
and the vertex only when no label is left; a NULL `category_pk` still passes,
because rows an older projector drew carry it and `reproject` is their repair.
"""

import uuid
import pytest
from django.db import IntegrityError, transaction
from core import models as core_models
from graph_engine import models as graph_engine_models
from tests.support import drawing


def _category(graph: core_models.Graph, key: str) -> core_models.Category:
    return core_models.Category.objects.get(graph=graph, key=key)


def _bare_vertex(graph: core_models.Graph) -> graph_engine_models.ProjectionVertex:
    return graph_engine_models.ProjectionVertex.objects.create(graph=graph, ref=uuid.uuid4(), kind="ENTITY")


@pytest.mark.django_db(transaction=True)
def test_a_category_of_another_graph_is_refused(test_graph, bio_graph, table_projector) -> None:
    foreign = _category(bio_graph, "AIS")
    vertex = _bare_vertex(test_graph)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            graph_engine_models.ProjectionLabel.objects.create(graph=test_graph, vertex=vertex, label="AIS", category_pk=foreign.pk)


@pytest.mark.django_db(transaction=True)
def test_an_invented_category_id_is_refused(test_graph, table_projector) -> None:
    vertex = _bare_vertex(test_graph)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            graph_engine_models.ProjectionLabel.objects.create(graph=test_graph, vertex=vertex, label="AIS", category_pk=999999)


@pytest.mark.django_db(transaction=True)
def test_updating_a_label_onto_a_foreign_category_is_refused(test_graph, bio_graph, table_projector) -> None:
    own = _category(test_graph, "AIS")
    foreign = _category(bio_graph, "AIS")
    ref = uuid.uuid4()
    table_projector.draw_node(test_graph, str(ref), [(own.age_name, own.pk)], "ENTITY", [str(ref)])
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            graph_engine_models.ProjectionLabel.objects.filter(graph=test_graph, vertex__ref=ref).update(category_pk=foreign.pk)


@pytest.mark.django_db(transaction=True)
def test_deleting_a_category_cascades_its_drawings_and_only_its_drawings(test_graph, table_projector) -> None:
    ais = _category(test_graph, "AIS")
    cell = _category(test_graph, "Cell")
    ais_ref, cell_ref = uuid.uuid4(), uuid.uuid4()
    table_projector.draw_node(test_graph, str(ais_ref), [(ais.age_name, ais.pk)], "ENTITY", [str(ais_ref)])
    table_projector.draw_node(test_graph, str(cell_ref), [(cell.age_name, cell.pk)], "ENTITY", [str(cell_ref)])
    assert table_projector.draw_edge(test_graph, str(ais_ref), str(cell_ref), "TOUCHES", {})

    core_models.Category.objects.filter(pk=ais.pk).delete()

    vertices = graph_engine_models.ProjectionVertex.objects.filter(graph=test_graph)
    assert not vertices.filter(ref=ais_ref).exists(), "the deleted category's vertex must go with it — its last label went, so the trigger takes the vertex"
    assert vertices.filter(ref=cell_ref).exists(), "another category's vertex must stay"
    assert not graph_engine_models.ProjectionEdge.objects.filter(graph=test_graph).exists(), "edges touching the erased vertex go by cascade — the DETACH"
    members = graph_engine_models.ProjectionMember.objects.filter(graph=test_graph)
    assert not members.filter(ref=ais_ref).exists(), "the erased vertex's member rows go by the same SQL-level cascade (migration 0007)"
    assert members.filter(ref=cell_ref).exists()


@pytest.mark.django_db(transaction=True)
def test_deleting_one_of_a_vertexs_categories_keeps_the_vertex(test_graph, table_projector) -> None:
    """RFC 0019: a vertex under two categories loses one label, not itself."""
    ais = _category(test_graph, "AIS")
    soma = _category(test_graph, "Soma")
    ref = str(uuid.uuid4())
    table_projector.draw_node(test_graph, ref, [(ais.age_name, ais.pk), (soma.age_name, soma.pk)], "ENTITY", [ref])

    core_models.Category.objects.filter(pk=soma.pk).delete()

    labels = set(graph_engine_models.ProjectionLabel.objects.filter(graph=test_graph, vertex__ref=ref).values_list("label", flat=True))
    assert labels == {ais.age_name}
    assert graph_engine_models.ProjectionVertex.objects.filter(graph=test_graph, ref=ref).exists()
    assert graph_engine_models.ProjectionMember.objects.filter(graph=test_graph, ref=ref).exists()


@pytest.mark.django_db(transaction=True)
def test_a_null_category_still_passes(test_graph, table_projector) -> None:
    # Rows an older projector drew have no category stamp; the constraint is
    # MATCH SIMPLE, so they survive until a reproject re-draws them.
    ref = str(uuid.uuid4())
    table_projector.draw_node(test_graph, ref, [("Cell", None)], "ENTITY", [ref])


@pytest.mark.django_db(transaction=True)
def test_deleting_one_category_keeps_the_vertex_under_the_other(test_graph, table_projector) -> None:
    """The composite FK cascades the deleted category's *label*; the vertex
    stays while another label holds it, and goes with its last one."""
    from graph_engine import models as projection_models

    ais = core_models.Category.objects.get(graph=test_graph, key="AIS")
    soma = core_models.Category.objects.get(graph=test_graph, key="Soma")
    ref = "00000000-0000-0000-0000-00000000a15e"
    table_projector.draw_node(test_graph, ref, [(ais.age_name, ais.pk), (soma.age_name, soma.pk)], "ENTITY", [ref])
    assert drawing.labels_of(test_graph, ref) == {ais.age_name, soma.age_name}

    core_models.Category.objects.filter(pk=soma.pk).delete()
    assert drawing.labels_of(test_graph, ref) == {ais.age_name}
    assert projection_models.ProjectionVertex.objects.filter(graph=test_graph, ref=ref).exists()

    core_models.Category.objects.filter(pk=ais.pk).delete()
    assert not projection_models.ProjectionVertex.objects.filter(graph=test_graph, ref=ref).exists(), "no label left, no vertex"
    assert not projection_models.ProjectionMember.objects.filter(graph=test_graph, ref=ref).exists()
