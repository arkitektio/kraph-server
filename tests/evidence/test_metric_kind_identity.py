"""How a write resolves the term it is recording under.

Two rules, and the symmetry between them is the design:

- **A declaration is exact, and never refused.** `get_or_create` on the whole
  four-tuple, so a second caller declaring a different type gets a second term
  rather than an error.
- **Silence is resolved from the vocabulary.** One existing term wins; none means
  infer and mint; more than one is the single case that still raises.

That last raise is the legitimate remainder of the one this change removed. The
objection was to a *declaration* being rejected, not to an ambiguous *lookup*
being reported — and picking arbitrarily among terms would file the same
measurement in different columns depending on which write happened to run first.
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


def test_an_existing_term_beats_inference(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
) -> None:
    """`45` after `45.2` must not mint an INT term beside the FLOAT one.

    The drift this rule exists to stop. Inference reads `type(value)`, so without
    it the identity of a term would be decided by whether a measurement happened
    to be written with a decimal point — two terms for one quantity, silently, on
    the first two measurements.
    """
    declared = writer.ensure_metric_kind(organization, roi_kind, "vector_length", ValueKind.FLOAT)
    inferred = writer.ensure_metric_kind(organization, roi_kind, "vector_length", value=45)

    assert inferred.pk == declared.pk, "An undeclared write adopts the existing term"
    assert inferred.value_kind == ValueKind.FLOAT.value


def test_inference_mints_when_there_is_nothing_to_adopt(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
) -> None:
    """A first measurement under a new key does not need a declaration."""
    minted = writer.ensure_metric_kind(organization, roi_kind, "brightness", value=7.5)

    assert minted.value_kind == ValueKind.FLOAT.value


def test_an_undeclared_write_against_an_ambiguous_key_raises(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
) -> None:
    """The one raise that survives, and it names both terms.

    Not a contradiction being rejected — both terms are legitimate and both stay.
    It is a lookup with no answer, and the caller is the only one who can supply
    it.
    """
    writer.ensure_metric_kind(organization, roi_kind, "confidence", ValueKind.FLOAT)
    writer.ensure_metric_kind(organization, roi_kind, "confidence", ValueKind.STRING)

    with pytest.raises(ValueError) as excinfo:
        writer.ensure_metric_kind(organization, roi_kind, "confidence", value=0.9)

    message = str(excinfo.value)
    assert "FLOAT" in message and "STRING" in message, "The error must name both terms to be actionable"

    # And declaring resolves it, without disturbing either term.
    resolved = writer.ensure_metric_kind(organization, roi_kind, "confidence", ValueKind.FLOAT)
    assert resolved.value_kind == ValueKind.FLOAT.value
    assert evidence_models.MetricKind.objects.for_organization(organization).filter(key="confidence").count() == 2


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
