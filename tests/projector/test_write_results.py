"""What a write hands back: the claim it recorded, and everywhere that claim stands.

The point of `docs/rfcs/0003-undrawn-nodes.md` option F, and the two cases the old
return shape could not express at all:

- **A claim no view draws.** The write returns a node with `drawings: []`. It used
  to return a node carrying a category borrowed from *some* graph — one that had
  not drawn it, picked by an unordered `.first()` — so two identical writes could
  report different categories and nothing about the claim explained the
  difference.
- **A claim several views draw.** The write returns one drawing per view. It used
  to return the *first* graph that answered and silently discard the rest; the
  `order_by("pk")` that made that deterministic was damage control on a lossy
  shape.

Both go through the real GraphQL surface, because the shape being tested is the
API's. And both need the real AGE stack: `MockCypherEngine` returns `[]` for the
`MATCH (n) WHERE n.id = $nid RETURN n` that reads a drawing back, so a drawings
assertion against the mock would pass by finding nothing.
"""

import uuid

import kante
import pytest
from kante.context import HttpContext

from core import models as core_models

ASSERT_ENTITY = """
    mutation AssertEntityExists($input: AssertEntityExistsInput!) {
        assertEntityExists(input: $input) {
            assertion { id subject seq }
            instance { id kind term { key } }
            drawings {
                graph { id name }
                category { id key }
                node { id label }
            }
        }
    }
"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_claim_no_view_declares_is_recorded_and_undrawn(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The write succeeds, the assertion is real, and nothing draws it.

    This is the case that used to raise — `create_entity` ended with
    `ValueError("... no category in {age_name} admits it")` *after* the claim was
    durably committed — and then, once it stopped raising, the case that returned
    a stranger's category.
    """
    word = f"Unlikely{uuid.uuid4().hex[:8]}"

    result = await api_schema.execute(
        ASSERT_ENTITY,
        variable_values={"input": {"term": word, "supportingEvidence": []}},
        context_value=simple_api_context,
    )

    assert result.errors is None, f"A claim under an undeclared word must succeed: {result.errors}"
    payload = result.data["assertEntityExists"]

    assert payload["instance"]["id"], "The claim has a durable identity whether or not any view draws it"
    assert payload["instance"]["term"]["key"] == word, "And it names the word claimed, not a category's name"
    assert payload["drawings"] == [], "No view declares the word, so no view draws it"

    assert payload["assertion"]["id"], "The act itself is addressable"
    assert payload["assertion"]["seq"] is not None, "including its position in the log"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_claim_two_views_declare_reports_both_drawings(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    second_graph: core_models.Graph,
) -> None:
    """Two views declaring one word both draw the claim, and the result says so.

    The old return could only name one of them. Note the assertion is on the *set*
    of graphs rather than on ordering: which view is reported first is not a fact
    about the claim, and a test that pinned it would be pinning `order_by("pk")`.
    """
    from asgiref.sync import sync_to_async

    @sync_to_async
    def declared_word() -> str:
        """A word both graphs declare a category for."""
        for graph in (test_graph, second_graph):
            assert core_models.EntityCategory.objects.filter(graph=graph, key="AIS").exists(), f"{graph.name} must declare AIS"
        return "AIS"

    word = await declared_word()

    result = await api_schema.execute(
        ASSERT_ENTITY,
        variable_values={"input": {"term": word, "supportingEvidence": []}},
        context_value=simple_api_context,
    )

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    payload = result.data["assertEntityExists"]

    drawn_in = {drawing["graph"]["id"] for drawing in payload["drawings"]}
    assert drawn_in == {str(test_graph.id), str(second_graph.id)}, f"Both views declaring the word must draw it, got {payload['drawings']}"

    for drawing in payload["drawings"]:
        assert drawing["category"]["key"] == word, "Each drawing reports the category *that view* drew it under"
        assert drawing["node"]["id"] == payload["instance"]["id"], "and the same node, seen from that view"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_top_level_node_carries_no_borrowed_category(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Even when a view *does* draw it, the payload names no category.

    The claim is one thing and the several ways views draw it are another. A
    category belongs to a view, so the only honest place for one is inside a
    drawing — which is where every real category now is.

    It used to be a **null** `categoryId` on a graph-shaped payload. An `Instance` has
    no such field to be null: the claim names a word (`term`), and what a view makes
    of that word is the drawing's business.
    """
    result = await api_schema.execute(
        """
        mutation AssertEntityExists($input: AssertEntityExistsInput!) {
            assertEntityExists(input: $input) {
                instance { id term { key } }
                drawings { category { id } }
            }
        }
        """,
        variable_values={"input": {"term": "AIS", "supportingEvidence": []}},
        context_value=simple_api_context,
    )

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    payload = result.data["assertEntityExists"]

    assert payload["instance"]["term"]["key"] == "AIS", "The claim names a word, not a view's rule for one"
    assert payload["drawings"], "while the view that drew it reports its category"
    assert payload["drawings"][0]["category"]["id"], "which is a real category"
