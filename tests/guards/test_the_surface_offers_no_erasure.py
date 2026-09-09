"""Instance data cannot be destroyed through the API (A1).

Evidence is append-only, so a retraction is a `Standing` and the record of what
a derived value once rested on survives. Asserting the *absence* of a surface,
rather than trusting the removal to stick, is the pattern: a primitive with no
caller is one the next write path reaches for. Genuine erasure lives in
`manage.py redact` — deliberate, operator-only, unreachable from a request.

History: every `delete*` mutation for instance data contradicted this, and
`deleteEntity` was worse — it detached the vertex while leaving the node's
status active, so `reproject` resurrected every deleted entity. The in-place
`update*` mutations went the same way: a correction is a new claim.
"""

import re

import pytest

from api.schema import schema

#: Every mutation that used to destroy instance data.
REMOVED = [
    "deleteEntity",
    "deleteStructure",
    "deleteMetric",
    "deleteRelation",
    "deleteMeasurement",
    "deleteStructureRelation",
    "deleteNaturalEvent",
    "deleteProtocolEvent",
    # Named `archive*`, implemented as `item.delete()`. Their `delete*` twins
    # remain — these are config rows, not evidence — so nothing is lost by
    # dropping the pair that lied about what it did.
    "archiveScatterPlot",
    # The in-place update archived the node and created a new uuid, so a correction  # retired
    # forked identity and every metric and relation keyed on the old ref stopped
    # describing it. Its whole payload was `supportingEvidence` — which
    # `assertInforms` attaches to a *live* entity — plus
    # `stickyProperties`, which nothing ever read. Corrections are additive now:
    # measurements accumulate, and classification is a `CLASSIFIES` claim. This
    # was the one mutation contradicting BIOLOGIST.md's rule that you cannot
    # change the entity directly, only provide new evidence.
    "updateEntity",  # retired
    # Same defect for events: archive the node, mint a new uuid. They survived
    # the entity update's removal only because their payload carried role mappings  # retired
    # and nothing else could change who took part. `assertParticipation` does
    # that additively now, so their last job is gone.
    "updateNaturalEvent",  # retired
    "updateProtocolEvent",  # retired
]

#: The retraction path each removed mutation's callers should use instead. Kept as
#: a positive assertion so this file cannot pass by the schema simply being empty.
#:
#: Spelled `retract*` rather than `archive*`. Nothing is put away: a
#: `Standing(stands=False)` is written and the drawing is removed, which is what the
#: rest of the codebase has always called retraction.
RETAINED = [
    "retractEntity",
    "retractStructure",
    "retractMetric",
    "retractRelation",
    "retractMeasurement",
    "retractStructureRelation",
    "retractNaturalEvent",
    "retractProtocolEvent",
]


def _mutation_fields() -> set[str]:
    """The field names on the root Mutation type.

    Parsed from the Mutation block rather than the whole SDL: `deleteEntity` is a
    substring of `deleteEntityCategory` and of `DeleteEntityInput`, so a
    document-wide search would pass while the mutation was still mounted.
    """
    sdl = str(schema)
    block = re.search(r"type Mutation \{(.*?)\n\}", sdl, re.S)
    assert block, "schema must expose a Mutation type"
    return set(re.findall(r"^\s+(\w+)\(", block.group(1), re.M))


@pytest.mark.parametrize("name", REMOVED)
def test_hard_delete_mutation_is_absent(name: str) -> None:
    """No API caller can destroy instance data."""
    assert name not in _mutation_fields()


@pytest.mark.parametrize("name", RETAINED)
def test_the_retraction_path_remains(name: str) -> None:
    """Removing the destructive path is only correct if the retracting one stayed."""
    assert name in _mutation_fields()


def test_the_additive_correction_path_remains() -> None:
    """Removing the in-place entity update is only correct because these cover its job.

    Evidence attaches to a live entity through `assertInforms`, and a
    reclassification is a claim rather than a new node. Neither touches identity.
    """
    fields = _mutation_fields()
    assert "assertInforms" in fields, "attaching evidence to an existing entity is how a correction is made"
    assert "assertMetricValue" in fields
    assert "assertParticipation" in fields, "changing who took part in an event must not require replacing the event"
    assert "retractParticipation" in fields, "and withdrawing that claim must not require deleting it"


def test_no_inert_sticky_properties_input() -> None:
    """`stickyProperties` was in the schema and read by nothing.

    Declared on every entity input, so a client could send it and be silently
    ignored — the same silent-no-op class as the rule-less properties
    `materialize` now rejects.
    """
    assert "stickyProperties" not in str(schema)


def test_redact_is_a_management_command_not_a_mutation() -> None:
    """Erasure exists, and is deliberately not reachable from a request."""
    from django.core.management import get_commands

    assert get_commands().get("redact") == "core"
    assert not any(field.lower().startswith("redact") for field in _mutation_fields())
