"""The organization's vocabulary, through the API.

A `Term` is a word — "AIS", "Mitosis" — and it is what the evidence log names. A
`Category` is one graph's rule for that word. Both are exposed, and the pair is
navigable in both directions, because "which views speak this word" and "what does
this view mean by it" are the two questions the split exists to keep apart.

`createTerm` exists where `structureKind` has no create, and the difference is the
point: `@mikro/roi` is owned by the service producing the datum, so there is
nothing to declare in advance, while "AIS" is an ontology entry a curator may want
to describe before any graph uses it.
"""

import uuid
import kante
import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext
from core import enums, models as core_models
from evidence import models as evidence_models
from tests.support import reads, writes


DELETE_TERM = """
    mutation DeleteTerm($input: DeleteTermInput!) {
        deleteTerm(input: $input)
    }
"""
CATEGORY_TERM = """
    query EntityCategory($id: ID!) {
        entityCategory(id: $id) { id key term { id kind key categories { id key } } }
    }
"""
def test_term_kinds_match_category_kinds() -> None:
    """The two enums must not drift.

    `TermKind` is a strawberry enum because `CategoryKindChoices` is a Django
    `TextChoices` and is not exposed to GraphQL — but they name the same set, and
    `Category.save` mints a term using `self.kind` verbatim. A member added to one
    and not the other would mint terms of a kind no client can ask for, or let a
    client ask for a kind nothing can mint.
    """
    assert {kind.value for kind in enums.TermKind} == {kind.value for kind in enums.CategoryKindChoices}
def test_instance_kinds_match_the_model() -> None:
    """`InstanceKind` is the GraphQL spelling of `Instance.Kind`, and nothing else.

    The model stores lowercase (`"entity"`) because that is what the column has always
    held; a GraphQL enum is uppercase. `Instance.kind` upcases on the way out, so a
    member in one and not the other would either be unaskable or unanswerable.
    """
    from evidence import models as evidence_models

    assert {kind.value for kind in enums.InstanceKind} == {choice.value.upper() for choice in evidence_models.Instance.Kind}
def test_link_kinds_match_the_model() -> None:
    """The same for `LinkKind`, where it matters more.

    `Link.source` and `Link.target` dispatch on this enum's members to decide which
    table each ref names, so a kind the enum does not know would resolve an endpoint
    against the wrong table — or, with the fallback, against none.
    """
    from evidence import models as evidence_models

    assert {kind.value for kind in enums.LinkKind} == {choice.value.upper() for choice in evidence_models.Link.Kind}
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_category_and_its_term_navigate_to_each_other(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """`Category.term` is the join, and `Term.categories` is its inverse.

    Both directions are exposed because both questions are real: a client showing
    a graph wants the word behind a category, and one curating vocabulary wants
    every view that speaks a word.
    """
    category = await core_models.EntityCategory.objects.filter(graph=test_graph, key="AIS").afirst()
    assert category is not None

    result = await api_schema.execute(CATEGORY_TERM, variable_values={"id": str(category.pk)}, context_value=simple_api_context)
    assert result.errors is None, f"GraphQL errors: {result.errors}"

    term = result.data["entityCategory"]["term"]
    assert term is not None, "Every category declares a word"
    assert (term["kind"], term["key"]) == ("ENTITY", "AIS")
    assert str(category.pk) in {row["id"] for row in term["categories"]}, "And the word knows the views that speak it"
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_deleting_a_word_in_use_is_refused(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The guard that moved off `Category` when the log stopped naming it.

    Deleting a *category* is free — it is one view's rule. The word every view's
    claims were recorded under has to outlive them, so `Node.term`, `Link.term`
    and `Category.term` are all `PROTECT`.
    """
    category = await core_models.EntityCategory.objects.filter(graph=test_graph, key="AIS").afirst()
    assert category is not None

    created = await api_schema.execute(
        writes.ASSERT_ENTITY_EXISTS,
        variable_values={"input": {"term": category.key, "supportingEvidence": []}},
        context_value=simple_api_context,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"

    result = await api_schema.execute(
        DELETE_TERM,
        variable_values={"input": {"id": str(category.term_id)}},
        context_value=simple_api_context,
    )

    assert result.errors is not None, "A word that has been claimed under cannot be retired"
    assert "evidence still refers to it" in str(result.errors[0])

    @sync_to_async
    def survives() -> int:
        return evidence_models.Term.objects.for_organization(test_graph.organization).filter(pk=category.term_id).count()

    assert await survives() == 1
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_unused_word_can_be_retired(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Nothing claimed it and no view declares it, so there is nothing to protect."""
    key = f"Ephemeral_{uuid.uuid4().hex[:6]}"

    created = await api_schema.execute(
        writes.CREATE_TERM,
        variable_values={"input": {"kind": "ENTITY", "key": key}},
        context_value=simple_api_context,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    term_id = created.data["createTerm"]["id"]

    result = await api_schema.execute(DELETE_TERM, variable_values={"input": {"id": term_id}}, context_value=simple_api_context)
    assert result.errors is None, f"GraphQL errors: {result.errors}"

    @sync_to_async
    def gone() -> int:
        return evidence_models.Term.all_objects.filter(pk=term_id).count()

    assert await gone() == 0
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_terms_can_be_filtered_by_kind_and_by_whether_a_graph_speaks_them(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """`declared` separates curated vocabulary from vocabulary in use.

    A term with no category is not an error — it is a word described before any
    graph was wired to it. Being able to ask for exactly those is the reason
    `createTerm` is worth having.
    """
    key = f"Undeclared_{uuid.uuid4().hex[:6]}"
    created = await api_schema.execute(writes.CREATE_TERM, variable_values={"input": {"kind": "ENTITY", "key": key}}, context_value=simple_api_context)
    assert created.errors is None, f"GraphQL errors: {created.errors}"

    entities = await api_schema.execute(reads.TERMS, variable_values={"filters": {"kinds": ["ENTITY"]}}, context_value=simple_api_context)
    assert entities.errors is None, f"GraphQL errors: {entities.errors}"
    assert {row["kind"] for row in entities.data["terms"]} == {"ENTITY"}
    assert key in {row["key"] for row in entities.data["terms"]}

    undeclared = await api_schema.execute(reads.TERMS, variable_values={"filters": {"declared": False}}, context_value=simple_api_context)
    assert undeclared.errors is None, f"GraphQL errors: {undeclared.errors}"
    keys = {row["key"] for row in undeclared.data["terms"]}
    assert key in keys, "A word no graph declares is still the organization's"
    assert "AIS" not in keys, "And one every graph declares is not in that list"
