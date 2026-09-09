import pytest
import kante
from kante.context import HttpContext
from core import models as core_models


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_list_entities_filtered_by_property_with_supporting_evidence(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
):
    entity_category = await test_graph.aget_entity_def("AIS")

    create_entity_mutation = """
        mutation CreateEntity($input: AssertEntityExistsInput!) {
            assertEntityExists(input: $input) { instance { id term { key } } }
        }
    """

    async def create_ais_with_length(object_id: str, length: float) -> str:
        result = await api_schema.execute(
            create_entity_mutation,
            variable_values={
                "input": {
                    "term": entity_category.key,
                    "supportingEvidence": [
                        {
                            "identifier": "@mikro/roi",
                            "object": object_id,
                            "metrics": [
                                {
                                    "key": "vector_length",
                                    "value": length,
                                    "valueKind": "FLOAT",
                                }
                            ],
                        }
                    ],
                }
            },
            context_value=simple_api_context,
        )

        assert result.errors is None, f"GraphQL errors: {result.errors}"
        assert result.data is not None
        assert result.data["assertEntityExists"]["instance"]["term"]["key"] == "AIS"
        return result.data["assertEntityExists"]["instance"]["id"]

    entity_id_small = await create_ais_with_length("roi-entity-small", 5.0)
    entity_id_large_1 = await create_ais_with_length("roi-entity-large-1", 25.0)
    entity_id_large_2 = await create_ais_with_length("roi-entity-large-2", 40.0)

    list_query = """
        query ListEntities($entityCategoryId: ID!, $filters: EntityFilter) {
            entities(entityCategoryId: $entityCategoryId, filters: $filters) {
                id
                properties
            }
        }
    """

    listed = await api_schema.execute(
        list_query,
        variable_values={
            "entityCategoryId": str(entity_category.pk),
            # Selected by id rather than by an ordering over ids. This used to
            # filter `id GREATER_THAN <n>`, which only meant anything while an id
            # was an integer AGE vertex id — an identifier reassigned by every
            # reproject, so the comparison ordered entities by an accident of
            # storage. Ids are uuids now and have no order to compare.
            "filters": {"ids": [entity_id_large_1, entity_id_large_2]},
        },
        context_value=simple_api_context,
    )

    assert listed.errors is None, f"GraphQL errors: {listed.errors}"
    assert listed.data is not None

    entities = listed.data["entities"]
    returned_ids = {entity["id"] for entity in entities}

    assert returned_ids == {entity_id_large_1, entity_id_large_2}
    assert entity_id_small not in returned_ids

