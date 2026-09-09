"""Two graphs measuring the same datum share one term.

This file used to assert the opposite, and that inversion is the point of the
change rather than a side effect of it.

Before, structure and metric categories hung off a graph. A structure introduced
by graph A carried A's category, so a measurement recorded through graph B
resolved against A's schema — gated on A's permissions, and filing any
auto-created metric category under A where B could not see it. The old tests here
documented that as expected behaviour and pinned it in place.

Now the vocabulary belongs to the organization. `@mikro/roi` is an identifier
owned by the service that produces the datum, so there is exactly one term for it
and both graphs see the same one. There is no acting graph to resolve against and
no per-graph copy to disagree with.
"""

import pytest
from authentikate.models import Organization
from core.enums import ValueKind
from evidence import models as evidence_models
from evidence import writer
from typing import Set
from asgiref.sync import sync_to_async
from kante.context import HttpContext
from api.schema import schema
from core.models import Graph
import uuid
import kante
from core import models as core_models


@pytest.fixture
def shared_structure(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
    assertion: evidence_models.Assertion,
) -> evidence_models.Structure:
    """One structure, first referenced while building graph A."""
    return writer.ensure_structure(organization, roi_kind, "roi-shared", assertion)


def test_resolving_the_same_identifier_twice_returns_one_kind(organization: Organization) -> None:
    """The term is the organization's, so resolving it twice returns one row.

    No graph fixtures, because no graph is involved — which is the point. This
    previously produced two rows, identical in everything but which graph owned
    them, one per graph that happened to reference the identifier.
    """
    from_a = writer.ensure_structure_kind(organization, "@mikro/roi")
    from_b = writer.ensure_structure_kind(organization, "@mikro/roi")

    assert from_a.pk == from_b.pk
    assert evidence_models.StructureKind.objects.for_organization(organization).filter(identifier="@mikro/roi").count() == 1


def test_a_structure_reached_from_either_graph_is_the_same_row(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
    shared_structure: evidence_models.Structure,
    assertion: evidence_models.Assertion,
) -> None:
    """And it carries the one term, so "whose category is this" has no meaning."""
    again = writer.ensure_structure(organization, roi_kind, "roi-shared", assertion)

    assert again.pk == shared_structure.pk
    assert again.kind_id == roi_kind.pk


def test_a_measurement_recorded_by_either_graph_uses_one_term(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
    shared_structure: evidence_models.Structure,
    assertion: evidence_models.Assertion,
) -> None:
    """The defect this file used to document, now impossible.

    Whichever graph records the measurement, `ensure_metric_kind` resolves the
    same organization-level term — so the second graph can see what the first
    recorded, which is the whole reason evidence is shared.
    """
    from_a = writer.ensure_metric_kind(organization, roi_kind, "vector_length", ValueKind.FLOAT)
    from_b = writer.ensure_metric_kind(organization, roi_kind, "vector_length", ValueKind.FLOAT)

    assert from_a.pk == from_b.pk

    metric = writer.record_metric(
        organization,
        shared_structure,
        from_b,
        key="vector_length",
        value=45.2,
        assertion=assertion,
    )
    assert metric.kind_id == from_a.pk


def test_a_contradicting_value_kind_makes_a_second_term(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
) -> None:
    """A disagreement about type is two quantities, not one rejected write.

    This assertion is inverted from what it was, deliberately. It used to raise:
    one term per `(organization, structure_kind, key)` meant the second
    declaration contradicted the first, and naming both kinds in the error was
    the best that could be done. But that refuses a measurement because someone
    else reached the key first — and a float `confidence` and a category-label
    `confidence` are not the same quantity disagreeing, they are two quantities
    sharing a name.

    The raise that remains is a different one, on the *undeclared* path: see
    `test_metric_kind_identity`.
    """
    as_float = writer.ensure_metric_kind(organization, roi_kind, "vector_length", ValueKind.FLOAT)
    as_string = writer.ensure_metric_kind(organization, roi_kind, "vector_length", ValueKind.STRING)

    assert as_float.pk != as_string.pk, "Each declaration gets its own term"
    assert evidence_models.MetricKind.objects.for_organization(organization).filter(structure_kind=roi_kind, key="vector_length").count() == 2

    # And re-declaring either is still idempotent — the identity is the whole
    # four-tuple, so this is a lookup and not a third term.
    assert writer.ensure_metric_kind(organization, roi_kind, "vector_length", ValueKind.FLOAT).pk == as_float.pk


def test_the_same_key_on_different_structures_is_a_different_term(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
) -> None:
    """`vector_length` on an ROI and on a Mask are separate quantities.

    Identity is `(organization, structure_kind, key, value_kind)`. The old table
    enforced `(graph, key)` while the lookup used
    `(graph, key, structure_category)`, so two metrics named `area` on different
    structures collided at the database level.
    """
    mask_kind = writer.ensure_structure_kind(organization, "@mikro/mask")

    on_roi = writer.ensure_metric_kind(organization, roi_kind, "area", ValueKind.FLOAT)
    on_mask = writer.ensure_metric_kind(organization, mask_kind, "area", ValueKind.FLOAT)

    assert on_roi.pk != on_mask.pk


def test_kinds_never_cross_organizations(
    organization: Organization,
    other_organization: Organization,
) -> None:
    """Sharing is within a tenant. It has to stop at the tenant boundary."""
    writer.ensure_structure_kind(organization, "@mikro/roi")
    writer.ensure_structure_kind(other_organization, "@mikro/roi")

    assert evidence_models.StructureKind.objects.for_organization(organization).count() == 1
    assert evidence_models.StructureKind.objects.for_organization(other_organization).count() == 1
    assert evidence_models.StructureKind.all_objects.filter(identifier="@mikro/roi").count() == 2


def test_a_declaration_is_never_refused(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
) -> None:
    """Both declarations land. Neither caller is told to go away."""
    as_float = writer.ensure_metric_kind(organization, roi_kind, "confidence", ValueKind.FLOAT)
    as_category = writer.ensure_metric_kind(organization, roi_kind, "confidence", ValueKind.CATEGORY)

    assert as_float.pk != as_category.pk
    assert as_float.value_kind == ValueKind.FLOAT.value
    assert as_category.value_kind == ValueKind.CATEGORY.value


def test_a_declaration_is_idempotent(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
) -> None:
    """Declaring the same thing twice is a lookup, not a second term."""
    first = writer.ensure_metric_kind(organization, roi_kind, "confidence", ValueKind.FLOAT)
    again = writer.ensure_metric_kind(organization, roi_kind, "confidence", ValueKind.FLOAT)

    assert first.pk == again.pk
    assert evidence_models.MetricKind.objects.for_organization(organization).filter(key="confidence").count() == 1


def test_the_property_type_spelling_is_accepted(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
) -> None:
    """The GraphQL surface says "float"; storage says FLOAT. One term either way.

    Without normalising at this boundary the two spellings would be two terms,
    and the lowercase one would carry a `value_kind` no column mapping
    recognises — `writer.value_columns` rejects it outright.
    """
    canonical = writer.ensure_metric_kind(organization, roi_kind, "confidence", ValueKind.FLOAT)
    lowercase = writer.ensure_metric_kind(organization, roi_kind, "confidence", "float")

    assert canonical.pk == lowercase.pk


def test_a_missing_value_kind_is_refused(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
) -> None:
    """No kind, no term. There is nothing left that guesses one.

    Replaces three tests that covered the guessing: adopt-the-existing-term,
    infer-and-mint, and the raise when a key had several terms. The last of those
    was unactionable — it told callers to declare a kind through inputs that had
    no field for one — and the first two only existed to keep inference from
    forking a key. The error names the key so a failure inside a batch of
    measurements can be located.
    """
    with pytest.raises(ValueError) as excinfo:
        writer.ensure_metric_kind(organization, roi_kind, "confidence", None)

    message = str(excinfo.value)
    assert "confidence" in message, "The error must name the key it could not record"
    assert "@mikro/roi" in message


def test_a_key_with_several_terms_is_writable(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
) -> None:
    """The dead end, at the writer level.

    Two terms for one key used to make an undeclared write impossible. Naming the
    kind resolves it exactly, and neither existing term is disturbed.
    """
    as_float = writer.ensure_metric_kind(organization, roi_kind, "confidence", ValueKind.FLOAT)
    as_string = writer.ensure_metric_kind(organization, roi_kind, "confidence", ValueKind.STRING)

    assert writer.ensure_metric_kind(organization, roi_kind, "confidence", ValueKind.STRING).pk == as_string.pk
    assert writer.ensure_metric_kind(organization, roi_kind, "confidence", ValueKind.FLOAT).pk == as_float.pk
    assert evidence_models.MetricKind.objects.for_organization(organization).filter(key="confidence").count() == 2


def test_nothing_infers_a_value_kind(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
) -> None:
    """`45` and `45.2` under one declared key stay one term.

    Not because an existing term wins over inference — because there is no
    inference. `writer` exports no way to guess a kind from a value, and this
    asserts that rather than trusting the deletion stuck: a re-introduced
    `infer_value_kind` would be a guessing primitive with no caller, and the next
    write path to want one would reach for it.
    """
    assert not hasattr(writer, "infer_value_kind")

    first = writer.ensure_metric_kind(organization, roi_kind, "vector_length", ValueKind.FLOAT)
    second = writer.ensure_metric_kind(organization, roi_kind, "vector_length", ValueKind.FLOAT)

    assert first.pk == second.pk
    assert evidence_models.MetricKind.objects.for_organization(organization).filter(key="vector_length").count() == 1


def test_an_unknown_value_kind_is_rejected(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
) -> None:
    """A misspelling must not become a term nothing can read back.

    `Metric.value` looks its column up by `value_kind`, so a term carrying a kind
    outside the vocabulary produces rows whose value cannot be retrieved at all.
    """
    with pytest.raises(ValueError, match="Unknown value kind"):
        writer.ensure_metric_kind(organization, roi_kind, "confidence", "flaot")


def test_terms_never_cross_organizations(
    organization: Organization,
    other_organization: Organization,
    roi_kind: evidence_models.StructureKind,
) -> None:
    """Vocabulary is per-tenant, and the four-tuple does not change that."""
    other_roi = writer.ensure_structure_kind(other_organization, "@mikro/roi")

    writer.ensure_metric_kind(organization, roi_kind, "confidence", ValueKind.FLOAT)
    writer.ensure_metric_kind(other_organization, other_roi, "confidence", ValueKind.FLOAT)

    assert evidence_models.MetricKind.objects.for_organization(organization).count() == 1
    assert evidence_models.MetricKind.objects.for_organization(other_organization).count() == 1


def test_the_term_names_its_value_kind(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
) -> None:
    """Two terms for one key must not print identically.

    The admin list and `ensure_metric_kind`'s own ambiguity error are exactly
    where telling them apart matters.
    """
    as_float = writer.ensure_metric_kind(organization, roi_kind, "confidence", ValueKind.FLOAT)
    as_string = writer.ensure_metric_kind(organization, roi_kind, "confidence", ValueKind.STRING)

    assert str(as_float) != str(as_string)
    assert "FLOAT" in str(as_float)


STRUCTURE_KINDS = """
    query StructureKinds {
        structureKinds { id identifier label }
    }
"""
METRIC_KINDS = """
    query MetricKinds {
        metricKinds { id key valueKind structureKind { identifier } }
    }
"""


@sync_to_async
def _seed(organization: Organization) -> None:
    roi = writer.ensure_structure_kind(organization, "@mikro/roi")
    roi.label = "TEST_ROI"
    roi.save()

    nucleus = writer.ensure_structure_kind(organization, "@mikro/nucleus")
    nucleus.label = "TEST_NUCLEUS"
    nucleus.save()

    writer.ensure_metric_kind(organization, roi, "vector_length", ValueKind.FLOAT)


@sync_to_async
def _seed_other_organization() -> Organization:
    other, _ = Organization.objects.get_or_create(slug="a-different-tenant")
    writer.ensure_structure_kind(other, "@secret/thing")
    return other


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_structure_kinds_lists_the_organizations_vocabulary(test_graph: Graph, authenticated_context: HttpContext) -> None:
    """Both kinds, with no graph named anywhere in the query."""
    await _seed(test_graph.organization)

    result = await schema.execute(STRUCTURE_KINDS, context_value=authenticated_context)

    assert result.errors is None, result.errors
    identifiers: Set[str] = {item["identifier"] for item in result.data["structureKinds"]}
    assert {"@mikro/roi", "@mikro/nucleus"} <= identifiers


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_metric_kinds_name_the_structure_they_describe(test_graph: Graph, authenticated_context: HttpContext) -> None:
    """A measurement term is meaningless without the thing it measures."""
    await _seed(test_graph.organization)

    result = await schema.execute(METRIC_KINDS, context_value=authenticated_context)

    assert result.errors is None, result.errors
    kinds = {item["key"]: item for item in result.data["metricKinds"]}
    assert "vector_length" in kinds
    assert kinds["vector_length"]["structureKind"]["identifier"] == "@mikro/roi"
    assert kinds["vector_length"]["valueKind"] == "FLOAT"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_another_organizations_kinds_are_not_returned(test_graph: Graph, authenticated_context: HttpContext) -> None:
    """The check that matters.

    Removing `CategoryFilter.graph` removed the only thing that had ever scoped
    these fields, so a missing resolver would leak every tenant's vocabulary to
    every caller — and nothing would have looked wrong.
    """
    await _seed(test_graph.organization)
    await _seed_other_organization()

    result = await schema.execute(STRUCTURE_KINDS, context_value=authenticated_context)

    assert result.errors is None, result.errors
    identifiers: Set[str] = {item["identifier"] for item in result.data["structureKinds"]}
    assert "@secret/thing" not in identifiers, "Another organization's vocabulary must never appear"
    assert await evidence_models.StructureKind.all_objects.filter(identifier="@secret/thing").acount() == 1


INGEST_INPUTS = ["AssertMetricValueInput", "AssertStructureExistsInput"]


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
        mutation RecordMetric($input: AssertMetricValueInput!) {
            assertMetricValue(input: $input) { metric { id value unit } }
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
    assert recorded.data["assertMetricValue"]["metric"]["value"] == 45.2
    assert recorded.data["assertMetricValue"]["metric"]["unit"] == "um"

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
        mutation RecordMetric($input: AssertMetricValueInput!) {
            assertMetricValue(input: $input) { metric { id } }
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
