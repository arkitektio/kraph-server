"""A value that does not match its declared kind says so.

The complement to making `value_kind` required. While the write path guessed, a
mismatch was the system's fault and the best it could do was fail somewhere
downstream. Now the caller states the kind, so a mismatch is their own
declaration disagreeing with what they sent — and the error should say that
rather than surfacing `could not convert string to float: 'high'` from inside
`float()`, which names neither the key nor the kind and leaves a caller batching
many measurements to work out which one it came from.
"""

import pytest
from authentikate.models import Organization

from core.enums import ValueKind
from evidence import models as evidence_models
from evidence import writer


def test_a_string_under_a_float_term_names_all_three(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
    assertion: evidence_models.Assertion,
) -> None:
    """The key, the declared kind, and the value that did not fit."""
    structure = writer.ensure_structure(organization, roi_kind, "roi-mismatch", assertion)
    term = writer.ensure_metric_kind(organization, roi_kind, "vector_length", ValueKind.FLOAT)

    with pytest.raises(ValueError) as excinfo:
        writer.record_metric(organization, structure, term, key="vector_length", value="high", assertion=assertion)

    message = str(excinfo.value)
    assert "vector_length" in message, "…so a failure inside a batch can be located"
    assert "FLOAT" in message, "…so the caller can see which declaration is being enforced"
    assert "high" in message, "…and which value broke it"


def test_the_underlying_cause_is_kept(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
    assertion: evidence_models.Assertion,
) -> None:
    """Wrapped, not swallowed. The original coercion failure stays reachable.

    Losing it would trade one unhelpful error for a different one — the wrapper
    says what was declared, the cause says what the conversion actually objected
    to.
    """
    structure = writer.ensure_structure(organization, roi_kind, "roi-cause", assertion)
    term = writer.ensure_metric_kind(organization, roi_kind, "count", ValueKind.INT)

    with pytest.raises(ValueError) as excinfo:
        writer.record_metric(organization, structure, term, key="count", value="not a number", assertion=assertion)

    assert excinfo.value.__cause__ is not None, "The coercion error must survive as __cause__"


def test_a_value_that_does_fit_is_untouched(
    organization: Organization,
    roi_kind: evidence_models.StructureKind,
    assertion: evidence_models.Assertion,
) -> None:
    """The wrapper must not change what a well-formed write does.

    Coercion across compatible types is deliberate — an INT term accepts `3` and
    a STRING term accepts `12.5` as text — and only genuine failures are
    reported.
    """
    structure = writer.ensure_structure(organization, roi_kind, "roi-fits", assertion)

    as_text = writer.ensure_metric_kind(organization, roi_kind, "label", ValueKind.STRING)
    recorded = writer.record_metric(organization, structure, as_text, key="label", value=12.5, assertion=assertion)
    assert recorded.value == "12.5", "A STRING term stores a number as its text"

    as_int = writer.ensure_metric_kind(organization, roi_kind, "count", ValueKind.INT)
    counted = writer.record_metric(organization, structure, as_int, key="count", value=3, assertion=assertion)
    assert counted.value == 3
    assert type(counted.value) is int, "INT shares value_num with FLOAT and has to narrow back on the way out"
