"""Comments are claims: lok's komment model, restated as evidence.

What lok kept as mutable state has to show up here as appended rows — the author
and time are the assertion, resolution is a `Standing`, and the row itself can
never be edited. These tests pin each translation, plus the two flows lok left
as `NotImplementedError` (reply, resolve), which arrive here as what they always
were underneath.
"""

import pytest
import kante
from asgiref.sync import sync_to_async
from kante.context import HttpContext

from core import models as core_models

COMMENT = """
    mutation CommentOnStructure($input: CommentOnStructureInput!) {
        commentOnStructure(input: $input) {
            assertion { id subject }
            comment {
                id
                text
                mentions
                resolved
                parent { id }
                structure { id identifier object }
                descendants {
                    kind
                    ... on ParagraphDescendant { size }
                    children {
                        kind
                        ... on LeafDescendant { text bold }
                        ... on MentionDescendant { subject }
                    }
                }
            }
        }
    }
"""

READ_FOR = """
    query CommentsFor($identifier: String!, $object: ID!) {
        commentsFor(identifier: $identifier, object: $object) {
            id
            text
            resolved
            replies { id text }
        }
    }
"""

RETRACT = """
    mutation Retract($input: RetractCommentInput!) {
        retractComment(input: $input) {
            assertion { id }
            comment { id resolved standings { stands assertion { subject } } }
        }
    }
"""

ATTEST = """
    mutation Attest($input: AttestCommentInput!) {
        attestComment(input: $input) {
            comment { id resolved standings { stands } }
        }
    }
"""


def _body(text: str, mention: str | None = None) -> list[dict]:
    children: list[dict] = [{"kind": "LEAF", "text": text, "bold": True}]
    if mention is not None:
        children.append({"kind": "MENTION", "user": mention})
    return [{"kind": "PARAGRAPH", "size": "normal", "children": children}]


async def _comment(api_schema: kante.Schema, ctx: HttpContext, object_id: str, text: str, **extra) -> dict:
    result = await api_schema.execute(
        COMMENT,
        variable_values={"input": {"identifier": "@mikro/roi", "object": object_id, "descendants": _body(text, extra.pop("mention", None)), **extra}},
        context_value=ctx,
    )
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    return result.data["commentOnStructure"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_comment_mints_its_structure_and_folds_its_body(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
) -> None:
    """One act: the remark and, if the datum is new, the structure that carries it.

    `text` and `mentions` are folded from the tree at write time — the row is
    append-only, so there is no after-the-fact to derive them in, which is where
    lok did it.
    """
    payload = await _comment(api_schema, simple_api_context, "roi_c1", "looks off", mention="reviewer-7")
    comment = payload["comment"]

    assert comment["structure"]["identifier"] == "@mikro/roi", "Commenting on an unseen datum minted its structure"
    assert comment["structure"]["object"] == "roi_c1"
    assert comment["text"] == "looks off@reviewer-7", "The plain text is the folded leaves"
    assert comment["mentions"] == ["reviewer-7"], "Mentions are extracted from the tree"
    assert comment["resolved"] is False, "Nobody has taken a position, so it stands"
    assert comment["parent"] is None

    tree = comment["descendants"]
    assert tree[0]["kind"] == "PARAGRAPH" and tree[0]["size"] == "normal"
    assert tree[0]["children"][0] == {"kind": "LEAF", "text": "looks off", "bold": True}
    assert tree[0]["children"][1] == {"kind": "MENTION", "subject": "reviewer-7"}

    listed = await api_schema.execute(READ_FOR, variable_values={"identifier": "@mikro/roi", "object": "roi_c1"}, context_value=simple_api_context)
    assert listed.errors is None, f"GraphQL errors: {listed.errors}"
    assert [row["id"] for row in listed.data["commentsFor"]] == [comment["id"]], "The thread reads back by the datum's address"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_reply_stays_on_its_parents_thread(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
) -> None:
    """Threading is `parent`/`replies`, and the thread is the structure.

    A reply naming a parent from a different datum's thread is refused: it would
    fork one conversation across two data.
    """
    first = await _comment(api_schema, simple_api_context, "roi_thread", "is this segmented right?")
    reply = await _comment(api_schema, simple_api_context, "roi_thread", "yes, checked it", parent=first["comment"]["id"])

    assert reply["comment"]["parent"]["id"] == first["comment"]["id"]

    listed = await api_schema.execute(READ_FOR, variable_values={"identifier": "@mikro/roi", "object": "roi_thread"}, context_value=simple_api_context)
    assert listed.errors is None
    by_id = {row["id"]: row for row in listed.data["commentsFor"]}
    assert [child["text"] for child in by_id[first["comment"]["id"]]["replies"]] == ["yes, checked it"]

    other = await api_schema.execute(
        COMMENT,
        variable_values={"input": {"identifier": "@mikro/roi", "object": "roi_elsewhere", "descendants": _body("crossing threads"), "parent": first["comment"]["id"]}},
        context_value=simple_api_context,
    )
    assert other.errors, "A reply must stay on its parent's thread"
    assert "thread" in str(other.errors[0]), f"Refused for the wrong reason: {other.errors[0]}"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_resolving_is_a_standing_and_reopening_is_more_evidence(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
) -> None:
    """lok's `resolved`/`resolved_by` columns, as the fold they should have been.

    Retract says the remark no longer stands — whether the author withdrew it or
    a reviewer resolved it, the standing's assertion records whose position it
    was. Attest reopens. Both stay on the record, newest first.
    """
    created = await _comment(api_schema, simple_api_context, "roi_resolve", "artifact?")
    comment_id = created["comment"]["id"]

    resolved = await api_schema.execute(RETRACT, variable_values={"input": {"id": comment_id}}, context_value=simple_api_context)
    assert resolved.errors is None, f"GraphQL errors: {resolved.errors}"
    after = resolved.data["retractComment"]["comment"]
    assert after["resolved"] is True
    assert [row["stands"] for row in after["standings"]] == [False]
    assert after["standings"][0]["assertion"]["subject"], "Who resolved it is the standing's own assertion — lok's resolved_by, as provenance"

    reopened = await api_schema.execute(ATTEST, variable_values={"input": {"id": comment_id}}, context_value=simple_api_context)
    assert reopened.errors is None, f"GraphQL errors: {reopened.errors}"
    again = reopened.data["attestComment"]["comment"]
    assert again["resolved"] is False
    assert [row["stands"] for row in again["standings"]] == [True, False], "Newest first, and the resolution stays on the record"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_comment_log_is_append_only(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
) -> None:
    """Editing a comment is refused by the database, not by a docstring.

    The same trigger that guards the other six log tables — lok edits rows in
    place, and the whole point of carrying comments here is that nothing does.
    """
    created = await _comment(api_schema, simple_api_context, "roi_immutable", "original wording")
    comment_id = created["comment"]["id"]

    @sync_to_async
    def try_to_edit() -> str:
        from django.db import connection

        try:
            with connection.cursor() as cursor:
                cursor.execute("UPDATE evidence_comment SET text = 'revised wording' WHERE id = %s", [comment_id])
            return ""
        except Exception as error:  # noqa: BLE001 — the message is the assertion
            return str(error)

    refusal = await try_to_edit()
    assert "append-only" in refusal, f"An UPDATE on a comment must be refused by the trigger, got: {refusal!r}"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_my_mentions_finds_the_caller_by_subject(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
) -> None:
    """A mention names a subject — `Assertion.subject`'s vocabulary — and the query folds on it."""
    me = str(simple_api_context.request.user.id)
    await _comment(api_schema, simple_api_context, "roi_mention", "ping", mention=me)
    await _comment(api_schema, simple_api_context, "roi_mention", "no ping here")

    result = await api_schema.execute("query { myMentions { text mentions } }", context_value=simple_api_context)
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert [row["mentions"] for row in result.data["myMentions"]] == [[me]], "Only the remark that mentions the caller"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_unknown_descendant_kind_is_refused_at_the_door(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
) -> None:
    """A stored tree is forever, so the shape is enforced where it can still be fixed."""
    result = await api_schema.execute(
        COMMENT,
        variable_values={"input": {"identifier": "@mikro/roi", "object": "roi_bad", "descendants": [{"kind": "TABLE"}]}},
        context_value=simple_api_context,
    )
    assert result.errors, "An unknown kind must be refused, not stored"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_resolution_cache_replays_from_the_log(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """`CurrentStanding` covers comments, and refolding reproduces the answer.

    The honesty test every projection gets: destroy the cache, replay it from
    the log, and the fold must not change.
    """
    created = await _comment(api_schema, simple_api_context, "roi_refold", "to be resolved")
    comment_id = created["comment"]["id"]
    await api_schema.execute(RETRACT, variable_values={"input": {"id": comment_id}}, context_value=simple_api_context)

    @sync_to_async
    def destroy_and_refold() -> bool:
        from evidence import claims as claims_module
        from evidence import models as evidence_models

        organization = test_graph.organization
        evidence_models.CurrentStanding.objects.for_organization(organization).filter(target_type="comment").delete()
        claims_module.refold_current(organization)
        return claims_module.current(organization, "comment", comment_id)

    assert await destroy_and_refold() is False, "The replayed fold must still say the remark is resolved"
