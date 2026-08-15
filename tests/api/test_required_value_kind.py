"""Every measurement input names its value kind.

The regression test for a dead end. When `value_kind` became part of a metric
term's identity, a key could hold two terms — and `ensure_metric_kind` refused an
undeclared write against such a key with "Declare one". But only
`AssertMetricValueInput` had a `value_kind` to declare with: `createMetric`,
`updateMetric` and the supporting-evidence metrics on `createEntity` all took the
undeclared branch. An organization with `roi.confidence` as both FLOAT and STRING
could not write that key through any of them, and the error told them to do
something the schema did not permit.

Requiring the field on the `MetricInput` base removes the branch rather than
repairing it. Asserted against the schema type map as well as through behaviour —
a field that quietly goes optional again would keep every test below passing
while re-opening the hole.
"""

import uuid

import kante
import pytest
from kante.context import HttpContext

from core import models as core_models
from evidence import models as evidence_models

MEASUREMENT_INPUTS = ["MetricInput", "AssertMetricValueInput", "AssertMetricValueForStructureInput", "SupersedeMetricValueInput"]

RECORD = """
mutation RecordMetric($input: AssertMetricValueInput!) {
    assertMetricValue(input: $input) { metric { id value } }
}
"""

CREATE = """
mutation CreateMetric($input: AssertMetricValueForStructureInput!) {
    assertMetricValueForStructure(input: $input) { metric { id value } }
}
"""


@pytest.mark.parametrize("type_name", MEASUREMENT_INPUTS)
def test_the_input_requires_a_value_kind(api_schema: kante.Schema, type_name: str) -> None:
    """Non-null, on every input that carries a measurement."""
    graphql_type = api_schema._schema.type_map[type_name]
    field = graphql_type.fields.get("valueKind")

    assert field is not None, f"{type_name} must name a value kind"
    assert str(field.type).endswith("!"), f"{type_name}.valueKind is {field.type}, which lets a caller omit it again"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_metric_works_on_a_key_with_several_terms(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The dead end itself. This mutation had no way to succeed.

    Two terms are established through `recordMetric` — the one input that could
    always declare — and then `createMetric`, which could not, writes to the same
    key. Before `value_kind` moved onto the base this failed with "Declare one".
    """
    identifier = f"@test/deadend_{uuid.uuid4().hex[:6]}"
    object_id = "obj-1"

    for kind, value in (("FLOAT", 0.9), ("STRING", "high")):
        recorded = await api_schema.execute(
            RECORD,
            variable_values={"input": {"identifier": identifier, "object": object_id, "key": "confidence", "value": value, "valueKind": kind}},
            context_value=simple_api_context,
        )
        assert recorded.errors is None, f"GraphQL errors: {recorded.errors}"

    structure = await evidence_models.Structure.all_objects.filter(object=object_id, identifier=identifier).afirst()
    assert structure is not None

    created = await api_schema.execute(
        CREATE,
        variable_values={"input": {"structure": str(structure.pk), "key": "confidence", "value": "medium", "valueKind": "STRING"}},
        context_value=simple_api_context,
    )

    assert created.errors is None, f"createMetric must reach a named term: {created.errors}"
    assert created.data["assertMetricValueForStructure"]["metric"]["value"] == "medium"

    metric = await evidence_models.Metric.all_objects.filter(structure=structure, key="confidence", value_txt="medium").select_related("kind").afirst()
    assert metric is not None
    assert metric.value_kind == "STRING", "…the term it named, not whichever one was found first"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_declared_kind_selects_the_term(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """`createMetric` reaches the term it names, not one inference would pick.

    Proves the field is wired through `_record_metric` and not merely present in
    the schema. `12.5` looks like a float from every angle; declaring STRING has
    to win anyway.
    """
    identifier = f"@test/wired_{uuid.uuid4().hex[:6]}"

    recorded = await api_schema.execute(
        RECORD,
        variable_values={"input": {"identifier": identifier, "object": "obj-1", "key": "area", "value": 1.0, "valueKind": "FLOAT"}},
        context_value=simple_api_context,
    )
    assert recorded.errors is None, f"GraphQL errors: {recorded.errors}"

    # `select_related`: `structure.kind` below is a lazy FK, and touching it in
    # an async test raises SynchronousOnlyOperation rather than querying.
    structure = await evidence_models.Structure.all_objects.filter(object="obj-1", identifier=identifier).select_related("kind").afirst()
    assert structure is not None

    created = await api_schema.execute(
        CREATE,
        variable_values={"input": {"structure": str(structure.pk), "key": "area", "value": 12.5, "valueKind": "STRING"}},
        context_value=simple_api_context,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"

    kinds = {term.value_kind async for term in evidence_models.MetricKind.all_objects.filter(structure_kind=structure.kind, key="area")}
    assert kinds == {"FLOAT", "STRING"}

    metric = await evidence_models.Metric.all_objects.filter(structure=structure, value_txt="12.5").afirst()
    assert metric is not None, "The declared STRING term must have received it, filed in value_txt"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_supporting_evidence_can_name_a_kind_too(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The path that could never declare, and therefore could never disambiguate.

    Supporting-evidence metrics inherit `value_kind` from the base like every
    other measurement input, so an entity's evidence can name a term the same way
    a direct write does.
    """
    graphql_type = api_schema._schema.type_map["StructureReferenceInput"]
    metrics_field = graphql_type.fields["metrics"]

    assert "MetricInput" in str(metrics_field.type), f"Supporting evidence must carry MetricInput, got {metrics_field.type}"
