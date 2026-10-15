"""The organization's vocabulary is navigable (A4, C4).

A `Term` is a word and is what the log names; a `Category` is one view's rule
for it. Both are exposed, and the pair is navigable in both directions: which
views speak this word, and what this view means by it.
"""

import uuid
import kante
import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext
from core import enums, models as core_models
from evidence import models as evidence_models
from tests.support import reads, writes


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
async def test_a_hidden_word_is_put_away_not_gone(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Hiding is the only way to put a word away, and it is reversible.

    A hidden word drops out of `hidden: false` (what pickers ask for), is still
    listed under `hidden: true` and still found by id, and comes back with
    `hidden: false`. Omitting `hidden` on an update leaves it as it was.

    History: `deleteTerm` retired a word nothing was claimed under. It is gone —
    a word is what the log names, and a client may name an unused one tomorrow.
    """
    key = f"Hideable_{uuid.uuid4().hex[:6]}"
    created = await api_schema.execute(writes.CREATE_TERM, variable_values={"input": {"kind": "ENTITY", "key": key}}, context_value=simple_api_context)
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    term_id = created.data["createTerm"]["id"]

    hidden = await api_schema.execute(writes.UPDATE_TERM, variable_values={"input": {"id": term_id, "hidden": True}}, context_value=simple_api_context)
    assert hidden.errors is None, f"GraphQL errors: {hidden.errors}"
    assert hidden.data["updateTerm"]["hidden"] is True

    offered = await api_schema.execute(reads.TERMS, variable_values={"filters": {"hidden": False}}, context_value=simple_api_context)
    assert offered.errors is None, f"GraphQL errors: {offered.errors}"
    assert key not in {row["key"] for row in offered.data["terms"]}, "A hidden word is no longer offered"

    put_away = await api_schema.execute(reads.TERMS, variable_values={"filters": {"hidden": True}}, context_value=simple_api_context)
    assert put_away.errors is None, f"GraphQL errors: {put_away.errors}"
    assert key in {row["key"] for row in put_away.data["terms"]}, "But it is still the organization's word"

    relabelled = await api_schema.execute(writes.UPDATE_TERM, variable_values={"input": {"id": term_id, "label": "Still hidden"}}, context_value=simple_api_context)
    assert relabelled.errors is None, f"GraphQL errors: {relabelled.errors}"
    assert relabelled.data["updateTerm"]["hidden"] is True, "An update that does not mention `hidden` leaves it alone"

    shown = await api_schema.execute(writes.UPDATE_TERM, variable_values={"input": {"id": term_id, "hidden": False}}, context_value=simple_api_context)
    assert shown.errors is None, f"GraphQL errors: {shown.errors}"
    assert shown.data["updateTerm"]["hidden"] is False, "And it can be shown again"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_declaring_a_hidden_word_shows_it_but_claiming_under_it_does_not(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """`createTerm` is wanting the word; a claim naming it is not.

    A claim under a hidden word stands — hiding says nothing about the world —
    and leaves the word hidden. Declaring the word explicitly brings it back.
    """
    category = await core_models.EntityCategory.objects.filter(graph=test_graph, key="AIS").afirst()
    assert category is not None

    hidden = await api_schema.execute(writes.UPDATE_TERM, variable_values={"input": {"id": str(category.term_id), "hidden": True}}, context_value=simple_api_context)
    assert hidden.errors is None, f"GraphQL errors: {hidden.errors}"

    claimed = await api_schema.execute(
        writes.ASSERT_ENTITY_EXISTS,
        variable_values={"input": {"term": category.key, "supportingEvidence": []}},
        context_value=simple_api_context,
    )
    assert claimed.errors is None, f"A claim under a hidden word stands: {claimed.errors}"

    @sync_to_async
    def is_hidden() -> bool:
        return evidence_models.Term.all_objects.get(pk=category.term_id).hidden

    assert await is_hidden(), "Claiming under the word does not show it"

    declared = await api_schema.execute(writes.CREATE_TERM, variable_values={"input": {"kind": "ENTITY", "key": category.key}}, context_value=simple_api_context)
    assert declared.errors is None, f"GraphQL errors: {declared.errors}"
    assert declared.data["createTerm"]["id"] == str(category.term_id), "Declaring finds the same word"
    assert not await is_hidden(), "Declaring it shows it again"


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


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_word_is_findable_by_id_and_by_text(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """`ids` and `search` narrow the vocabulary; `search` reads key, label and description.

    History: the three vocabulary filters declared `ids` and `search` as bare
    fields with no resolver, so strawberry_django applied them as `Q(ids=…)` /
    `Q(search=…)` against models with no such column, and every use raised
    `FieldError`. No test passed either argument.
    """
    stamp = uuid.uuid4().hex[:6]
    wanted = await api_schema.execute(writes.CREATE_TERM, variable_values={"input": {"kind": "ENTITY", "key": f"Wanted_{stamp}", "label": f"Axon initial segment {stamp}", "description": "where spikes begin"}}, context_value=simple_api_context)
    assert wanted.errors is None, f"GraphQL errors: {wanted.errors}"
    other = await api_schema.execute(writes.CREATE_TERM, variable_values={"input": {"kind": "ENTITY", "key": f"Other_{stamp}", "label": "Dendrite", "description": "receives"}}, context_value=simple_api_context)
    assert other.errors is None, f"GraphQL errors: {other.errors}"
    wanted_id = wanted.data["createTerm"]["id"]

    by_id = await api_schema.execute(reads.TERMS, variable_values={"filters": {"ids": [wanted_id]}}, context_value=simple_api_context)
    assert by_id.errors is None, f"GraphQL errors: {by_id.errors}"
    assert [row["id"] for row in by_id.data["terms"]] == [wanted_id]

    by_label = await api_schema.execute(reads.TERMS, variable_values={"filters": {"search": f"initial segment {stamp}"}}, context_value=simple_api_context)
    assert by_label.errors is None, f"GraphQL errors: {by_label.errors}"
    assert [row["id"] for row in by_label.data["terms"]] == [wanted_id]

    by_description = await api_schema.execute(reads.TERMS, variable_values={"filters": {"search": "spikes begin"}}, context_value=simple_api_context)
    assert by_description.errors is None, f"GraphQL errors: {by_description.errors}"
    assert wanted_id in {row["id"] for row in by_description.data["terms"]}
    assert other.data["createTerm"]["id"] not in {row["id"] for row in by_description.data["terms"]}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_kind_is_findable_by_id_and_by_text(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The same two filters on `structureKinds` and `metricKinds` — the kinds are vocabulary too."""
    from core.enums import ValueKind
    from evidence import writer

    @sync_to_async
    def seed() -> tuple[str, str]:
        organization = test_graph.organization
        roi = writer.ensure_structure_kind(organization, "@mikro/roi")
        roi.label = "Region of interest"
        roi.save()
        writer.ensure_structure_kind(organization, "@mikro/image")
        length = writer.ensure_metric_kind(organization, roi, "vector_length", ValueKind.FLOAT)
        return str(roi.pk), str(length.pk)

    roi_id, length_id = await seed()

    kinds = await api_schema.execute(reads.STRUCTURE_KINDS, variable_values={"filters": {"search": "region of"}}, context_value=simple_api_context)
    assert kinds.errors is None, f"GraphQL errors: {kinds.errors}"
    assert [row["id"] for row in kinds.data["structureKinds"]] == [roi_id]

    kinds = await api_schema.execute(reads.STRUCTURE_KINDS, variable_values={"filters": {"ids": [roi_id]}}, context_value=simple_api_context)
    assert kinds.errors is None, f"GraphQL errors: {kinds.errors}"
    assert [row["identifier"] for row in kinds.data["structureKinds"]] == ["@mikro/roi"]

    metrics = await api_schema.execute(reads.METRIC_KINDS, variable_values={"filters": {"search": "vector_len"}}, context_value=simple_api_context)
    assert metrics.errors is None, f"GraphQL errors: {metrics.errors}"
    assert [row["id"] for row in metrics.data["metricKinds"]] == [length_id]

    metrics = await api_schema.execute(reads.METRIC_KINDS, variable_values={"filters": {"ids": [length_id]}}, context_value=simple_api_context)
    assert metrics.errors is None, f"GraphQL errors: {metrics.errors}"
    assert [row["key"] for row in metrics.data["metricKinds"]] == ["vector_length"]
