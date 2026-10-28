"""What an app may do here is what its token's scopes say: every root field asks for one of kraph's
own (the ``@auth`` directive publishes it, a generated client gathers it), and `kraph_all` stands
for all of them. What a member may do is what their kraph role says: `kraph_editor` records facts,
`kraph_curator` changes the vocabulary, `kraph_admin` both."""

import pytest
from kante.context import HttpContext, UniversalRequest
from strawberry.http.temporal_response import TemporalResponse

from arkitekt_service.graphql import scope_gaps
from tests.support import reads, writes


def _as(token: str) -> HttpContext:
    return HttpContext(request=UniversalRequest(_extensions={}), response=TemporalResponse(), headers={"Authorization": f"Bearer {token}"}, type="http")


def _reason(result) -> str | None:
    return result.errors[0].extensions.get("reason") if result.errors else None


def _a_term(key: str) -> dict[str, dict[str, str]]:
    return {"input": {"kind": "ENTITY", "key": key}}


def test_every_root_field_asks_for_a_scope_kraph_declares(api_schema):
    assert scope_gaps(api_schema) == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_app_granted_reads_reads_and_writes_nothing(api_schema):
    read = await api_schema.execute(reads.TERMS, context_value=_as("readertest"))
    assert read.errors is None, read.errors
    refused = await api_schema.execute(writes.CREATE_TERM, variable_values=_a_term("ScopedOut"), context_value=_as("readertest"))
    assert _reason(refused) == "INSUFFICIENT_SCOPE"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_all_scope_writes(api_schema):
    made = await api_schema.execute(writes.CREATE_TERM, variable_values=_a_term("AllScoped"), context_value=_as("test"))
    assert made.errors is None, made.errors


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_editor_records_facts_but_curates_no_vocabulary(api_schema):
    asserted = await api_schema.execute(writes.ASSERT_ENTITY_EXISTS, variable_values={"input": {"term": "EditedIn"}}, context_value=_as("editortest"))
    assert asserted.errors is None, asserted.errors
    refused = await api_schema.execute(writes.CREATE_TERM, variable_values=_a_term("NotCurated"), context_value=_as("editortest"))
    assert _reason(refused) == "INSUFFICIENT_ROLE"
