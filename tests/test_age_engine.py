"""
Integration tests for the Apache AGE Engine.

These tests run against a real PostgreSQL database with Apache AGE extension.
"""
import pytest
from django.test import override_settings

from graph_engine.engine import (
    AgeEngine, 
    SimpleGraph,
    GraphProtocol,
    graph_cursor,
)
from graph_engine.base_models import GraphDefinitionModel, GraphExtensions, NodeDefinition, PropertyDefinition, PropertyType
from graph_engine.controller import GraphController
from graph_engine.input_models import (
    EntityCreationPayload,
    ProvenanceContext,
    MeasurementInput,
)

class TestAgeEngineBasic:
    """Basic tests for AgeEngine functionality."""
    
    @pytest.mark.django_db(transaction=True)
    def test_create_and_query_node(self, age_engine, test_graph):
        """Test creating and querying a simple node."""
        # Create a node
        result = age_engine.execute(
            test_graph,
            "CREATE (n:Person {name: $name, age: $age}) RETURN n.name as name, n.age as age",
            {"name": "Alice", "age": 30}
        )
        
        assert len(result) == 1
        assert result[0]["name"] == "Alice"
        assert result[0]["age"] == 30
    
    @pytest.mark.django_db(transaction=True)
    def test_create_and_query_with_id(self, age_engine, test_graph):
        """Test creating a node and retrieving its id."""
        result = age_engine.execute(
            test_graph,
            "CREATE (n:Person {name: $name}) RETURN id(n) as id, n.name as name",
            {"name": "Bob"}
        )
        
        assert len(result) == 1
        assert "id" in result[0]
        assert result[0]["name"] == "Bob"
    
    @pytest.mark.django_db(transaction=True)
    def test_match_query(self, age_engine, test_graph):
        """Test MATCH queries."""
        # Create nodes
        age_engine.execute(
            test_graph,
            "CREATE (a:Person {name: 'Alice'}), (b:Person {name: 'Bob'})"
        )
        
        # Match all persons
        result = age_engine.execute(
            test_graph,
            "MATCH (p:Person) RETURN p.name as name ORDER BY p.name"
        )
        
        assert len(result) == 2
        assert result[0]["name"] == "Alice"
        assert result[1]["name"] == "Bob"
    
    @pytest.mark.django_db(transaction=True)
    def test_create_relationship(self, age_engine, test_graph):
        """Test creating relationships between nodes."""
        # Create nodes and relationship
        result = age_engine.execute(
            test_graph,
            """
            CREATE (a:Person {name: 'Alice'})
            CREATE (b:Person {name: 'Bob'})
            CREATE (a)-[r:KNOWS {since: 2020}]->(b)
            RETURN a.name as from_name, b.name as to_name, r.since as since
            """
        )
        
        assert len(result) == 1
        assert result[0]["from_name"] == "Alice"
        assert result[0]["to_name"] == "Bob"
        assert result[0]["since"] == 2020
    
    @pytest.mark.django_db(transaction=True)
    def test_match_relationship(self, age_engine, test_graph):
        """Test matching relationships."""
        # Create nodes and relationship
        age_engine.execute(
            test_graph,
            "CREATE (a:Person {name: 'Alice'})-[:KNOWS]->(b:Person {name: 'Bob'})"
        )
        
        # Match the relationship
        result = age_engine.execute(
            test_graph,
            """
            MATCH (a:Person)-[:KNOWS]->(b:Person)
            RETURN a.name as from_name, b.name as to_name
            """
        )
        
        assert len(result) == 1
        assert result[0]["from_name"] == "Alice"
        assert result[0]["to_name"] == "Bob"
    
    @pytest.mark.django_db(transaction=True)
    def test_merge_creates_if_not_exists(self, age_engine, test_graph):
        """Test MERGE creates node if it doesn't exist."""
        result = age_engine.execute(
            test_graph,
            "MERGE (n:Person {name: $name}) RETURN n.name as name",
            {"name": "Charlie"}
        )
        
        assert len(result) == 1
        assert result[0]["name"] == "Charlie"
    
    @pytest.mark.django_db(transaction=True)
    def test_merge_reuses_existing(self, age_engine, test_graph):
        """Test MERGE reuses existing node."""
        # Create first
        age_engine.execute(test_graph, "CREATE (n:Person {name: 'Charlie', age: 25})")
        
        # Merge should find existing
        age_engine.execute(
            test_graph,
            "MERGE (n:Person {name: $name}) SET n.age = $age",
            {"name": "Charlie", "age": 30}
        )
        
        # Verify only one node exists
        result = age_engine.execute(
            test_graph,
            "MATCH (p:Person {name: 'Charlie'}) RETURN p.age as age"
        )
        
        assert len(result) == 1
        assert result[0]["age"] == 30


class TestAgeEngineParameters:
    """Tests for parameter handling in AgeEngine."""
    
    @pytest.mark.django_db(transaction=True)
    def test_string_parameter(self, age_engine, test_graph):
        """Test string parameters are escaped correctly."""
        result = age_engine.execute(
            test_graph,
            "CREATE (n:Test {value: $val}) RETURN n.value as value",
            {"val": "It's a test with 'quotes'"}
        )
        
        assert result[0]["value"] == "It's a test with 'quotes'"
    
    @pytest.mark.django_db(transaction=True)
    def test_integer_parameter(self, age_engine, test_graph):
        """Test integer parameters."""
        result = age_engine.execute(
            test_graph,
            "CREATE (n:Test {value: $val}) RETURN n.value as value",
            {"val": 42}
        )
        
        assert result[0]["value"] == 42
    
    @pytest.mark.django_db(transaction=True)
    def test_float_parameter(self, age_engine, test_graph):
        """Test float parameters."""
        result = age_engine.execute(
            test_graph,
            "CREATE (n:Test {value: $val}) RETURN n.value as value",
            {"val": 3.14}
        )
        
        assert abs(result[0]["value"] - 3.14) < 0.001
    
    @pytest.mark.django_db(transaction=True)
    def test_boolean_parameter(self, age_engine, test_graph):
        """Test boolean parameters."""
        result = age_engine.execute(
            test_graph,
            "CREATE (n:Test {active: $val}) RETURN n.active as active",
            {"val": True}
        )
        
        assert result[0]["active"] == True
    
    @pytest.mark.django_db(transaction=True)
    def test_null_parameter(self, age_engine, test_graph):
        """Test null parameters."""
        result = age_engine.execute(
            test_graph,
            "CREATE (n:Test {value: $val}) RETURN n.value as value",
            {"val": None}
        )
        
        assert result[0]["value"] is None
    
    @pytest.mark.django_db(transaction=True)
    def test_dict_parameter(self, age_engine, test_graph):
        """Test dict parameters are converted to Cypher maps."""
        result = age_engine.execute(
            test_graph,
            "CREATE (n:Test $props) RETURN n.name as name, n.age as age",
            {"props": {"name": "Test", "age": 10}}
        )
        
        assert result[0]["name"] == "Test"
        assert result[0]["age"] == 10


class TestGraphControllerWithAgeEngine:
    """Integration tests for GraphController with real AGE engine."""
    
    @pytest.fixture
    def sample_schema(self):
        """Create a sample schema for testing."""
        return GraphDefinitionModel(
            system_version="1.0",
            extensions=GraphExtensions(
                entities={
                    "Cell": NodeDefinition(
                        description="A biological cell",
                        properties={
                            "name": PropertyDefinition(type=PropertyType.STRING),
                            "size": PropertyDefinition(type=PropertyType.FLOAT),
                        }
                    )
                }
            )
        )
    
    @pytest.fixture
    def sample_graph(self, test_graph_name, sample_schema):
        """Create a sample graph with schema."""
        return SimpleGraph(age_name=test_graph_name, definition=sample_schema)
    
    @pytest.mark.django_db(transaction=True)
    def test_controller_with_graph_protocol(self, age_engine, sample_graph):
        """Test creating a controller with graph protocol."""
        controller = GraphController(engine=age_engine, graph=sample_graph)
        
        assert controller.engine is age_engine
        assert controller.age_name == sample_graph.age_name
        assert controller.definition == sample_graph.definition


class TestGraphCursor:
    """Tests for the graph_cursor context manager."""
    
    @pytest.mark.django_db(transaction=True)
    def test_graph_cursor_loads_age(self, db, backend_stack):
        """Test that graph_cursor properly loads AGE extension."""
        with graph_cursor() as cursor:
            # This should work if AGE is loaded
            cursor.execute("SELECT * FROM ag_catalog.ag_graph LIMIT 1")
            # No exception means AGE is loaded correctly
    
    @pytest.mark.django_db(transaction=True)
    def test_graph_cursor_sets_search_path(self, db, backend_stack):
        """Test that graph_cursor sets the correct search_path."""
        with graph_cursor() as cursor:
            cursor.execute("SHOW search_path")
            result = cursor.fetchone()
            assert "ag_catalog" in result[0]


class TestSchemaMigration:
    """Tests for schema migration functionality."""
    
    def test_generate_migration_add_entity(self):
        """Test generating migration for adding an entity."""
        from graph_engine.schema_migration import generate_schema_migration, MigrationAction
        
        old_schema = GraphDefinitionModel(
            system_version="1.0",
            extensions=GraphExtensions()
        )
        
        new_schema = GraphDefinitionModel(
            system_version="1.1",
            extensions=GraphExtensions(
                entities={
                    "Cell": NodeDefinition(
                        description="A cell",
                        properties={
                            "name": PropertyDefinition(type=PropertyType.STRING)
                        }
                    )
                }
            )
        )
        
        plan = generate_schema_migration(old_schema, new_schema)
        
        assert plan.from_version == "1.0"
        assert plan.to_version == "1.1"
        assert len(plan.mutations) == 1
        assert plan.mutations[0].action == MigrationAction.ADD_NODE_TYPE
        assert plan.mutations[0].target == "Cell"
    
    def test_generate_migration_add_property(self):
        """Test generating migration for adding a property."""
        from graph_engine.schema_migration import generate_schema_migration, MigrationAction
        
        old_schema = GraphDefinitionModel(
            system_version="1.0",
            extensions=GraphExtensions(
                entities={
                    "Cell": NodeDefinition(
                        properties={
                            "name": PropertyDefinition(type=PropertyType.STRING)
                        }
                    )
                }
            )
        )
        
        new_schema = GraphDefinitionModel(
            system_version="1.1",
            extensions=GraphExtensions(
                entities={
                    "Cell": NodeDefinition(
                        properties={
                            "name": PropertyDefinition(type=PropertyType.STRING),
                            "size": PropertyDefinition(type=PropertyType.FLOAT)
                        }
                    )
                }
            )
        )
        
        plan = generate_schema_migration(old_schema, new_schema)
        
        assert len(plan.mutations) == 1
        assert plan.mutations[0].action == MigrationAction.ADD_PROPERTY
        assert plan.mutations[0].target == "Cell"
        assert plan.mutations[0].property_name == "size"
        assert "SET n.size" in plan.mutations[0].cypher_query
    
    def test_generate_migration_remove_property(self):
        """Test generating migration for removing a property."""
        from graph_engine.schema_migration import generate_schema_migration, MigrationAction
        
        old_schema = GraphDefinitionModel(
            system_version="1.0",
            extensions=GraphExtensions(
                entities={
                    "Cell": NodeDefinition(
                        properties={
                            "name": PropertyDefinition(type=PropertyType.STRING),
                            "old_field": PropertyDefinition(type=PropertyType.STRING)
                        }
                    )
                }
            )
        )
        
        new_schema = GraphDefinitionModel(
            system_version="1.1",
            extensions=GraphExtensions(
                entities={
                    "Cell": NodeDefinition(
                        properties={
                            "name": PropertyDefinition(type=PropertyType.STRING)
                        }
                    )
                }
            )
        )
        
        plan = generate_schema_migration(old_schema, new_schema)
        
        assert plan.has_breaking_changes
        assert len(plan.mutations) == 1
        assert plan.mutations[0].action == MigrationAction.REMOVE_PROPERTY
        assert plan.mutations[0].property_name == "old_field"
    
    def test_generate_migration_from_none(self):
        """Test generating migration from scratch (None schema)."""
        from graph_engine.schema_migration import generate_schema_migration, MigrationAction
        
        new_schema = GraphDefinitionModel(
            system_version="1.0",
            extensions=GraphExtensions(
                entities={
                    "Cell": NodeDefinition(
                        properties={
                            "name": PropertyDefinition(type=PropertyType.STRING)
                        }
                    )
                }
            )
        )
        
        plan = generate_schema_migration(None, new_schema)
        
        assert plan.from_version == "0.0.0"
        assert plan.to_version == "1.0"
        assert len(plan.mutations) == 1
        assert plan.mutations[0].action == MigrationAction.ADD_NODE_TYPE
