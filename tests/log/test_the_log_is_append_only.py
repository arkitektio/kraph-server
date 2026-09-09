"""The log is append-only, and the database says so.

`evidence/writer.py` promised this in its module docstring from the beginning, and
for just as long the promise was enforced by nothing — while being false: `record_standing()`
wrote the row and then flipped a cached `stands` boolean on the target, an `UPDATE`
on a log table four lines below the sentence saying there were none.

Two changes made the rule real. The cached answer moved to `CurrentStanding`, a
projection (`0004`), and a trigger now refuses `UPDATE` and `DELETE` on the six log
tables (`0005`). These tests hold the second one up. Without them the guard is a
migration nobody would notice the absence of.

Triggers rather than `REVOKE`, and the reason matters for what can be tested: a
superuser ignores table privileges, and the role the test stack connects as is one.
A grant-based guard would pass a test that asserted nothing.
"""

from __future__ import annotations
import pytest
from django.db import connection, transaction
from django.db.utils import IntegrityError
from evidence import claims as claims_module
from evidence import models as evidence_models
from evidence import writer


REFUSED = IntegrityError
@pytest.mark.django_db(transaction=True)
def test_an_assertion_cannot_be_updated(organization) -> None:
    """The provenance record is immutable — including through `queryset.update()`.

    The ORM-level guard is not enough on its own: `queryset.update()` never calls
    `save()`, and five test call sites were using exactly that to flip `stands`
    with no claim behind it before the column was removed.
    """
    assertion = writer.create_assertion(organization, subject="someone", app_id="app")

    with pytest.raises(REFUSED), transaction.atomic():
        evidence_models.Assertion.all_objects.filter(pk=assertion.pk).update(subject="somebody-else")

    assertion.refresh_from_db()
    assert assertion.subject == "someone", "The row is unchanged, not merely reported as unchanged"
@pytest.mark.django_db(transaction=True)
def test_a_claim_cannot_be_deleted(organization, roi_kind) -> None:
    """Withdrawing a claim is another claim. Removing the record is not an option."""
    minting = writer.create_assertion(organization, subject="minter", app_id="app")
    structure = writer.ensure_structure(organization, kind=roi_kind, object="roi-append-only", assertion=minting)

    retracting = writer.create_assertion(organization, subject="retractor", app_id="app")
    writer.retract(organization, structure, retracting)

    with pytest.raises(REFUSED), transaction.atomic():
        evidence_models.Standing.all_objects.filter(target_id=str(structure.pk)).delete()

    assert evidence_models.Standing.objects.for_organization(organization).filter(target_id=str(structure.pk)).count() == 1
@pytest.mark.django_db(transaction=True)
def test_every_log_table_refuses_a_rewrite(organization, roi_kind, length_category) -> None:
    """Not just the two most obvious ones.

    Every table, because the guard is attached per-table: covering five of six
    would leave a hole nothing else would find. Each one gets a real row first —
    the trigger is `FOR EACH ROW`, so an `UPDATE` against an empty table touches
    nothing and would pass a test that only asserted it raised.
    """
    assertion = writer.create_assertion(organization, subject="minter", app_id="app")
    structure = writer.ensure_structure(organization, kind=roi_kind, object="roi-every-table", assertion=assertion)
    writer.record_metric(organization, structure, length_category, key="length", value=1.0, assertion=assertion)
    term = writer.ensure_term(organization, "ENTITY", "Cell")
    node = evidence_models.Instance.objects.create_for_organization(
        organization=organization,
        kind=evidence_models.Instance.Kind.ENTITY,
        term=term,
        assertion=assertion,
    )
    writer.create_link(
        organization,
        kind=evidence_models.Link.Kind.INFORMS,
        source_ref=str(structure.pk),
        target_ref=str(node.pk),
        assertion=assertion,
    )

    # `evidence_standing` has no row yet — recording a metric states no position on
    # anything — so retract something to give it one, and the loop stays uniform.
    writer.retract(organization, structure, writer.create_assertion(organization, subject="r", app_id="app"))

    # The table names the renames moved: `evidence_claim` → `evidence_standing`,
    # `evidence_node` → `evidence_instance`. The trigger follows the table through
    # `ALTER TABLE … RENAME`, so this guard never lapsed — but `0008` recreates each
    # one under the new name, and this is what proves it did.
    for table in ("evidence_assertion", "evidence_standing", "evidence_structure", "evidence_metric", "evidence_link", "evidence_instance"):
        with pytest.raises(REFUSED, match="append-only"), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(f"UPDATE {table} SET organization_id = organization_id")
@pytest.mark.django_db(transaction=True)
def test_projections_stay_mutable(organization, roi_kind) -> None:
    """`CurrentStanding` and `State` are folded from the log and must be rewritable.

    The guard covers the log, not everything in the app. A projection that could
    not be rebuilt would not be a projection — `refold_current` deletes and
    replays every row of one, and `refold_state` does the same for the other.
    """
    minting = writer.create_assertion(organization, subject="minter", app_id="app")
    structure = writer.ensure_structure(organization, kind=roi_kind, object="roi-projection", assertion=minting)
    writer.retract(organization, structure, writer.create_assertion(organization, subject="r", app_id="app"))

    rows = evidence_models.CurrentStanding.objects.for_organization(organization).filter(target_id=structure.pk)
    assert rows.count() == 1, "The retraction produced a cached answer"

    rows.update(stands=True)  # must not raise
    rows.delete()  # nor this

    # And it comes back from the log, which is the property that makes it a cache.
    claims_module.refold_current(organization)
    assert claims_module.current(organization, "structure", structure.pk) is False
@pytest.mark.django_db(transaction=True)
def test_the_escape_hatch_is_explicit_and_transaction_scoped(organization) -> None:
    """`redact` can destroy; nothing else inherits the permission.

    `SET LOCAL` binds the exemption to one transaction, so an erasure cannot leave
    the guard down for whatever runs next on the same connection.
    """
    doomed = writer.create_assertion(organization, subject="doomed", app_id="app")

    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL kraph.allow_log_rewrite = 'on'")
        evidence_models.Assertion.all_objects.filter(pk=doomed.pk).delete()

    assert not evidence_models.Assertion.all_objects.filter(pk=doomed.pk).exists(), "The sanctioned path does destroy"

    survivor = writer.create_assertion(organization, subject="survivor", app_id="app")
    with pytest.raises(REFUSED), transaction.atomic():
        evidence_models.Assertion.all_objects.filter(pk=survivor.pk).delete()
@pytest.mark.django_db(transaction=True)
def test_concurring_claims_are_both_recorded(organization, roi_kind) -> None:
    """Two annotators retracting the same thing are two claims, not one.

    The dedup that used to suppress the second one was not tidiness — it was the
    guard that kept `state.retract` from subtracting twice, and it lived on the
    mutable `stands` column. Moving that guard onto the transition is what let the
    log stop dropping concurrence, so this is the behaviour that change bought.
    """
    minting = writer.create_assertion(organization, subject="minter", app_id="app")
    structure = writer.ensure_structure(organization, kind=roi_kind, object="roi-concurrence", assertion=minting)

    first = writer.retract(organization, structure, writer.create_assertion(organization, subject="johannes", app_id="app"))
    second = writer.retract(organization, structure, writer.create_assertion(organization, subject="christian", app_id="app"))

    assert first.standing.pk != second.standing.pk, "Both retractions are on the record"
    assert first.moved is True, "The first one changed the answer"
    assert second.moved is False, "The second agreed with it, so nothing to re-fold"

    claims = evidence_models.Standing.objects.for_organization(organization).filter(target_id=str(structure.pk))
    assert claims.count() == 2
    assert sorted(claim.assertion.subject for claim in claims) == ["christian", "johannes"], "And who said so is answerable"
@pytest.mark.django_db(transaction=True)
def test_the_migrations_escape_hatch_actually_rewrites_the_log(organization, roi_kind) -> None:
    """`0008`'s data migration rewrites a log table, and this is the only proof it can.

    The migration that renamed `Claim` to `Standing` also had to rewrite
    `target_type` from `'node'` to `'instance'` — an `UPDATE` on a log table, which
    the guard exists to refuse. `0005` sanctions exactly one way through, and this
    runs that SQL verbatim: `SET LOCAL kraph.allow_log_rewrite = 'on'` followed by
    the updates, in one multi-statement string, which is what psycopg actually sends.

    **Migrating a green test database proves nothing about this.** Migrations run
    before any test data exists, so the `WHERE target_type = 'node'` in the real
    migration matched zero rows and the `FOR EACH ROW` trigger never fired. A row has
    to exist for the escape to be exercised at all, so this makes one.
    """
    import importlib

    migration = importlib.import_module("evidence.migrations.0008_instance_and_standing")

    minting = writer.create_assertion(organization, subject="minter", app_id="app")
    structure = writer.ensure_structure(organization, kind=roi_kind, object="roi-escape-hatch", assertion=minting)
    writer.retract(organization, structure, writer.create_assertion(organization, subject="r", app_id="app"))

    standings = evidence_models.Standing.objects.for_organization(organization).filter(target_id=str(structure.pk))
    assert standings.count() == 1, "There is a log row for the escape to have to get past"

    # Without the escape: refused, which is the guard working.
    with pytest.raises(REFUSED), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("UPDATE evidence_standing SET target_type = 'rewritten'")

    # With it, and through the migration's own SQL rather than a paraphrase of it.
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(migration._rename_target_type("structure", "rewritten"))

    assert standings.filter(target_type="rewritten").count() == 1, "The escape hatch let the rewrite through"

    # And it does not outlive the transaction it was set in — `SET LOCAL`, not `SET`.
    with pytest.raises(REFUSED), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("UPDATE evidence_standing SET target_type = 'structure'")
