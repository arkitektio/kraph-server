"""Recording a measurement names no graph.

The user-visible half of the change. Evidence rows were already organization-
scoped; what still forced a graph into every ingest call was the *ontology* —
structure and metric categories hung off `Graph` through the polymorphic
`Category` base, so resolving "what kind of thing is `@mikro/roi`" needed a
projection that had nothing to do with the measurement.

Asserted against the schema itself rather than only through behaviour: a `graph`
argument that quietly comes back would still work for callers who pass one, and
nothing else would notice.
"""

import uuid

import kante
import pytest
from kante.context import HttpContext

from core import models as core_models
from evidence import models as evidence_models

INGEST_INPUTS = ["RecordMetricInput", "CreateStructureInput", "EnsureStructureInput"]


@pytest.mark.parametrize("type_name", INGEST_INPUTS)
def test_the_input_has_no_graph_field(api_schema: kante.Schema, type_name: str) -> None:
    """No ingest input may name a graph."""
    graphql_type = api_schema._schema.type_map[type_name]
    assert "graph" not in graphql_type.fields, f"{type_name} still takes a graph"


@pytest.mark.parametrize("type_name", INGEST_INPUTS)
def test_the_input_names_a_structure_identifier(api_schema: kante.Schema, type_name: str) -> None:
    """What replaced it: the identifier of the datum being measured."""
    graphql_type = api_schema._schema.type_map[type_name]
    assert "identifier" in graphql_type.fields, f"{type_name} must identify the datum it describes"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_measurement_round_trips_with_no_graph_anywhere(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Write it, read it back, with no projection named in either direction."""
    object_id = f"obj_{uuid.uuid4().hex[:8]}"

    recorded = await api_schema.execute(
        """
        mutation RecordMetric($input: RecordMetricInput!) {
            recordMetric(input: $input) { id value unit }
        }
        """,
        variable_values={
            "input": {
                "identifier": "@mikro/roi",
                "object": object_id,
                "key": "vector_length",
                "value": 45.2,
                "valueKind": "FLOAT",
                "unit": "um",
            }
        },
        context_value=simple_api_context,
    )

    assert recorded.errors is None, f"GraphQL errors: {recorded.errors}"
    assert recorded.data["recordMetric"]["value"] == 45.2
    assert recorded.data["recordMetric"]["unit"] == "um"

    structure = await evidence_models.Structure.all_objects.filter(object=object_id).afirst()
    assert structure is not None
    assert await evidence_models.Metric.all_objects.filter(structure=structure).acount() == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_kind_is_minted_by_the_write_that_needs_it(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Vocabulary is discovered, not declared.

    No graph had to describe `@test/brand_new` in advance, and there is no
    permission gate to pass — the identifier belongs to the service that produced
    the datum.
    """
    identifier = f"@test/brand_new_{uuid.uuid4().hex[:6]}"

    result = await api_schema.execute(
        """
        mutation RecordMetric($input: RecordMetricInput!) {
            recordMetric(input: $input) { id }
        }
        """,
        variable_values={
            "input": {
                "identifier": identifier,
                "object": "obj-1",
                "key": "brightness",
                "value": 7.0,
                "valueKind": "FLOAT",
            }
        },
        context_value=simple_api_context,
    )

    assert result.errors is None, f"GraphQL errors: {result.errors}"

    kind = await evidence_models.StructureKind.all_objects.filter(identifier=identifier).afirst()
    assert kind is not None, "The structure kind must be created by the write"
    assert kind.organization_id == test_graph.organization_id

    metric_kind = await evidence_models.MetricKind.all_objects.filter(structure_kind=kind, key="brightness").afirst()
    assert metric_kind is not None, "So must the metric kind"
    assert metric_kind.value_kind == "FLOAT", "…in the canonical vocabulary, not the input spelling"
