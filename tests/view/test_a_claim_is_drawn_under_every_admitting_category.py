"""A node is drawn under every category of the view that admits it (RFC 0019).

A vertex used to carry one label — an Apache AGE limitation the table
projection never had, kept alive by `resolve_categories` refusing any node two
definitions admitted. "Pyramidal" and "Excitatory" are not a disagreement: a
cell can be both, and a view that declares both words draws the cell under
both. What was a refusal is now the union.

What stays a refusal is a **property** two of the node's categories both
define under different rules, because one vertex has one value per key and
picking either category's would bury the other's.
"""

import kante
import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext
from core import models as core_models
from graph_engine import projector as projector_module
from tests.support import claims, drawing, graphs, reads, rules, writes


JOHANNES = "johannes"
CHRISTIAN = "christian"
ENTITIES = """
    query Entities($category: ID!) {
        entities(entityCategoryId: $category) { id }
    }
"""
def _rollup(key: str, aggregation: str) -> dict:
    return {"key": key, "value_kind": "FLOAT", "derivation": "ROLLUP", "rule": {"source_node": "ROI", "key": "vector_length", "aggregation": aggregation}}
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_node_two_categories_admit_is_drawn_once_under_both(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """One vertex, two labels — not a refusal, and not two vertices."""

    await writes.create_entity(api_schema, simple_api_context, "AIS")

    @sync_to_async
    def both_admit_it() -> tuple[str, dict]:
        node = claims.only_instance(test_graph)
        ais = graphs.define_entity(test_graph, "AIS", rules.definition(rules.rule(rules.word("AIS"), rules.by(JOHANNES))))
        graphs.define_entity(test_graph, "Excitatory", rules.definition(rules.rule(rules.word("AIS"), rules.by(CHRISTIAN))))
        claims.retract_classifications(test_graph, node.ref)
        claims.classify(test_graph, node.ref, ais, JOHANNES)
        claims.classify(test_graph, node.ref, ais, CHRISTIAN)
        return str(node.ref), graphs.rebuild(test_graph, table_projector)

    ref, result = await both_admit_it()
    assert result["nodes"] == 1, "The node is drawn — a second admitting category is not an ambiguity"
    assert result["unclassified"] == 0

    @sync_to_async
    def drawn() -> tuple[int, set[str], int, int]:
        return drawing.vertices_with_ref(test_graph, ref), drawing.labels_of(test_graph, ref), drawing.vertex_count(test_graph, "ais"), drawing.vertex_count(test_graph, "excitatory")

    vertices, labels, ais_count, excitatory_count = await drawn()
    assert vertices == 1, "one individual, one vertex"
    assert labels == {"ais", "excitatory"}
    assert ais_count == 1 and excitatory_count == 1, "and it counts under each label"
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_it_is_listed_under_each_category_and_in_each_namespace_view(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """`entities(category:)` for either category lists it, and so does the
    category's element table in the property graph."""

    from django.db import connection

    ref = await writes.create_entity(api_schema, simple_api_context, "AIS")

    @sync_to_async
    def both_admit_it() -> tuple[int, int]:
        ais = graphs.define_entity(test_graph, "AIS", rules.definition(rules.rule(rules.word("AIS"))))
        excitatory = graphs.define_entity(test_graph, "Excitatory", rules.definition(rules.rule(rules.word("AIS"))))
        graphs.rebuild(test_graph, table_projector)
        return ais.pk, excitatory.pk

    ais_pk, excitatory_pk = await both_admit_it()

    for pk in (ais_pk, excitatory_pk):
        listed = await api_schema.execute(ENTITIES, variable_values={"category": str(pk)}, context_value=simple_api_context)
        assert listed.errors is None, f"GraphQL errors: {listed.errors}"
        assert [row["id"] for row in listed.data["entities"]] == [ref]

    @sync_to_async
    def in_property_graph() -> dict[str, list[str]]:
        found = {}
        with connection.cursor() as cursor:
            for label in ("ais", "excitatory"):
                cursor.execute(f'SELECT ref FROM GRAPH_TABLE ("{test_graph.age_name}".graph MATCH (a IS "{label}") COLUMNS (a.__ref AS ref))')
                found[label] = [row[0] for row in cursor.fetchall()]
        return found

    assert await in_property_graph() == {"ais": [ref], "excitatory": [ref]}
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_properties_are_the_union_over_the_categories(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """AIS derives `avg_length`; Excitatory derives `max_length`; the vertex has both."""

    ref = await writes.create_entity(api_schema, simple_api_context, "AIS")

    @sync_to_async
    def measure_and_rebuild() -> dict:
        graphs.define_entity(test_graph, "AIS", rules.definition(rules.rule(rules.word("AIS"))))
        graphs.define_entity(test_graph, "Excitatory", rules.definition(rules.rule(rules.word("AIS"))), properties=[_rollup("max_length", "MAX")])
        for obj, value in (("roi-1", 2.0), ("roi-2", 4.0)):
            claims.measure(test_graph.organization, ref, obj=obj, key="vector_length", value=value, subject=JOHANNES)
        graphs.rebuild(test_graph, table_projector)
        return drawing.vertex_properties(test_graph, ref)

    properties = await measure_and_rebuild()
    assert properties["avg_length"] == 3.0, "AIS's rule"
    assert properties["max_length"] == 4.0, "Excitatory's rule, on the same vertex"

    read = await api_schema.execute(reads.ENTITY, variable_values={"id": ref, "graph": str(test_graph.pk)}, context_value=simple_api_context)
    assert read.errors is None, f"GraphQL errors: {read.errors}"
    rich = {row["key"]: row["value"] for row in read.data["entity"]["richProperties"]}
    assert rich["avg_length"] == 3.0 and rich["max_length"] == 4.0, "richProperties declares the keys of every category"
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_key_two_categories_define_differently_is_refused_naming_both(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """One vertex has one value per key. AIS says `avg_length` is the MEAN,
    Excitatory says the MAX: whichever was written would misreport the other,
    so the node is refused with a reason that names both."""

    await writes.create_entity(api_schema, simple_api_context, "AIS")

    @sync_to_async
    def conflict() -> tuple[dict, dict[str, str]]:
        graphs.define_entity(test_graph, "AIS", rules.definition(rules.rule(rules.word("AIS"))))
        graphs.define_entity(test_graph, "Excitatory", rules.definition(rules.rule(rules.word("AIS"))), properties=[_rollup("avg_length", "MAX")])
        result = graphs.rebuild(test_graph, table_projector)
        _, skipped = projector_module.resolve_categories(test_graph, [claims.only_instance(test_graph)])
        return result, skipped

    result, skipped = await conflict()
    assert result["nodes"] == 0 and result["unclassified"] == 1
    (reason,) = skipped.values()
    assert "avg_length" in reason and "AIS" in reason and "Excitatory" in reason

    @sync_to_async
    def agree() -> dict:
        # The same rule on both is not a conflict: there is one answer.
        graphs.define_entity(test_graph, "Excitatory", rules.definition(rules.rule(rules.word("AIS"))), properties=[_rollup("avg_length", "MEAN")])
        graphs.define_entity(test_graph, "AIS", rules.definition(rules.rule(rules.word("AIS"))), properties=[_rollup("avg_length", "MEAN")])
        return graphs.rebuild(test_graph, table_projector)

    assert (await agree())["nodes"] == 1
RELATE = """
    mutation Relate($input: AssertRelationExistsInput!) {
        assertRelationExists(input: $input) { link { id } drawings { category { id } } }
    }
"""
RETRACT_RELATION = """
    mutation Retract($input: RetractRelationInput!) {
        retractRelation(input: $input) { assertion { id } }
    }
"""
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_edge_two_relation_categories_admit_is_drawn_under_both(api_schema, simple_api_context, test_graph, table_projector) -> None:
    """The edge-side twin of RFC 0019 (RFC 0021).

    Two defined relation categories both derive from the word `touches`. The old
    term→category map found two candidates, warned, and mapped the word to
    nothing — so a claim both categories admitted was drawn under neither.
    """
    from evidence import writer
    from tests.support import rules, writes

    @sync_to_async
    def declare() -> None:
        for key, label in (("curated_touch", "CURATED"), ("loose_touch", "LOOSE")):
            core_models.RelationCategory.objects.create(
                graph=test_graph,
                key=key,
                age_name=label,
                label=key,
                term=writer.ensure_term(test_graph.organization, "RELATION", key),
                source_definition={},
                target_definition={},
                definition=rules.definition(rules.rule(rules.word("touches"))),
            )

    await declare()
    a = await writes.create_entity(api_schema, simple_api_context, "Cell")
    b = await writes.create_entity(api_schema, simple_api_context, "Cell")

    result = await api_schema.execute(RELATE, variable_values={"input": {"term": "touches", "sourceId": a, "targetId": b, "supportingEvidence": []}}, context_value=simple_api_context)
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    link_id = result.data["assertRelationExists"]["link"]["id"]
    assert len(result.data["assertRelationExists"]["drawings"]) == 2, "one drawing per admitting category"

    @sync_to_async
    def drawn() -> tuple[int, int]:
        return drawing.edges_between(test_graph, a, b, "CURATED"), drawing.edges_between(test_graph, a, b, "LOOSE")

    assert await drawn() == (1, 1)

    @sync_to_async
    def rebuilt() -> tuple[int, int]:
        graphs.rebuild(test_graph, table_projector)
        return drawing.edges_between(test_graph, a, b, "CURATED"), drawing.edges_between(test_graph, a, b, "LOOSE")

    assert await rebuilt() == (1, 1), "a rebuild draws the same two edges"

    retracted = await api_schema.execute(RETRACT_RELATION, variable_values={"input": {"id": link_id}}, context_value=simple_api_context)
    assert retracted.errors is None, f"GraphQL errors: {retracted.errors}"
    assert await drawn() == (0, 0), "no claim holds either edge up"
@pytest.mark.django_db(transaction=True)
def test_a_view_has_one_category_per_declared_word(test_graph) -> None:
    """`(graph, term)` is unique on `Category` (RFC 0021): the invariant the deleted
    term→category map silently assumed is one the database states."""
    from django.db import IntegrityError, transaction

    from evidence import writer

    term = writer.ensure_term(test_graph.organization, "ENTITY", "Cell")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            core_models.EntityCategory.objects.create(graph=test_graph, key="Cell2", age_name="Cell2", label="Cell2", term=term)
