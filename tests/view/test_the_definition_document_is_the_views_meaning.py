"""
Tests for the materialize function.

These tests verify that:
1. Graphs can be materialized from a GraphDefinitionModel
2. All database models (EntityCategory, RelationCategory, NaturalEventCategory) are created
3. The GraphSchema is created and activated
4. The AGE graph is created in the database
5. Property definitions are correctly stored
"""

import pytest
from graph_engine import input_models as models
from graph_engine.materialize import materialize, compute_definition_hash, compute_properties_hash
from core import models as core_models
import kante
from asgiref.sync import sync_to_async
from kante.context import HttpContext
from evidence import models as evidence_models
from tests.support import claims, drawing, rules, writes
from typing import Any, Dict
from api.schema import schema
from graph_engine.input_models import GraphDefinitionInput


def _materialize_with_context(definition, engine, context, name=None, description=None):
    request = context.request
    return materialize(
        definition,
        engine,
        user=request._user,
        organization=request._organization,
        membership=request.membership,
        name=name,
        description=description,
    )


def test_materialize_creates_graph(transactional_db, table_projector, bio_graph_schema, authenticated_context) -> None:
    """Test that materialize creates a Graph instance with correct attributes."""
    graph = _materialize_with_context(
        bio_graph_schema,
        table_projector,
        authenticated_context,
        name="test_materialize_graph",
        description="Test graph for materialization",
    )

    assert graph is not None
    assert graph.name == "test_materialize_graph"
    assert graph.description == "Test graph for materialization"
    assert graph.age_name is not None


def test_materialize_creates_entity_categories(transactional_db, table_projector, bio_graph_schema, authenticated_context) -> None:
    """Test that materialize creates EntityCategory for each entity definition."""
    graph = _materialize_with_context(
        bio_graph_schema,
        table_projector,
        authenticated_context,
        name="test_entity_cats",
    )

    # Check that all entity categories are created
    entity_cats = graph.entity_categories.all()
    entity_keys = {cat.age_name for cat in entity_cats}

    # bio_graph_schema has AIS, Soma, Cell
    assert "AIS" in entity_keys
    assert "Soma" in entity_keys
    assert "Cell" in entity_keys


def test_materialize_creates_relation_categories(transactional_db, table_projector, bio_graph_schema, authenticated_context) -> None:
    """Test that materialize creates RelationCategory for each relation definition."""
    graph = _materialize_with_context(
        bio_graph_schema,
        table_projector,
        authenticated_context,
        name="test_relation_cats",
    )

    # Check that all relation categories are created
    relation_cats = graph.relation_categories.all()
    relation_keys = {cat.age_name for cat in relation_cats}

    # bio_graph_schema has IS_CONNECTED_TO, PART_OF
    assert "IS_CONNECTED_TO" in relation_keys
    assert "PART_OF" in relation_keys


def test_materialize_creates_event_categories(transactional_db, table_projector, bio_graph_schema, authenticated_context) -> None:
    """Test that materialize creates NaturalEventCategory for each event definition."""
    graph = _materialize_with_context(
        bio_graph_schema,
        table_projector,
        authenticated_context,
        name="test_event_cats",
    )

    # Check that all event categories are created
    event_cats = graph.natural_event_categories.all()
    event_keys = {cat.age_name for cat in event_cats}

    # bio_graph_schema has Mitosis
    assert "Mitosis" in event_keys


def test_materialize_creates_active_schema(transactional_db, table_projector, bio_graph_schema, authenticated_context) -> None:
    """Test that materialize creates an active GraphSchema."""
    graph = _materialize_with_context(
        bio_graph_schema,
        table_projector,
        authenticated_context,
        name="test_schema",
    )

    # Check that schema is created and active
    active_schema = graph.active_schema
    assert active_schema is not None
    assert active_schema.is_active is True
    assert active_schema.version == bio_graph_schema.system_version


def test_entity_category_has_property_definitions(transactional_db, table_projector, bio_graph_schema, authenticated_context) -> None:
    """Test that EntityCategory stores property definitions correctly."""
    graph = _materialize_with_context(
        bio_graph_schema,
        table_projector,
        authenticated_context,
        name="test_props",
    )

    # Get AIS entity category
    ais_cat = graph.get_entity_def("AIS")
    assert ais_cat is not None

    # Check property definitions
    prop_defs = ais_cat.property_definitions
    assert len(prop_defs) > 0

    # AIS has avg_length and name properties
    prop_keys = {p["key"] for p in prop_defs}
    assert "avg_length" in prop_keys
    assert "name" in prop_keys


def test_relation_category_has_source_target_definitions(transactional_db, table_projector, bio_graph_schema, authenticated_context) -> None:
    """Test that RelationCategory stores source/target definitions correctly."""
    graph = _materialize_with_context(
        bio_graph_schema,
        table_projector,
        authenticated_context,
        name="test_rel_defs",
    )

    # Get IS_CONNECTED_TO relation category
    rel_cat = graph.relation_categories.get(age_name="IS_CONNECTED_TO")
    assert rel_cat is not None

    # Check source/target definitions
    assert rel_cat.source_definition is not None
    assert rel_cat.target_definition is not None
    assert "keys" in rel_cat.source_definition
    assert "Cell" in rel_cat.source_definition["keys"]
    assert "keys" in rel_cat.target_definition
    assert "Cell" in rel_cat.target_definition["keys"]


def test_event_category_has_roles(transactional_db, table_projector, bio_graph_schema, authenticated_context) -> None:
    """Test that NaturalEventCategory stores source/target roles correctly."""
    graph = _materialize_with_context(
        bio_graph_schema,
        table_projector,
        authenticated_context,
        name="test_event_roles",
    )

    # Get Mitosis event category
    event_cat = graph.natural_event_categories.get(age_name="Mitosis")
    assert event_cat is not None

    # Check source/target roles
    assert len(event_cat.source_entity_roles) > 0
    assert len(event_cat.target_entity_roles) > 0


def test_compute_definition_hash_is_deterministic() -> None:
    """Test that compute_definition_hash produces consistent results.

    `property_definitions`, not `properties`: an entity definition spells it the
    first way and only an edge definition spells it the second. This said
    `properties=[...]`, pydantic dropped the unknown key, and the schema being
    hashed had no properties at all — so the test was determinism over an empty
    entity. `StrictModel` refuses the key now.
    """
    schema = models.GraphDefinitionInput(system_version="1.0.0", extensions=models.GraphExtensionsInput(entities=[models.EntityDefinitionInput(key="TestEntity", property_definitions=[models.PropertyDefinitionInput(key="name", type=models.PropertyType.STRING)])]))

    hash1 = compute_definition_hash(schema)
    hash2 = compute_definition_hash(schema)

    assert hash1 == hash2


def test_compute_properties_hash_is_deterministic() -> None:
    """Test that compute_properties_hash produces consistent results."""
    props = [
        {"key": "name", "type": "string"},
        {"key": "value", "type": "float"},
    ]

    hash1 = compute_properties_hash(props)
    hash2 = compute_properties_hash(props)

    assert hash1 == hash2


def test_compute_properties_hash_is_order_independent() -> None:
    """Test that compute_properties_hash produces same results regardless of list order."""
    props1 = [
        {"key": "name", "type": "string"},
        {"key": "value", "type": "float"},
    ]
    props2 = [
        {"key": "value", "type": "float"},
        {"key": "name", "type": "string"},
    ]

    hash1 = compute_properties_hash(props1)
    hash2 = compute_properties_hash(props2)

    assert hash1 == hash2


def test_materialize_with_minimal_schema(transactional_db, table_projector, minimal_schema, authenticated_context) -> None:
    """Test materialize works with a minimal schema (just entities)."""
    graph = _materialize_with_context(
        minimal_schema,
        table_projector,
        authenticated_context,
        name="minimal_test",
    )

    assert graph is not None
    assert graph.entity_categories.count() == 1
    assert graph.relation_categories.count() == 0
    assert graph.natural_event_categories.count() == 0

    # Check the Person entity
    person_cat = graph.get_entity_def("Person")
    assert person_cat is not None
    assert person_cat.description == "A person"


def test_get_entity_def_returns_correct_category(transactional_db, table_projector, bio_graph_schema, authenticated_context) -> None:
    """Test that Graph.get_entity_def returns the correct EntityCategory."""
    graph = _materialize_with_context(
        bio_graph_schema,
        table_projector,
        authenticated_context,
        name="test_get_def",
    )

    ais = graph.get_entity_def("AIS")
    soma = graph.get_entity_def("Soma")
    cell = graph.get_entity_def("Cell")

    assert ais.age_name == "AIS"
    assert soma.age_name == "Soma"
    assert cell.age_name == "Cell"


def test_get_entity_def_raises_for_unknown_key(transactional_db, table_projector, bio_graph_schema, authenticated_context) -> None:
    """Test that Graph.get_entity_def raises an error for unknown keys."""
    graph = _materialize_with_context(
        bio_graph_schema,
        table_projector,
        authenticated_context,
        name="test_get_def_error",
    )

    with pytest.raises(core_models.EntityCategory.DoesNotExist):
        graph.get_entity_def("UnknownEntity")


def test_an_extrinsic_event_materializes_as_a_protocol_event_category(transactional_db, table_projector, authenticated_context) -> None:
    """`EventDefinitionInput.kind` decides the category kind. It used to be read
    by nothing, so every event became a natural event category."""
    definition = models.GraphDefinitionInput(
        system_version="1.0.0",
        extensions=models.GraphExtensionsInput(
            entities=[models.EntityDefinitionInput(key="Sample", property_definitions=[])],
            events=[
                models.EventDefinitionInput(key="Mitosis", kind=models.EventKind.INTRINSIC),
                models.EventDefinitionInput(key="Fixation", kind=models.EventKind.EXTRINSIC),
            ],
        ),
    )
    graph = _materialize_with_context(definition, table_projector, authenticated_context, name="protocol")

    assert set(graph.natural_event_categories.values_list("key", flat=True)) == {"Mitosis"}
    assert set(graph.protocol_event_categories.values_list("key", flat=True)) == {"Fixation"}


CREATE_CATEGORY = """
    mutation C($input: CreateEntityCategoryInput!) {
        createEntityCategory(input: $input) { id key definition { rules { when { field operator value } } } }
    }
"""
UPDATE_CATEGORY = """
    mutation U($input: UpdateEntityCategoryInput!) {
        updateEntityCategory(input: $input) { id definition { rules { when { field operator value } } } }
    }
"""
CREATE_GRAPH = """
    mutation G($input: CreateGraphInput!) {
        createGraph(input: $input) { id }
    }
"""


async def _claimed_cells(api_schema, ctx, literal_graph) -> tuple[str, str]:
    """Two Cells, one claimed by peter, one by karl."""
    c1 = await writes.create_entity(api_schema, ctx, "Cell")
    c2 = await writes.create_entity(api_schema, ctx, "Cell")

    @sync_to_async
    def annotate():
        cell = core_models.Category.objects.get(graph=literal_graph, key="Cell")
        claims.classify(literal_graph, c1, cell, "peter")
        claims.classify(literal_graph, c2, cell, "karl")

    await annotate()
    return c1, c2


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_with_a_definition_backfills_the_admitted_history(api_schema: kante.Schema, simple_api_context: HttpContext, literal_graph: core_models.Graph, table_projector) -> None:
    peters, _ = await _claimed_cells(api_schema, simple_api_context, literal_graph)

    made = await api_schema.execute(CREATE_GRAPH, variable_values={"input": {"name": "defined-views"}}, context_value=simple_api_context)
    assert made.errors is None, f"GraphQL errors: {made.errors}"
    graph_id = made.data["createGraph"]["id"]

    created = await api_schema.execute(
        CREATE_CATEGORY,
        variable_values={
            "input": {
                "graph": graph_id,
                "key": "PetersCells",
                "definition": rules.definition(rules.rule(rules.word("Cell"), rules.by("peter"))),
                "backfill": True,
            }
        },
        context_value=simple_api_context,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    assert {"field": "WORD", "operator": "IS", "value": "Cell"} in created.data["createEntityCategory"]["definition"]["rules"][0]["when"], "the meaning reads back from the same mutation"

    @sync_to_async
    def drawn():
        graph = core_models.Graph.objects.get(pk=graph_id)
        return drawing.refs_with_label(graph, "PetersCells")

    assert await drawn() == [peters], "backfill drew exactly the history the clauses admit — under this view's own word"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_updating_a_definition_moves_membership_and_writes_no_evidence(api_schema: kante.Schema, simple_api_context: HttpContext, literal_graph: core_models.Graph, table_projector) -> None:
    peters, karls = await _claimed_cells(api_schema, simple_api_context, literal_graph)

    made = await api_schema.execute(CREATE_GRAPH, variable_values={"input": {"name": "movable"}}, context_value=simple_api_context)
    assert made.errors is None
    graph_id = made.data["createGraph"]["id"]
    created = await api_schema.execute(
        CREATE_CATEGORY,
        variable_values={"input": {"graph": graph_id, "key": "TheCells", "definition": rules.definition(rules.rule(rules.word("Cell"), rules.by("peter"))), "backfill": True}},
        context_value=simple_api_context,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    category_id = created.data["createEntityCategory"]["id"]

    @sync_to_async
    def evidence_rows() -> int:
        return evidence_models.Assertion.objects.for_organization(literal_graph.organization).count()

    before = await evidence_rows()

    updated = await api_schema.execute(
        UPDATE_CATEGORY,
        variable_values={"input": {"id": category_id, "definition": rules.definition(rules.rule(rules.word("Cell"), rules.by("karl")))}},
        context_value=simple_api_context,
    )
    assert updated.errors is None, f"GraphQL errors: {updated.errors}"
    assert {"field": "SUBJECT", "operator": "IS", "value": "karl"} in updated.data["updateEntityCategory"]["definition"]["rules"][0]["when"]

    @sync_to_async
    def drawn():
        graph = core_models.Graph.objects.get(pk=graph_id)
        return drawing.refs_with_label(graph, "TheCells")

    assert await drawn() == [karls], "membership moved with the meaning — the mutation reprojected"
    assert await evidence_rows() == before, "a definition is a read-side reinterpretation: zero evidence writes"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_malformed_definitions_are_refused_by_name(api_schema: kante.Schema, simple_api_context: HttpContext, literal_graph: core_models.Graph, table_projector) -> None:
    made = await api_schema.execute(CREATE_GRAPH, variable_values={"input": {"name": "refusals"}}, context_value=simple_api_context)
    graph_id = made.data["createGraph"]["id"]

    async def attempt(definition):
        return await api_schema.execute(
            CREATE_CATEGORY,
            variable_values={"input": {"graph": graph_id, "key": "Broken", "definition": definition}},
            context_value=simple_api_context,
        )

    empty_union = await attempt({"rules": []})
    assert empty_union.errors is not None, "an empty rule list matches nothing and is refused at the write"

    wordless = await attempt(rules.definition(rules.rule(rules.by("peter"))))
    assert wordless.errors is not None, "a rule must name the word(s) it derives from"

    empty_rule = await attempt({"rules": [{"when": []}]})
    assert empty_rule.errors is not None, "a rule needs at least one condition"

    unknown = await attempt({"rules": [{"when": [rules.word("Cell")], "tags": ["old"]}]})
    assert unknown.errors is not None, "an unknown key is an error, not a silent no-op"

    bad_operator = await attempt(rules.definition(rules.rule(rules.condition("SUBJECT", "BEFORE", "peter"))))
    assert bad_operator.errors is not None, "a time operator on an identity field is refused by name"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_graph_definition_document_carries_meaning(api_schema: kante.Schema, simple_api_context: HttpContext, literal_graph: core_models.Graph, table_projector) -> None:
    """The whole view — words *and* what they mean — arrives as one schema.

    `createGraph`'s definition document declares a defined category inline, and
    `backfill` draws the history its rules admit. No follow-up mutation, no
    Python: the definition input is part of `GraphDefinitionInput`.
    """
    peters, _ = await _claimed_cells(api_schema, simple_api_context, literal_graph)

    made = await api_schema.execute(
        """
        mutation G($input: CreateGraphInput!) {
            createGraph(input: $input) { id }
        }
        """,
        variable_values={
            "input": {
                "name": "peters-view",
                "backfill": True,
                "definition": {"extensions": {"entities": [{"key": "PetersCell", "definition": rules.definition(rules.rule(rules.word("Cell"), rules.by("peter")))}]}},
            }
        },
        context_value=simple_api_context,
    )
    assert made.errors is None, f"GraphQL errors: {made.errors}"
    graph_id = made.data["createGraph"]["id"]

    @sync_to_async
    def drawn():
        return drawing.refs_with_label(core_models.Graph.objects.get(pk=graph_id), "PetersCell")

    assert await drawn() == [peters], "one mutation: the schema declared the meaning and the backfill drew what it admits"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_graph_from_schema(
    db: object,
    bio_graph_schema: GraphDefinitionInput,
    authenticated_context: HttpContext,
) -> None:
    query: str = """
        mutation CreateGraph($input: CreateGraphInput!) {
            createGraph(input: $input) {
                id
                name
            }
        }
    """

    variables: Dict[str, Any] = {
        "input": {
            "name": "Test Model",
            "description": "A test graph schema for validating graph creation from schema functionality.",
            "definition": {
                "systemVersion": "1.0.1",
                "extensions": {
                    "entities": [
                        {
                            "key": "TestEntity",
                            "label": "Test Entity",
                            "description": "Entity used for schema creation tests",
                            # The rule is required: a property with no source is
                            # not computable, and nothing writes one directly.
                            "propertyDefinitions": [
                                {
                                    "key": "name",
                                    "valueKind": "STRING",
                                    "derivation": "LATEST",
                                    "rule": {"sourceNode": "ROI", "key": "name"},
                                }
                            ],
                        }
                    ]
                },
            },
        }
    }

    sub = await schema.execute(
        query,
        variable_values=variables,
        context_value=authenticated_context,
    )

    assert sub.data, sub.errors

    assert sub.data["createGraph"]["name"] == "Test Model"


TERMS = """
    query Terms($filters: TermFilter) {
        terms(filters: $filters) { id kind key label description purl }
    }
"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_materializing_a_graph_puts_its_words_in_the_vocabulary(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Terms are minted by declaring a category, so the list is never empty."""
    result = await api_schema.execute(TERMS, variable_values={"filters": None}, context_value=simple_api_context)
    assert result.errors is None, f"GraphQL errors: {result.errors}"

    listed = {(row["kind"], row["key"]) for row in result.data["terms"]}
    assert ("ENTITY", "AIS") in listed, "The bio schema declares an AIS entity, so the organization knows the word"
    assert ("RELATION", "IS_CONNECTED_TO") in listed, "And a relation, under its own kind"
