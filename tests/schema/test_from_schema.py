from typing import Any, Dict

import pytest
from api.schema import schema
from graph_engine.input_models import GraphDefinitionInput
from kante.context import HttpContext


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
                            "propertyDefinitions": [
                                {
                                    "key": "name",
                                    "valueKind": "STRING",
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
