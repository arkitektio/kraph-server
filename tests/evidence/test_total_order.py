"""The log has an order to replay in.

`docs/LOG.md` carried this as a known gap: every evidence row is keyed on a
`uuid4`, so "replay the log in order" had no order. `Claim.recorded_at` broke ties
within one target and conceded in its own help_text that it was "a tiebreak, not a
total order" — two claims written in one request share it to the microsecond often
enough that the fold could return either, so the same evidence could produce two
different graphs.

These tests hold the three properties the column has to have: the database assigns
it, it is monotonic, and the fold actually uses it.
"""

from __future__ import annotations

import datetime

import pytest
from django.db import connection

from evidence import claims as claims_module
from evidence import models as evidence_models
from evidence import writer


@pytest.mark.django_db(transaction=True)
def test_the_database_assigns_seq_and_no_writer_can_pass_one(organization) -> None:
    """`seq` comes from a sequence, not from application code.

    `writer.create_assertion` takes no `seq` argument and the field is
    `editable=False` with a `db_default`, so there is no path by which a caller
    chooses its own position in the log.
    """
    assertion = writer.create_assertion(organization, subject="someone", app_id="app")
    assertion.refresh_from_db()

    assert assertion.seq is not None, "The database must assign a position"
    assert isinstance(assertion.seq, int)

    field = evidence_models.Assertion._meta.get_field("seq")
    assert field.editable is False, "A writer choosing its own seq would be choosing where in history it lands"
    assert field.unique is True, "Two assertions sharing a position is the tie this column exists to remove"


@pytest.mark.django_db(transaction=True)
def test_seq_is_monotonic_across_assertions(organization) -> None:
    """Later assertions get higher positions, and none repeat."""
    written = [writer.create_assertion(organization, subject=f"s{index}", app_id="app") for index in range(25)]
    for assertion in written:
        assertion.refresh_from_db()

    seqs = [assertion.seq for assertion in written]

    assert seqs == sorted(seqs), "Arrival order and seq order must agree"
    assert len(set(seqs)) == len(seqs), "No two assertions may share a position"


@pytest.mark.django_db(transaction=True)
def test_seq_does_not_repeat_across_organizations(organization, other_organization) -> None:
    """One order spans the log, not one per tenant.

    Tenancy scopes what a fold *reads*; it does not give each tenant its own
    history. A per-organization counter would make "replay everything in order"
    unanswerable the moment two tenants existed.
    """
    here = writer.create_assertion(organization, subject="a", app_id="app")
    there = writer.create_assertion(other_organization, subject="b", app_id="app")
    here.refresh_from_db()
    there.refresh_from_db()

    assert here.seq != there.seq
    assert there.seq > here.seq, "The sequence is global and does not restart per tenant"


@pytest.mark.django_db(transaction=True)
def test_the_fold_breaks_ties_on_seq_not_on_wall_clock(organization, roi_kind) -> None:
    """Two claims at the same instant resolve deterministically, by the later assertion.

    This is the case `recorded_at` could not decide. Both claims are given the
    *same* `at`, so the fold has nothing to order them by except the tiebreak — and
    the answer must be the one asserted later, every time.
    """
    instant = datetime.datetime(2026, 3, 3, 12, 0, 0, tzinfo=datetime.timezone.utc)

    minting = writer.create_assertion(organization, subject="minter", app_id="app")
    structure = writer.ensure_structure(organization, kind=roi_kind, object="roi-total-order", assertion=minting)

    first = writer.create_assertion(organization, subject="first", app_id="app")
    writer.claim_ref(
        organization,
        target_type="structure",
        target_id=str(structure.pk),
        stands=True,
        assertion=first,
        at=instant,
    )

    second = writer.create_assertion(organization, subject="second", app_id="app")
    writer.claim_ref(
        organization,
        target_type="structure",
        target_id=str(structure.pk),
        stands=False,
        assertion=second,
        at=instant,
    )

    assert claims_module.stands(organization, "structure", str(structure.pk)) is False, "The later assertion wins a tie on `at`"

    # And the same answer read the batch way, which folds in Python over the
    # ordered queryset rather than taking `.first()`.
    folded = claims_module.stands_for(organization, "structure", [str(structure.pk)])
    assert folded[str(structure.pk)] is False


@pytest.mark.django_db(transaction=True)
def test_the_sequence_survives_a_gap(organization) -> None:
    """Gaps are expected; density is not promised.

    A rolled-back transaction consumes a sequence value and leaves a hole. Any
    reader that treats `seq` as dense — "the next one is n+1" — breaks the first
    time a write fails, so the property under test is ordering, not contiguity.
    """
    before = writer.create_assertion(organization, subject="before", app_id="app")
    before.refresh_from_db()

    with connection.cursor() as cursor:
        cursor.execute(f"SELECT nextval('{evidence_models.ASSERTION_SEQ}')")
        burned = cursor.fetchone()[0]

    after = writer.create_assertion(organization, subject="after", app_id="app")
    after.refresh_from_db()

    assert before.seq < burned < after.seq, "The burned value is skipped, and order still holds across the hole"
