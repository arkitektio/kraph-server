"""
Tests for the Graph Definition API.

These tests verify that:
1. Schema definitions can be validated
2. Schema definitions can be set on a graph
3. Schema versions can be managed
4. Entity creation works with schema definitions
"""
import pytest
import kante
from kante.context import HttpContext

# ===========================================
# VALIDATE SCHEMA TESTS
# ===========================================

@pytest.mark.asyncio
async def test_validate_schema_valid(api_schema: kante.Schema, simple_api_context: HttpContext):
    """Test validating a valid schema definition."""
    
    mutation = """
        mutation ValidateSchema($input: ValidateSchemaInput!) {
            validateSchema(input: $input) {
                isValid
                errors {
                    location
                    message
                    type
                }
                warnings {
                    location
                    message
                    type
                }
            }
        }
    """
    
    definition = {
        "system_version": "1.0.0",
        "extensions": {
            "structures": [
                {"key": "ROI", "description": "Region of Interest"}
            ],
            "entities": [
                {
                    "key": "Cell",
                    "description": "A biological cell",
                    "properties": [
                        {"key": "name", "type": "STRING"}
                    ]
                }
            ],
            "relations": [],
            "events": []
        }
    }

    result = await api_schema.execute(
        mutation,
        variable_values={
            "input": {
                "definition": definition
            }
        },
        context_value=simple_api_context,
    )

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data is not None, "No data returned from GraphQL execution"
    assert result.data["validateSchema"]["isValid"] is True
    assert len(result.data["validateSchema"]["errors"]) == 0


@pytest.mark.asyncio
async def test_validate_schema_invalid_version(api_schema: kante.Schema, simple_api_context: HttpContext):
    """Test validating a schema with invalid version format."""
    
    mutation = """
        mutation ValidateSchema($input: ValidateSchemaInput!) {
            validateSchema(input: $input) {
                isValid
                errors {
                    location
                    message
                    type
                }
            }
        }
    """
    
    # Invalid version - not semver
    definition = {
        "system_version": "not-a-version",
        "extensions": {
            "structures": [],
            "entities": [
                {"key": "Cell", "description": "A cell"}
            ],
            "relations": [],
            "events": []
        }
    }

    result = await api_schema.execute(
        mutation,
        variable_values={
            "input": {
                "definition": definition
            }
        },
        context_value=simple_api_context,
    )

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data is not None, "No data returned from GraphQL execution"
    assert result.data["validateSchema"]["isValid"] is False
    assert len(result.data["validateSchema"]["errors"]) > 0


@pytest.mark.asyncio
async def test_validate_schema_missing_entity_key(api_schema: kante.Schema, simple_api_context: HttpContext):
    """Test validating a schema with missing entity key."""
    
    mutation = """
        mutation ValidateSchema($input: ValidateSchemaInput!) {
            validateSchema(input: $input) {
                isValid
                errors {
                    location
                    message
                    type
                }
            }
        }
    """
    
    # Entity without key
    definition = {
        "system_version": "1.0.0",
        "extensions": {
            "structures": [],
            "entities": [
                {"description": "Missing key entity"}  # No key!
            ],
            "relations": [],
            "events": []
        }
    }

    result = await api_schema.execute(
        mutation,
        variable_values={
            "input": {
                "definition": definition
            }
        },
        context_value=simple_api_context,
    )

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data is not None, "No data returned from GraphQL execution"
    assert result.data["validateSchema"]["isValid"] is False
    errors = result.data["validateSchema"]["errors"]
    assert len(errors) > 0
    # Should have error about missing key
    error_messages = [e["message"] for e in errors]
    assert any("key" in msg.lower() or "required" in msg.lower() for msg in error_messages)


@pytest.mark.asyncio
async def test_validate_schema_with_relations(api_schema: kante.Schema, simple_api_context: HttpContext):
    """Test validating a schema with relation definitions."""
    
    mutation = """
        mutation ValidateSchema($input: ValidateSchemaInput!) {
            validateSchema(input: $input) {
                isValid
                errors {
                    location
                    message
                }
                warnings {
                    location
                    message
                }
            }
        }
    """
    
    definition = {
        "system_version": "1.0.0",
        "extensions": {
            "structures": [],
            "entities": [
                {"key": "Neuron", "description": "A neuron"},
                {"key": "Synapse", "description": "A synapse"}
            ],
            "relations": [
                {
                    "key": "CONNECTS_TO",
                    "source": ["Neuron"],
                    "target": ["Neuron"]
                }
            ],
            "events": []
        }
    }

    result = await api_schema.execute(
        mutation,
        variable_values={
            "input": {
                "definition": definition
            }
        },
        context_value=simple_api_context,
    )

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data is not None, "No data returned from GraphQL execution"
    assert result.data["validateSchema"]["isValid"] is True


@pytest.mark.asyncio
async def test_validate_schema_with_properties(api_schema: kante.Schema, simple_api_context: HttpContext):
    """Test validating a schema with property definitions on entities."""
    
    mutation = """
        mutation ValidateSchema($input: ValidateSchemaInput!) {
            validateSchema(input: $input) {
                isValid
                errors {
                    location
                    message
                }
            }
        }
    """
    
    definition = {
        "system_version": "1.0.0",
        "extensions": {
            "structures": [
                {"key": "ROI", "description": "Region of interest"}
            ],
            "entities": [
                {
                    "key": "Cell",
                    "description": "A cell",
                    "properties": [
                        {"key": "name", "type": "STRING"},
                        {"key": "volume", "type": "FLOAT"},
                        {"key": "count", "type": "INTEGER"}
                    ]
                }
            ],
            "relations": [],
            "events": []
        }
    }

    result = await api_schema.execute(
        mutation,
        variable_values={
            "input": {
                "definition": definition
            }
        },
        context_value=simple_api_context,
    )

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data["validateSchema"]["isValid"] is True


@pytest.mark.asyncio
async def test_validate_schema_empty_extensions_warning(api_schema: kante.Schema, simple_api_context: HttpContext):
    """Test that empty extensions generate warnings."""
    
    mutation = """
        mutation ValidateSchema($input: ValidateSchemaInput!) {
            validateSchema(input: $input) {
                isValid
                errors {
                    location
                    message
                }
                warnings {
                    location
                    message
                    type
                }
            }
        }
    """
    
    definition = {
        "system_version": "1.0.0",
        "extensions": {
            "structures": [],
            "entities": [],  # Empty - should warn
            "relations": [],  # Empty - should warn
            "events": []
        }
    }

    result = await api_schema.execute(
        mutation,
        variable_values={
            "input": {
                "definition": definition
            }
        },
        context_value=simple_api_context,
    )

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    # Still valid, but should have warnings
    assert result.data["validateSchema"]["isValid"] is True
    warnings = result.data["validateSchema"]["warnings"]
    assert len(warnings) >= 2  # At least empty_entities and empty_relations


# ===========================================
# COMPLEX SCHEMA VALIDATION TESTS
# ===========================================

@pytest.mark.asyncio
async def test_validate_connectome_schema(api_schema: kante.Schema, simple_api_context: HttpContext):
    """Test validating a complex connectome-style schema."""
    
    mutation = """
        mutation ValidateSchema($input: ValidateSchemaInput!) {
            validateSchema(input: $input) {
                isValid
                errors {
                    location
                    message
                }
            }
        }
    """
    
    definition = {
        "system_version": "1.0.0",
        "extensions": {
            "structures": [
                {"key": "ROI", "description": "Region of Interest"},
                {"key": "ToldYouSo", "description": "Evidence structure"}
            ],
            "entities": [
                {
                    "key": "Neuron",
                    "description": "A neuron",
                    "properties": [
                        {"key": "neuron_id", "type": "STRING"},
                        {"key": "cell_type", "type": "STRING"}
                    ]
                },
                {
                    "key": "Synapse",
                    "description": "A synapse",
                    "properties": [
                        {"key": "strength", "type": "FLOAT"}
                    ]
                },
                {
                    "key": "Region",
                    "description": "Brain region",
                    "properties": [
                        {"key": "name", "type": "STRING"}
                    ]
                }
            ],
            "relations": [
                {
                    "key": "CONNECTS_TO",
                    "source": ["Neuron"],
                    "target": ["Neuron"]
                },
                {
                    "key": "LOCATED_IN",
                    "source": ["Neuron"],
                    "target": ["Region"]
                }
            ],
            "events": [
                {
                    "key": "Activation",
                    "inputs": ["Neuron"],
                    "outputs": ["Neuron"]
                }
            ]
        }
    }

    result = await api_schema.execute(
        mutation,
        variable_values={
            "input": {
                "definition": definition
            }
        },
        context_value=simple_api_context,
    )

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data is not None, "No data returned from GraphQL execution"
    assert result.data["validateSchema"]["isValid"] is True


@pytest.mark.asyncio
async def test_validate_schema_with_derived_properties(api_schema: kante.Schema, simple_api_context: HttpContext):
    """Test validating a schema with derived properties and rollup rules."""
    
    mutation = """
        mutation ValidateSchema($input: ValidateSchemaInput!) {
            validateSchema(input: $input) {
                isValid
                errors {
                    location
                    message
                }
            }
        }
    """
    
    definition = {
        "system_version": "1.0.0",
        "extensions": {
            "structures": [
                {"key": "ROI", "description": "Region of Interest"}
            ],
            "entities": [
                {
                    "key": "Cell",
                    "description": "A cell",
                    "properties": [
                        {
                            "key": "avg_volume",
                            "type": "FLOAT",
                            "derivation": "ROLLUP",
                            "rule": {
                                "source_node": "ROI",
                                "key": "volume",
                                "aggregation": "MEAN"
                            }
                        }
                    ]
                }
            ],
            "relations": [],
            "events": []
        }
    }

    result = await schema.execute(
        mutation,
        variable_values={
            "input": {
                "definition": definition
            }
        },
        context_value=simple_api_context,
    )

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data["validateSchema"]["isValid"] is True


@pytest.mark.asyncio
async def test_validate_schema_with_materialization(api_schema: kante.Schema, simple_api_context: HttpContext):
    """Test validating a schema with relation materialization config."""
    
    mutation = """
        mutation ValidateSchema($input: ValidateSchemaInput!) {
            validateSchema(input: $input) {
                isValid
                errors {
                    location
                    message
                }
            }
        }
    """
    
    definition = {
        "system_version": "1.0.0",
        "extensions": {
            "structures": [
                {"key": "ROI", "description": "Region of Interest"}
            ],
            "entities": [
                {"key": "AIS", "description": "Axon Initial Segment"},
                {"key": "Soma", "description": "Cell body"}
            ],
            "relations": [
                {
                    "key": "IS_CONNECTED_TO",
                    "source": ["AIS"],
                    "target": ["Soma"],
                    "cardinality": "1:1",
                    "materialization": {
                        "backing_link_type": "link_ais_soma",
                        "desired_evidence": [
                            {"key": "alignment", "unit": "score"},
                            {"key": "proximity", "unit": "um"}
                        ],
                        "properties": [
                            {"key": "distance", "type": "FLOAT"}
                        ]
                    }
                }
            ],
            "events": []
        }
    }

    result = await api_schema.execute(
        mutation,
        variable_values={
            "input": {
                "definition": definition
            }
        },
        context_value=simple_api_context,
    )

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data["validateSchema"]["isValid"] is True
