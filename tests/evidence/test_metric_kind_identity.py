"""How a write resolves the term it is recording under.

One rule: **the caller states the value kind, and it is exact.** A declaration is
therefore never refused — a second caller declaring a different type gets a
second term rather than an error.

This file used to describe a second rule for callers who declared nothing:
adopt the key's single existing term, or infer one from ``type(value)`` and mint,
or raise when several terms existed. All of it is gone, and three tests went with
it. The raise is why. Its message said "Declare one" while the inputs that
reached it — `createMetric`, `updateMetric`, supporting evidence — had no field
to declare with, so a key with two terms became unwritable through them.

Requiring the kind removes that branch instead of repairing it, and the rest of
the guessing follows: with nothing inferring, a term's identity no longer depends
on whether a measurement happened to be written ``45`` or ``45.2``, and the
adopt-the-existing-term rule that existed to paper over exactly that is
unnecessary.
"""

import pytest
from authentikate.models import Organization

from core.enums import ValueKind
from evidence import models as evidence_models
from evidence import writer


def test_a_declaration_is_never_refused(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
) -> None:
    """Both declarations land. Neither caller is told to go away."""
    as_float = writer.ensure_metric_kind(organization, roi_kind, "confidence", ValueKind.FLOAT)
    as_category = writer.ensure_metric_kind(organization, roi_kind, "confidence", ValueKind.CATEGORY)

    assert as_float.pk != as_category.pk
    assert as_float.value_kind == ValueKind.FLOAT.value
    assert as_category.value_kind == ValueKind.CATEGORY.value


def test_a_declaration_is_idempotent(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
) -> None:
    """Declaring the same thing twice is a lookup, not a second term."""
    first = writer.ensure_metric_kind(organization, roi_kind, "confidence", ValueKind.FLOAT)
    again = writer.ensure_metric_kind(organization, roi_kind, "confidence", ValueKind.FLOAT)

    assert first.pk == again.pk
    assert evidence_models.MetricKind.objects.for_organization(organization).filter(key="confidence").count() == 1


def test_the_property_type_spelling_is_accepted(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
) -> None:
    """The GraphQL surface says "float"; storage says FLOAT. One term either way.

    Without normalising at this boundary the two spellings would be two terms,
    and the lowercase one would carry a `value_kind` no column mapping
    recognises — `writer.value_columns` rejects it outright.
    """
    canonical = writer.ensure_metric_kind(organization, roi_kind, "confidence", ValueKind.FLOAT)
    lowercase = writer.ensure_metric_kind(organization, roi_kind, "confidence", "float")

    assert canonical.pk == lowercase.pk


def test_a_missing_value_kind_is_refused(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
) -> None:
    """No kind, no term. There is nothing left that guesses one.

    Replaces three tests that covered the guessing: adopt-the-existing-term,
    infer-and-mint, and the raise when a key had several terms. The last of those
    was unactionable — it told callers to declare a kind through inputs that had
    no field for one — and the first two only existed to keep inference from
    forking a key. The error names the key so a failure inside a batch of
    measurements can be located.
    """
    with pytest.raises(ValueError) as excinfo:
        writer.ensure_metric_kind(organization, roi_kind, "confidence", None)

    message = str(excinfo.value)
    assert "confidence" in message, "The error must name the key it could not record"
    assert "@mikro/roi" in message


def test_a_key_with_several_terms_is_writable(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
) -> None:
    """The dead end, at the writer level.

    Two terms for one key used to make an undeclared write impossible. Naming the
    kind resolves it exactly, and neither existing term is disturbed.
    """
    as_float = writer.ensure_metric_kind(organization, roi_kind, "confidence", ValueKind.FLOAT)
    as_string = writer.ensure_metric_kind(organization, roi_kind, "confidence", ValueKind.STRING)

    assert writer.ensure_metric_kind(organization, roi_kind, "confidence", ValueKind.STRING).pk == as_string.pk
    assert writer.ensure_metric_kind(organization, roi_kind, "confidence", ValueKind.FLOAT).pk == as_float.pk
    assert evidence_models.MetricKind.objects.for_organization(organization).filter(key="confidence").count() == 2


def test_nothing_infers_a_value_kind(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
) -> None:
    """`45` and `45.2` under one declared key stay one term.

    Not because an existing term wins over inference — because there is no
    inference. `writer` exports no way to guess a kind from a value, and this
    asserts that rather than trusting the deletion stuck: a re-introduced
    `infer_value_kind` would be a guessing primitive with no caller, and the next
    write path to want one would reach for it.
    """
    assert not hasattr(writer, "infer_value_kind")

    first = writer.ensure_metric_kind(organization, roi_kind, "vector_length", ValueKind.FLOAT)
    second = writer.ensure_metric_kind(organization, roi_kind, "vector_length", ValueKind.FLOAT)

    assert first.pk == second.pk
    assert evidence_models.MetricKind.objects.for_organization(organization).filter(key="vector_length").count() == 1


def test_an_unknown_value_kind_is_rejected(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
) -> None:
    """A misspelling must not become a term nothing can read back.

    `Metric.value` looks its column up by `value_kind`, so a term carrying a kind
    outside the vocabulary produces rows whose value cannot be retrieved at all.
    """
    with pytest.raises(ValueError, match="Unknown value kind"):
        writer.ensure_metric_kind(organization, roi_kind, "confidence", "flaot")


def test_terms_never_cross_organizations(
    organization: Organization,
    other_organization: Organization,
    roi_kind: evidence_models.StructureKind,
) -> None:
    """Vocabulary is per-tenant, and the four-tuple does not change that."""
    other_roi = writer.ensure_structure_kind(other_organization, "@mikro/roi")

    writer.ensure_metric_kind(organization, roi_kind, "confidence", ValueKind.FLOAT)
    writer.ensure_metric_kind(other_organization, other_roi, "confidence", ValueKind.FLOAT)

    assert evidence_models.MetricKind.objects.for_organization(organization).count() == 1
    assert evidence_models.MetricKind.objects.for_organization(other_organization).count() == 1


def test_the_term_names_its_value_kind(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
) -> None:
    """Two terms for one key must not print identically.

    The admin list and `ensure_metric_kind`'s own ambiguity error are exactly
    where telling them apart matters.
    """
    as_float = writer.ensure_metric_kind(organization, roi_kind, "confidence", ValueKind.FLOAT)
    as_string = writer.ensure_metric_kind(organization, roi_kind, "confidence", ValueKind.STRING)

    assert str(as_float) != str(as_string)
    assert "FLOAT" in str(as_float)
