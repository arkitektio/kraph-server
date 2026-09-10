"""Claim lists page, filter and order at the log's grain (C4).

`entities`, `structures` and their kin read claim rows: ids are the claims',
ordering is the log's, and a filter the drawing could only approximate is
refused rather than narrowed silently.
"""

import pytest
import kante
from kante.context import HttpContext
from core import models as core_models
from tests.support import claims, reads, writes


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
            # was a drawn vertex id — an identifier reassigned by every
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


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_list_structures_with_filters_ordering_and_pagination(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
):
    structure_kind = await claims.ensure_kind(test_graph)

    create_structure_mutation = """
        mutation CreateStructure($input: AssertStructureExistsInput!) {
            assertStructureExists(input: $input) { structure { id object } }
        }
    """

    async def create_structure(object_id: str) -> str:
        result = await api_schema.execute(
            create_structure_mutation,
            variable_values={
                "input": {
                    "identifier": structure_kind.identifier,
                    "object": object_id,
                    "metrics": [],
                }
            },
            context_value=simple_api_context,
        )

        assert result.errors is None, f"GraphQL errors: {result.errors}"
        assert result.data is not None
        return result.data["assertStructureExists"]["structure"]["id"]

    structure_id_a = await create_structure("roi-structure-a")
    structure_id_b = await create_structure("roi-structure-b")
    structure_id_c = await create_structure("roi-structure-c")

    list_query = """
        query ListStructures($structureKindId: ID!, $filters: StructureFilter, $ordering: [StructureOrder!], $pagination: StructurePaginationInput) {
            structures(
                structureKindId: $structureKindId
                filters: $filters
                ordering: $ordering
                pagination: $pagination
            ) {
                id
                object
                identifier
            }
        }
    """

    listed = await api_schema.execute(
        list_query,
        variable_values={
            "structureKindId": str(structure_kind.pk),
            "filters": {
                "ids": [structure_id_b, structure_id_c],
            },
            "ordering": [{"createdAt": "ASC"}],
            "pagination": {"offset": 0, "limit": 10},
        },
        context_value=simple_api_context,
    )

    assert listed.errors is None, f"GraphQL errors: {listed.errors}"
    assert listed.data is not None

    structures = listed.data["structures"]
    returned_ids = [structure["id"] for structure in structures]

    assert structure_id_a not in returned_ids
    assert structure_id_b in returned_ids
    assert structure_id_c in returned_ids

    # Ordering is asserted by creation order, not by parsing the id. Structure ids
    # are uuid primary keys now, not `{graph}:{age_node_id}` composites, so there
    # is no monotonic component to split out — and ordering by a uuid4 would be
    # arbitrary rather than meaningful.
    assert returned_ids == [structure_id_b, structure_id_c]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_claim_lists_order_by_the_logs_own_order(api_schema, simple_api_context, test_graph) -> None:
    first = await writes.create_entity(api_schema, simple_api_context, "AIS")
    second = await writes.create_entity(api_schema, simple_api_context, "AIS")

    read = await api_schema.execute(reads.NODES_BY_SEQ, variable_values={"graph": str(test_graph.pk)}, context_value=simple_api_context)
    assert read.errors is None, f"GraphQL errors: {read.errors}"
    ids = [row["id"] for row in read.data["nodes"]]
    assert ids.index(second) < ids.index(first), "the later act comes first under seq DESC"


def test_the_page_window_is_clamped() -> None:
    """A `limit` above the ceiling is the ceiling; a missing one is the default; never an error.

    History: every list but `changes` accepted `limit: 10000000` as written.
    """
    from api import pagination

    assert pagination.window(None) == (0, pagination.DEFAULT_LIMIT)
    assert pagination.window(type("P", (), {"offset": 20, "limit": 5000})()) == (20, pagination.MAX_LIMIT)
    assert pagination.window(type("P", (), {"offset": -3, "limit": 0})()) == (0, pagination.DEFAULT_LIMIT)
    assert pagination.MAX_LIMIT == 1000


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_limit_above_the_ceiling_is_not_an_error(api_schema, simple_api_context, test_graph) -> None:
    await writes.create_entity(api_schema, simple_api_context, "AIS")

    result = await api_schema.execute(reads.NODES_PAGED, variable_values={"graph": str(test_graph.id), "pagination": {"limit": 5000, "offset": 0}}, context_value=simple_api_context)
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert 1 <= len(result.data["nodes"]) <= 1000
