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
from graph_engine import base_models as models
from graph_engine.materialize import materialize, compute_definition_hash, compute_properties_hash
from core import models as core_models

pytestmark = pytest.mark.skip(reason="Requires updated DB schema/migrations for materialize")


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


def test_materialize_creates_graph(transactional_db, age_engine, bio_graph_schema, authenticated_context) -> None:
    """Test that materialize creates a Graph instance with correct attributes."""
    graph = _materialize_with_context(
        bio_graph_schema,
        age_engine,
        authenticated_context,
        name="test_materialize_graph",
        description="Test graph for materialization",
    )
    
    assert graph is not None
    assert graph.name == "test_materialize_graph"
    assert graph.description == "Test graph for materialization"
    assert graph.age_name is not None


def test_materialize_creates_entity_categories(transactional_db, age_engine, bio_graph_schema, authenticated_context) -> None:
    """Test that materialize creates EntityCategory for each entity definition."""
    graph = _materialize_with_context(
        bio_graph_schema,
        age_engine,
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


def test_materialize_creates_relation_categories(transactional_db, age_engine, bio_graph_schema, authenticated_context) -> None:
    """Test that materialize creates RelationCategory for each relation definition."""
    graph = _materialize_with_context(
        bio_graph_schema,
        age_engine,
        authenticated_context,
        name="test_relation_cats",
    )
    
    # Check that all relation categories are created
    relation_cats = graph.relation_categories.all()
    relation_keys = {cat.age_name for cat in relation_cats}
    
    # bio_graph_schema has IS_CONNECTED_TO, PART_OF
    assert "IS_CONNECTED_TO" in relation_keys
    assert "PART_OF" in relation_keys


def test_materialize_creates_event_categories(transactional_db, age_engine, bio_graph_schema, authenticated_context) -> None:
    """Test that materialize creates NaturalEventCategory for each event definition."""
    graph = _materialize_with_context(
        bio_graph_schema,
        age_engine,
        authenticated_context,
        name="test_event_cats",
    )
    
    # Check that all event categories are created
    event_cats = graph.natural_event_categories.all()
    event_keys = {cat.age_name for cat in event_cats}
    
    # bio_graph_schema has Mitosis
    assert "Mitosis" in event_keys


def test_materialize_creates_active_schema(transactional_db, age_engine, bio_graph_schema, authenticated_context) -> None:
    """Test that materialize creates an active GraphSchema."""
    graph = _materialize_with_context(
        bio_graph_schema,
        age_engine,
        authenticated_context,
        name="test_schema",
    )
    
    # Check that schema is created and active
    active_schema = graph.active_schema
    assert active_schema is not None
    assert active_schema.is_active is True
    assert active_schema.version == bio_graph_schema.system_version


def test_entity_category_has_property_definitions(transactional_db, age_engine, bio_graph_schema, authenticated_context) -> None:
    """Test that EntityCategory stores property definitions correctly."""
    graph = _materialize_with_context(
        bio_graph_schema,
        age_engine,
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
    prop_keys = {p['key'] for p in prop_defs}
    assert "avg_length" in prop_keys
    assert "name" in prop_keys


def test_entity_category_has_schema_hash(transactional_db, age_engine, bio_graph_schema, authenticated_context) -> None:
    """Test that EntityCategory has a schema_hash computed from property definitions."""
    graph = _materialize_with_context(
        bio_graph_schema,
        age_engine,
        authenticated_context,
        name="test_hash",
    )
    
    ais_cat = graph.get_entity_def("AIS")
    assert ais_cat.schema_hash is not None
    assert len(ais_cat.schema_hash) > 0


def test_relation_category_has_source_target_definitions(transactional_db, age_engine, bio_graph_schema, authenticated_context) -> None:
    """Test that RelationCategory stores source/target definitions correctly."""
    graph = _materialize_with_context(
        bio_graph_schema,
        age_engine,
        authenticated_context,
        name="test_rel_defs",
    )
    
    # Get IS_CONNECTED_TO relation category
    rel_cat = graph.relation_categories.get(age_name="IS_CONNECTED_TO")
    assert rel_cat is not None
    
    # Check source/target definitions
    assert rel_cat.source_definition is not None
    assert rel_cat.target_definition is not None
    assert "types" in rel_cat.source_definition
    assert "AIS" in rel_cat.source_definition["types"]
    assert "Soma" in rel_cat.target_definition["types"]


def test_event_category_has_roles(transactional_db, age_engine, bio_graph_schema, authenticated_context) -> None:
    """Test that NaturalEventCategory stores source/target roles correctly."""
    graph = _materialize_with_context(
        bio_graph_schema,
        age_engine,
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
    """Test that compute_definition_hash produces consistent results."""
    schema = models.GraphDefinitionModel(
        system_version="1.0",
        extensions=models.GraphExtensions(
            entities=[
                models.EntityDefinition(
                    key="TestEntity",
                    properties=[
                        models.PropertyDefinition(key="name", type=models.PropertyType.STRING)
                    ]
                )
            ]
        )
    )
    
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


def test_materialize_with_minimal_schema(transactional_db, age_engine, minimal_schema, authenticated_context) -> None:
    """Test materialize works with a minimal schema (just entities)."""
    graph = _materialize_with_context(
        minimal_schema,
        age_engine,
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


def test_get_entity_def_returns_correct_category(transactional_db, age_engine, bio_graph_schema, authenticated_context) -> None:
    """Test that Graph.get_entity_def returns the correct EntityCategory."""
    graph = _materialize_with_context(
        bio_graph_schema,
        age_engine,
        authenticated_context,
        name="test_get_def",
    )
    
    ais = graph.get_entity_def("AIS")
    soma = graph.get_entity_def("Soma")
    cell = graph.get_entity_def("Cell")
    
    assert ais.age_name == "AIS"
    assert soma.age_name == "Soma"
    assert cell.age_name == "Cell"


def test_get_entity_def_raises_for_unknown_key(transactional_db, age_engine, bio_graph_schema, authenticated_context) -> None:
    """Test that Graph.get_entity_def raises an error for unknown keys."""
    graph = _materialize_with_context(
        bio_graph_schema,
        age_engine,
        authenticated_context,
        name="test_get_def_error",
    )
    
    with pytest.raises(core_models.EntityCategory.DoesNotExist):
        graph.get_entity_def("UnknownEntity")
