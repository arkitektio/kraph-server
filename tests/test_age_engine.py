"""
Integration tests for the Apache AGE Engine.

These tests run against a real PostgreSQL database with Apache AGE extension.
"""
import pytest
from django.test import override_settings

from graph_engine.engine import (
    AgeEngine, 
    AgeEngineFactory, 
    SimpleGraphContext,
    graph_cursor,
)
from graph_engine.base_models import GraphDefinitionModel, EntityDefinitionModel
from graph_engine.controller import GraphController
from graph_engine.input_models import (
    EntityCreationPayload,
    ProvenanceInput,
    EvidenceInput,
    MeasurementInput,
)


@pytest.fixture(scope="function")
def test_graph_name():
    """Generate a unique graph name for each test."""
    import uuid
    return f"test_graph_{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="function")
def age_engine(db, backend_stack, test_graph_name):
    """
    Create an AGE engine with a fresh test graph.
    
    Creates the graph, runs the test, then drops the graph.
    """
    engine = AgeEngine(graph_name=test_graph_name)
    
    # Create the graph
    try:
        engine.execute_raw(f"SELECT * FROM ag_catalog.create_graph('{test_graph_name}')")
    except Exception as e:
        # Graph might already exist
        if "already exists" not in str(e):
            raise
    
    yield engine
    
    # Clean up: drop the graph
    try:
        engine.execute_raw(f"SELECT * FROM ag_catalog.drop_graph('{test_graph_name}', true)")
    except Exception:
        pass  # Ignore cleanup errors


class TestAgeEngineBasic:
    """Basic tests for AgeEngine functionality."""
    
    @pytest.mark.django_db(transaction=True)
    def test_create_and_query_node(self, age_engine):
        """Test creating and querying a simple node."""
        # Create a node
        result = age_engine.execute(
            "CREATE (n:Person {name: $name, age: $age}) RETURN n.name as name, n.age as age",
            {"name": "Alice", "age": 30}
        )
        
        assert len(result) == 1
        assert result[0]["name"] == "Alice"
        assert result[0]["age"] == 30
    
    @pytest.mark.django_db(transaction=True)
    def test_create_and_query_with_id(self, age_engine):
        """Test creating a node and retrieving its id."""
        result = age_engine.execute(
            "CREATE (n:Person {name: $name}) RETURN id(n) as id, n.name as name",
            {"name": "Bob"}
        )
        
        assert len(result) == 1
        assert "id" in result[0]
        assert result[0]["name"] == "Bob"
    
    @pytest.mark.django_db(transaction=True)
    def test_match_query(self, age_engine):
        """Test MATCH queries."""
        # Create nodes
        age_engine.execute(
            "CREATE (a:Person {name: 'Alice'}), (b:Person {name: 'Bob'})"
        )
        
        # Match all persons
        result = age_engine.execute(
            "MATCH (p:Person) RETURN p.name as name ORDER BY p.name"
        )
        
        assert len(result) == 2
        assert result[0]["name"] == "Alice"
        assert result[1]["name"] == "Bob"
    
    @pytest.mark.django_db(transaction=True)
    def test_create_relationship(self, age_engine):
        """Test creating relationships between nodes."""
        # Create nodes and relationship
        result = age_engine.execute("""
            CREATE (a:Person {name: 'Alice'})
            CREATE (b:Person {name: 'Bob'})
            CREATE (a)-[r:KNOWS {since: 2020}]->(b)
            RETURN a.name as from_name, b.name as to_name, r.since as since
        """)
        
        assert len(result) == 1
        assert result[0]["from_name"] == "Alice"
        assert result[0]["to_name"] == "Bob"
        assert result[0]["since"] == 2020
    
    @pytest.mark.django_db(transaction=True)
    def test_match_relationship(self, age_engine):
        """Test matching relationships."""
        # Create nodes and relationship
        age_engine.execute("""
            CREATE (a:Person {name: 'Alice'})-[:KNOWS]->(b:Person {name: 'Bob'})
        """)
        
        # Match the relationship
        result = age_engine.execute("""
            MATCH (a:Person)-[:KNOWS]->(b:Person)
            RETURN a.name as from_name, b.name as to_name
        """)
        
        assert len(result) == 1
        assert result[0]["from_name"] == "Alice"
        assert result[0]["to_name"] == "Bob"
    
    @pytest.mark.django_db(transaction=True)
    def test_merge_creates_if_not_exists(self, age_engine):
        """Test MERGE creates node if it doesn't exist."""
        result = age_engine.execute(
            "MERGE (n:Person {name: $name}) RETURN n.name as name",
            {"name": "Charlie"}
        )
        
        assert len(result) == 1
        assert result[0]["name"] == "Charlie"
    
    @pytest.mark.django_db(transaction=True)
    def test_merge_reuses_existing(self, age_engine):
        """Test MERGE reuses existing node."""
        # Create first
        age_engine.execute("CREATE (n:Person {name: 'Charlie', age: 25})")
        
        # Merge should find existing
        age_engine.execute(
            "MERGE (n:Person {name: $name}) SET n.age = $age",
            {"name": "Charlie", "age": 30}
        )
        
        # Verify only one node exists
        result = age_engine.execute(
            "MATCH (p:Person {name: 'Charlie'}) RETURN p.age as age"
        )
        
        assert len(result) == 1
        assert result[0]["age"] == 30


class TestAgeEngineParameters:
    """Tests for parameter handling in AgeEngine."""
    
    @pytest.mark.django_db(transaction=True)
    def test_string_parameter(self, age_engine):
        """Test string parameters are escaped correctly."""
        result = age_engine.execute(
            "CREATE (n:Test {value: $val}) RETURN n.value as value",
            {"val": "It's a test with 'quotes'"}
        )
        
        assert result[0]["value"] == "It's a test with 'quotes'"
    
    @pytest.mark.django_db(transaction=True)
    def test_integer_parameter(self, age_engine):
        """Test integer parameters."""
        result = age_engine.execute(
            "CREATE (n:Test {value: $val}) RETURN n.value as value",
            {"val": 42}
        )
        
        assert result[0]["value"] == 42
    
    @pytest.mark.django_db(transaction=True)
    def test_float_parameter(self, age_engine):
        """Test float parameters."""
        result = age_engine.execute(
            "CREATE (n:Test {value: $val}) RETURN n.value as value",
            {"val": 3.14}
        )
        
        assert abs(result[0]["value"] - 3.14) < 0.001
    
    @pytest.mark.django_db(transaction=True)
    def test_boolean_parameter(self, age_engine):
        """Test boolean parameters."""
        result = age_engine.execute(
            "CREATE (n:Test {active: $val}) RETURN n.active as active",
            {"val": True}
        )
        
        assert result[0]["active"] == True
    
    @pytest.mark.django_db(transaction=True)
    def test_null_parameter(self, age_engine):
        """Test null parameters."""
        result = age_engine.execute(
            "CREATE (n:Test {value: $val}) RETURN n.value as value",
            {"val": None}
        )
        
        assert result[0]["value"] is None
    
    @pytest.mark.django_db(transaction=True)
    def test_dict_parameter(self, age_engine):
        """Test dict parameters are converted to Cypher maps."""
        result = age_engine.execute(
            "CREATE (n:Test $props) RETURN n.name as name, n.age as age",
            {"props": {"name": "Test", "age": 10}}
        )
        
        assert result[0]["name"] == "Test"
        assert result[0]["age"] == 10


class TestAgeEngineFactory:
    """Tests for AgeEngineFactory."""
    
    @pytest.mark.django_db(transaction=True)
    def test_from_context(self, db, backend_stack, test_graph_name):
        """Test creating engine from GraphContext."""
        context = SimpleGraphContext(
            age_name=test_graph_name,
            organization_id="test-org"
        )
        
        engine = AgeEngineFactory.from_context(context)
        
        assert engine.graph_name == test_graph_name
        
        # Create and drop the graph to verify connection works
        try:
            engine.execute_raw(f"SELECT * FROM ag_catalog.create_graph('{test_graph_name}')")
            engine.execute_raw(f"SELECT * FROM ag_catalog.drop_graph('{test_graph_name}', true)")
        except Exception as e:
            # Graph might already exist in some edge cases
            if "already exists" not in str(e):
                raise
    
    @pytest.mark.django_db(transaction=True)
    def test_from_graph_name(self, db, backend_stack, test_graph_name):
        """Test creating engine directly from graph name."""
        engine = AgeEngineFactory.from_graph_name(test_graph_name)
        
        assert engine.graph_name == test_graph_name


class TestGraphControllerWithAgeEngine:
    """Integration tests for GraphController with real AGE engine."""
    
    @pytest.fixture
    def sample_schema(self):
        """Create a sample schema for testing."""
        return GraphDefinitionModel.model_validate({
            "extensions": {
                "entities": {
                    "Cell": {
                        "label": "Cell",
                        "description": "A biological cell",
                        "properties": {
                            "name": {
                                "type": "string",
                                "required": True,
                                "description": "Cell name"
                            },
                            "size": {
                                "type": "float",
                                "required": False,
                                "description": "Cell size in micrometers"
                            }
                        }
                    }
                }
            }
        })
    
    @pytest.mark.django_db(transaction=True)
    def test_controller_with_graph_context(self, age_engine, sample_schema):
        """Test creating a controller with graph context."""
        # Create graph context with engine
        class TestGraphContext:
            def __init__(self, engine, definition, age_name, org_id):
                self.engine = engine
                self.definition = definition
                self.age_name = age_name
                self.organization_id = org_id
        
        context = TestGraphContext(
            engine=age_engine,
            definition=sample_schema,
            age_name=age_engine.graph_name,
            org_id="test-org"
        )
        
        controller = GraphController(graph=context)
        
        assert controller.engine is age_engine
        assert controller.age_name == age_engine.graph_name
        assert controller.organization_id == "test-org"
    
    @pytest.mark.django_db(transaction=True)
    def test_create_entity_with_real_engine(self, age_engine, sample_schema):
        """Test creating an entity with the real AGE engine."""
        controller = GraphController(engine=age_engine, schema=sample_schema)
        
        payload = EntityCreationPayload(
            ref_id="test-ref-1",
            kind="Cell",
            properties={"name": "Neuron", "size": 15.5},
            provenance=ProvenanceInput(
                user="test-user",
                action="create"
            ),
            supporting_evidence=[
                EvidenceInput(
                    id="evidence-1",
                    identifier="default",
                    properties={"source": "microscopy"},
                    measurements=[
                        MeasurementInput(
                            key="intensity",
                            value=0.85,
                            unit="AU",
                            confidence=0.95
                        )
                    ]
                )
            ]
        )
        
        result = controller.create_entity(payload)
        
        assert result.ref_id == "test-ref-1"
        assert result.graph_id is not None
        
        # Verify the entity was created in the graph
        verify_result = age_engine.execute(
            "MATCH (c:Cell {name: 'Neuron'}) RETURN c.name as name, c.size as size"
        )
        
        assert len(verify_result) == 1
        assert verify_result[0]["name"] == "Neuron"


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
