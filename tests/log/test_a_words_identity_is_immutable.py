"""A word's identity is what claims reference, and it is immutable (A4, RFC 0022).

The identity columns of `Term`, `StructureKind` and `MetricKind` may not be
rewritten; how a word presents may, and no act records it.
"""

from __future__ import annotations
import pytest
from django.db import connection, transaction
from django.db.utils import IntegrityError
from evidence import models as evidence_models
from evidence import writer
import kante
from asgiref.sync import sync_to_async
from kante.context import HttpContext
from core import models as core_models


REFUSED = IntegrityError


@pytest.mark.django_db(transaction=True)
def test_a_words_identity_cannot_be_rewritten(organization, roi_kind, length_category) -> None:
    """RFC 0022: the identity columns every claim references are immutable in the
    database, not by convention in one resolver."""
    term = writer.ensure_term(organization, "ENTITY", "AIS")

    with pytest.raises(REFUSED), transaction.atomic():
        evidence_models.Term.all_objects.filter(pk=term.pk).update(key="Axon")
    with pytest.raises(REFUSED), transaction.atomic():
        evidence_models.Term.all_objects.filter(pk=term.pk).update(kind="RELATION")
    with pytest.raises(REFUSED), transaction.atomic():
        evidence_models.StructureKind.all_objects.filter(pk=roi_kind.pk).update(identifier="@mikro/image")
    with pytest.raises(REFUSED), transaction.atomic():
        evidence_models.MetricKind.all_objects.filter(pk=length_category.pk).update(value_kind="INT")

    term.refresh_from_db()
    assert (term.kind, term.key) == ("ENTITY", "AIS")


@pytest.mark.django_db(transaction=True)
def test_a_words_presentation_is_not_evidence(organization, roi_kind, length_category) -> None:
    """How a word shows may change in place: no rule reads it, no claim references it."""
    term = writer.ensure_term(organization, "ENTITY", "AIS")

    evidence_models.Term.all_objects.filter(pk=term.pk).update(label="Axon initial segment", description="the AIS")
    evidence_models.StructureKind.all_objects.filter(pk=roi_kind.pk).update(label="Region of interest")
    evidence_models.MetricKind.all_objects.filter(pk=length_category.pk).update(label="Length")

    term.refresh_from_db()
    assert term.label == "Axon initial segment"


@pytest.mark.django_db(transaction=True)
def test_the_identity_guard_honours_the_redaction_hatch(organization) -> None:
    term = writer.ensure_term(organization, "ENTITY", "Misspelt")
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL kraph.allow_log_rewrite = 'on'")
        evidence_models.Term.all_objects.filter(pk=term.pk).update(key="Misspelled")
    term.refresh_from_db()
    assert term.key == "Misspelled"


CREATE_TERM = """
    mutation CreateTerm($input: CreateTermInput!) {
        createTerm(input: $input) { id kind key label description purl }
    }
"""


UPDATE_TERM = """
    mutation UpdateTerm($input: UpdateTermInput!) {
        updateTerm(input: $input) { id kind key label description }
    }
"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_declaring_a_word_that_exists_describes_it_rather_than_duplicating(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """`createTerm` is idempotent on `(kind, key)`, which is the term's identity.

    Filling in a PURL for a word some ingest minted bare is the expected use, so
    it must not fail — and it must not mint a second "AIS" either, because every
    claim already recorded points at the first.
    """
    category = await core_models.EntityCategory.objects.filter(graph=test_graph, key="AIS").afirst()
    assert category is not None
    existing_id = str(category.term_id)

    result = await api_schema.execute(
        CREATE_TERM,
        variable_values={"input": {"kind": "ENTITY", "key": "AIS", "description": "Axon initial segment", "purl": "http://purl.obolibrary.org/obo/UBERON_0006090"}},
        context_value=simple_api_context,
    )
    assert result.errors is None, f"GraphQL errors: {result.errors}"

    created = result.data["createTerm"]
    assert created["id"] == existing_id, "The same word is the same term — a second row would orphan every claim on the first"
    assert created["description"] == "Axon initial segment"
    assert created["purl"].endswith("UBERON_0006090")

    @sync_to_async
    def how_many() -> int:
        return evidence_models.Term.objects.for_organization(test_graph.organization).filter(kind="ENTITY", key="AIS").count()

    assert await how_many() == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_same_word_under_two_kinds_is_two_terms(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """ "AIS" as an entity and "AIS" as a relation are different words.

    `kind` is in the term's identity for exactly this reason, and it is why the
    projector can reach an event's edge labels from the term alone.
    """
    category = await core_models.EntityCategory.objects.filter(graph=test_graph, key="AIS").afirst()
    assert category is not None

    result = await api_schema.execute(
        CREATE_TERM,
        variable_values={"input": {"kind": "RELATION", "key": "AIS", "label": "a relation that happens to be spelled AIS"}},
        context_value=simple_api_context,
    )
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data["createTerm"]["id"] != str(category.term_id)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_updating_a_term_edits_its_presentation_only(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """`kind` and `key` are not editable, and the input has no field for them.

    Renaming a word would silently re-point every claim recorded under it. The
    append-only way to correct one is to declare the right word and re-classify,
    which leaves both claims on the record.
    """
    category = await core_models.EntityCategory.objects.filter(graph=test_graph, key="AIS").afirst()
    assert category is not None

    result = await api_schema.execute(
        UPDATE_TERM,
        variable_values={"input": {"id": str(category.term_id), "label": "AIS (curated)", "description": "The initial segment of an axon"}},
        context_value=simple_api_context,
    )
    assert result.errors is None, f"GraphQL errors: {result.errors}"

    updated = result.data["updateTerm"]
    assert updated["label"] == "AIS (curated)"
    assert updated["key"] == "AIS", "The word itself is untouched"
    assert updated["kind"] == "ENTITY"
