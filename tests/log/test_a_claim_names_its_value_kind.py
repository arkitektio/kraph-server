"""A value that does not match its declared kind says so.

The complement to making `value_kind` required. While the write path guessed, a
mismatch was the system's fault and the best it could do was fail somewhere
downstream. Now the caller states the kind, so a mismatch is their own
declaration disagreeing with what they sent — and the error should say that
rather than surfacing `could not convert string to float: 'high'` from inside
`float()`, which names neither the key nor the kind and leaves a caller batching
many measurements to work out which one it came from.
"""

import pytest
from authentikate.models import Organization
from core.enums import ValueKind
from evidence import models as evidence_models
from evidence import writer
import uuid
import kante
from kante.context import HttpContext
from core import models as core_models
from datetime import datetime, timezone


def test_a_string_under_a_float_term_names_all_three(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
    assertion: evidence_models.Assertion,
) -> None:
    """The key, the declared kind, and the value that did not fit."""
    structure = writer.ensure_structure(organization, roi_kind, "roi-mismatch", assertion)
    term = writer.ensure_metric_kind(organization, roi_kind, "vector_length", ValueKind.FLOAT)

    with pytest.raises(ValueError) as excinfo:
        writer.record_metric(organization, structure, term, key="vector_length", value="high", assertion=assertion)

    message = str(excinfo.value)
    assert "vector_length" in message, "…so a failure inside a batch can be located"
    assert "FLOAT" in message, "…so the caller can see which declaration is being enforced"
    assert "high" in message, "…and which value broke it"


def test_the_underlying_cause_is_kept(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
    assertion: evidence_models.Assertion,
) -> None:
    """Wrapped, not swallowed. The original coercion failure stays reachable.

    Losing it would trade one unhelpful error for a different one — the wrapper
    says what was declared, the cause says what the conversion actually objected
    to.
    """
    structure = writer.ensure_structure(organization, roi_kind, "roi-cause", assertion)
    term = writer.ensure_metric_kind(organization, roi_kind, "count", ValueKind.INT)

    with pytest.raises(ValueError) as excinfo:
        writer.record_metric(organization, structure, term, key="count", value="not a number", assertion=assertion)

    assert excinfo.value.__cause__ is not None, "The coercion error must survive as __cause__"


def test_a_value_that_does_fit_is_untouched(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
    assertion: evidence_models.Assertion,
) -> None:
    """The wrapper must not change what a well-formed write does.

    Coercion across compatible types is deliberate — an INT term accepts `3` and
    a STRING term accepts `12.5` as text — and only genuine failures are
    reported.
    """
    structure = writer.ensure_structure(organization, roi_kind, "roi-fits", assertion)

    as_text = writer.ensure_metric_kind(organization, roi_kind, "label", ValueKind.STRING)
    recorded = writer.record_metric(organization, structure, as_text, key="label", value=12.5, assertion=assertion)
    assert recorded.value == "12.5", "A STRING term stores a number as its text"

    as_int = writer.ensure_metric_kind(organization, roi_kind, "count", ValueKind.INT)
    counted = writer.record_metric(organization, structure, as_int, key="count", value=3, assertion=assertion)
    assert counted.value == 3
    assert type(counted.value) is int, "INT shares value_num with FLOAT and has to narrow back on the way out"


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


MEASUREMENT_INPUTS = ["MetricInput", "AssertMetricValueInput", "AssertMetricValueForStructureInput", "SupersedeMetricValueInput"]
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


LAST_YEAR = datetime(2025, 3, 1, 9, 0, tzinfo=timezone.utc)


TODAY = datetime(2026, 8, 11, 9, 0, tzinfo=timezone.utc)


def _structure(
    organization: Organization,
    category: evidence_models.StructureKind,
    assertion: evidence_models.Assertion,
    object_id: str = "roi-1",
) -> evidence_models.Structure:
    """A structure to hang measurements off."""
    return evidence_models.Structure.objects.create_for_organization(
        organization=organization,
        kind=category,
        identifier="@mikro/roi",
        object=object_id,
        assertion=assertion,
    )


def test_value_kind_selects_the_value_column(organization: Organization, roi_category_a: evidence_models.StructureKind, length_category: evidence_models.MetricKind, assertion: evidence_models.Assertion) -> None:
    """Each ValueKind reads back through the column its kind designates.

    The typed-column split is what keeps numeric aggregation in the database
    instead of in Python, so the mapping has to be exhaustive and exercised.
    """
    structure = _structure(organization, roi_category_a, assertion)

    cases = [
        (ValueKind.FLOAT, {"value_num": 45.2}, 45.2),
        (ValueKind.INT, {"value_num": 3}, 3),
        (ValueKind.STRING, {"value_txt": "apical"}, "apical"),
        (ValueKind.CATEGORY, {"value_txt": "neuron"}, "neuron"),
        (ValueKind.BOOLEAN, {"value_bool": True}, True),
        (ValueKind.DATETIME, {"value_time": LAST_YEAR}, LAST_YEAR),
        (ValueKind.THREE_D_VECTOR, {"value_json": [1.0, 2.0, 3.0]}, [1.0, 2.0, 3.0]),
    ]

    for kind, columns, expected in cases:
        metric = evidence_models.Metric.objects.create_for_organization(
            organization=organization,
            structure=structure,
            kind=length_category,
            key=f"probe_{kind.value}",
            value_kind=kind.value,
            observed_at=LAST_YEAR,
            asserted_at=TODAY,
            assertion=assertion,
            **columns,
        )
        metric.refresh_from_db()
        assert metric.value == expected, f"{kind.value} did not round-trip"
        # `==` is not enough for INT: it shares `value_num` with FLOAT, and
        # `3.0 == 3` would let an integer metric silently come back as a float.
        assert type(metric.value) is type(expected), f"{kind.value} round-tripped as {type(metric.value).__name__}"
