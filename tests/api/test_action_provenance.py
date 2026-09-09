"""An assertion records which run produced it, when there was one.

`Assertion` has carried `action_id`, `action_name` and `action_args` since it was
written, and until now nothing populated them — so the `action_names` branch of
all three selector filters was dead in production while three test conftests set
`action_name` and exercised it. Green tests over an unreachable path.

The information was already on the request. `AuthentikateExtension` verifies the
Rekuest provenance token and attaches it to the kante context; `koherent` only
mirrors the same token into a contextvar for its own history signals, and
`ProvenanceField` — which audits mutable Django rows in other mounts — has nothing
to do with it. Evidence does not use `ProvenanceField`, because for instance data
the `Assertion` *is* the provenance and two systems over the same rows would
eventually disagree.
"""

from __future__ import annotations

import datetime

import kante
import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext

from core import models as core_models
from evidence import models as evidence_models
from tests.support import writes


class _Actor:
    """The executing agent half of a token — `act` in the claim set."""

    def __init__(self) -> None:
        self.sub = "agent-user-sub"
        self.cid = "agent-client-id"


class _Token:
    """A verified provenance token, shaped as `kante.context.Provenance`.

    Hand-built rather than minted and signed: what is under test is that the
    claims reach the assertion, not that `authentikate` verifies a signature —
    which it has its own tests for, and which needs a running Rekuest to produce.
    """

    def __init__(self) -> None:
        self.iss = "rekuest"
        self.aud = ["kraph"]
        self.sub = "caller-sub"
        self.act = _Actor()
        self.iat = datetime.datetime(2026, 8, 14, tzinfo=datetime.timezone.utc)
        self.exp = datetime.datetime(2026, 8, 15, tzinfo=datetime.timezone.utc)
        self.jti = "token-id-once"
        self.tsk = "assignation-42"
        self.ptk = "assignation-41"
        self.rtk = "assignation-1"
        self.rcb = "the-human-who-asked"
        self.ahs = "sha256-of-the-canonical-args"
        self.aha = "canonical/v1"
        self.raw = "eyJ0aGlzIjoiaXMgYSBjcmVkZW50aWFsIn0"


@pytest.fixture
def provenanced_context(simple_api_context: HttpContext) -> HttpContext:
    """The ordinary test context, plus the token an assigned action would carry."""
    token = _Token()
    simple_api_context.request.set_provenance(token)  # type: ignore[arg-type]
    simple_api_context.request.set_extension("provenance", token)
    return simple_api_context


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_unprovenanced_write_still_records_a_claim(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """A human at a keyboard is not running an action, and must not be refused.

    The provenance path fails open on purpose. Requiring an assignation id would
    refuse a fact about the world on a bookkeeping technicality — the same
    argument `writer.ensure_term` makes about words no graph has declared.
    """
    entity_id = await writes.create_entity(api_schema, simple_api_context, "Cell")

    @sync_to_async
    def assertion_for() -> evidence_models.Assertion:
        node = evidence_models.Instance.objects.for_organization(test_graph.organization).select_related("assertion").get(pk=entity_id)
        return node.assertion

    assertion = await assertion_for()
    assert assertion.subject, "Who claimed it is always recorded"
    assert assertion.action_id is None, "There was no run, so there is no run to name"
    assert assertion.action_args == {}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_provenanced_write_records_the_run(
    api_schema: kante.Schema,
    provenanced_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The token's claims reach the assertion, without `KoherentExtension`.

    `action_id` is the assignation — "which run produced this" — and the args hash
    is kept beside it so the inputs can be recomputed and checked years later,
    which is the point of storing it on the claim rather than in a log line.
    """
    entity_id = await writes.create_entity(api_schema, provenanced_context, "Cell")

    @sync_to_async
    def assertion_for() -> evidence_models.Assertion:
        node = evidence_models.Instance.objects.for_organization(test_graph.organization).select_related("assertion").get(pk=entity_id)
        return node.assertion

    assertion = await assertion_for()

    assert assertion.action_id == "assignation-42", "The assignation is what identifies the run"
    assert assertion.action_args["args_hash"] == "sha256-of-the-canonical-args"
    assert assertion.action_args["args_hash_algorithm"] == "canonical/v1"

    # The causal chain, so "who ultimately asked for this" is answerable from the
    # assertion alone rather than by walking somebody else's task table.
    assert assertion.action_args["root_task"] == "assignation-1"
    assert assertion.action_args["parent_task"] == "assignation-41"
    assert assertion.action_args["assigner"] == "the-human-who-asked"
    assert assertion.action_args["agent"] == "agent-user-sub"
    assert assertion.action_args["agent_client_id"] == "agent-client-id"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_raw_token_is_never_stored(
    api_schema: kante.Schema,
    provenanced_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """It is a single-use credential, and an assertion outlives every use for one."""
    entity_id = await writes.create_entity(api_schema, provenanced_context, "Cell")

    @sync_to_async
    def stored() -> str:
        node = evidence_models.Instance.objects.for_organization(test_graph.organization).select_related("assertion").get(pk=entity_id)
        return repr(node.assertion.action_args)

    assert "eyJ0aGlzIjoiaXMgYSBjcmVkZW50aWFsIn0" not in await stored(), "The raw token must not be persisted"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_selector_can_filter_by_the_run(
    api_schema: kante.Schema,
    provenanced_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """What populating `action_id` buys: "count only what this analysis produced".

    Note the condition that is still dead. An `ACTION` condition has no
    source — a provenance token attests causation and carries no human-readable
    name for the action, and neither does `koherent.Task`, which is built from the
    same claims. Filtering by run means filtering on `action_id`.
    """
    await writes.create_entity(api_schema, provenanced_context, "Cell")

    @sync_to_async
    def counts() -> tuple[int, int]:
        assertions = evidence_models.Assertion.objects.for_organization(test_graph.organization)
        return (
            assertions.filter(action_id="assignation-42").count(),
            assertions.filter(action_name__isnull=False).count(),
        )

    by_run, named = await counts()
    assert by_run >= 1, "Evidence is attributable to the run that produced it"
    assert named == 0, "And nothing carries an action name, because nothing supplies one"
