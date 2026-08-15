"""`recordMetric` honours the value kind the caller declared.

`AssertMetricValueInput.value_kind` has always been a **required** field, and until
this change nothing read it: both write paths called `_infer_metric_value_kind`
on the Python value and threw the declaration away. Recording `7.0` as a STRING
produced a FLOAT term, and the caller was never told.

That was nearly invisible while a key had one term regardless. Once `value_kind`
became part of `MetricKind`'s identity it stopped being invisible: term identity
would have been decided by `type(value)`, so `45` would mint INT and `45.2`
FLOAT under one key, on the first two measurements, silently.

So this file asserts the declaration beats inference — the precondition the rest
of the change rests on.
"""

import uuid

import kante
import pytest
from kante.context import HttpContext

from core import models as core_models
from evidence import models as evidence_models

RECORD = """
mutation RecordMetric($input: AssertMetricValueInput!) {
    assertMetricValue(input: $input) { metric { id value } }
}
"""


async def _record(api_schema: kante.Schema, context: HttpContext, **fields: object) -> object:
    result = await api_schema.execute(RECORD, variable_values={"input": fields}, context_value=context)
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    return result


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_declared_string_beats_a_float_looking_value(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """`7.0` declared STRING mints a STRING term, not a FLOAT one.

    Inference would say FLOAT. The caller said STRING, and the caller knows what
    they are measuring — inference cannot tell a CATEGORY from a STRING either,
    which is why it is a fallback and not the rule.
    """
    identifier = f"@test/declared_{uuid.uuid4().hex[:6]}"

    await _record(
        api_schema,
        simple_api_context,
        identifier=identifier,
        object="obj-1",
        key="confidence",
        value=7.0,
        valueKind="STRING",
    )

    kind = await evidence_models.StructureKind.all_objects.filter(identifier=identifier).afirst()
    assert kind is not None

    terms = [term async for term in evidence_models.MetricKind.all_objects.filter(structure_kind=kind, key="confidence")]
    assert len(terms) == 1
    assert terms[0].value_kind == "STRING", "The declaration decides the term, not type(value)"

    metric = await evidence_models.Metric.all_objects.filter(kind=terms[0]).afirst()
    assert metric is not None
    assert metric.value_kind == "STRING", "And the row agrees with its own term"
    assert metric.value == "7.0", "Filed in value_txt, so it reads back as text"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_two_declarations_of_one_key_coexist(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The behaviour the change is for: neither write is refused.

    This used to raise. One tool measuring `confidence` as a number and another
    as a label were treated as contradicting each other, and whichever arrived
    second lost — refusing a fact about the world because someone else reached
    the key first.
    """
    identifier = f"@test/coexist_{uuid.uuid4().hex[:6]}"

    await _record(api_schema, simple_api_context, identifier=identifier, object="obj-1", key="confidence", value=0.9, valueKind="FLOAT")
    await _record(api_schema, simple_api_context, identifier=identifier, object="obj-1", key="confidence", value="high", valueKind="STRING")

    kind = await evidence_models.StructureKind.all_objects.filter(identifier=identifier).afirst()
    assert kind is not None

    terms = {term.value_kind async for term in evidence_models.MetricKind.all_objects.filter(structure_kind=kind, key="confidence")}
    assert terms == {"FLOAT", "STRING"}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_lowercase_input_spelling_is_normalised(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The GraphQL enum and storage disagree on spelling; the term uses storage's.

    Left unnormalised, "float" and FLOAT would be two terms under the four-tuple
    identity, and the lowercase one would carry a kind `writer.value_columns`
    rejects — so its values would have nowhere to be written at all.
    """
    identifier = f"@test/spelling_{uuid.uuid4().hex[:6]}"

    await _record(api_schema, simple_api_context, identifier=identifier, object="obj-1", key="area", value=3.5, valueKind="FLOAT")

    kind = await evidence_models.StructureKind.all_objects.filter(identifier=identifier).afirst()
    terms = [term async for term in evidence_models.MetricKind.all_objects.filter(structure_kind=kind, key="area")]

    assert len(terms) == 1
    assert terms[0].value_kind == "FLOAT", "…in the canonical vocabulary, not the input spelling"
