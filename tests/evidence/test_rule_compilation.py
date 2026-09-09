"""The rule language (RFC 0010): (field, operator, value) conditions, compiled.

A definition is a list of rules; a claim counts if any rule matches; a rule
matches when all its `when` conditions hold and no `unless` group does; a group
holds when all its conditions do. Three sentences, all visible in the syntax —
this file pins the compiler (`evidence/selector.py`) and the refusal matrix
that replaced the clause shape's silent edge cases.
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from evidence import models as evidence_models
from evidence import selector, writer
from graph_engine import input_models as models

DEC5 = datetime(2026, 12, 5, tzinfo=timezone.utc)


def _condition(field: str, operator: str, value) -> dict:
    return {"field": field, "operator": operator, "value": value}


def _definition(*rules: dict) -> dict:
    """A stored-shape definition, as `to_stored` writes it."""
    return {"rules": list(rules)}


# --------------------------------------------------------------------------- refusals


def test_a_definition_needs_at_least_one_rule() -> None:
    with pytest.raises(ValidationError):
        models.CategoryDefinitionInput(rules=[])


def test_a_rule_needs_at_least_one_condition() -> None:
    with pytest.raises(ValidationError):
        models.ClaimRuleInput(when=[])


def test_a_category_rule_needs_a_word() -> None:
    """The wordless-clause trap is unspellable now."""
    with pytest.raises(ValidationError, match="WORD"):
        models.CategoryDefinitionInput(rules=[models.ClaimRuleInput(when=[models.ClaimConditionInput(field=models.ClaimField.SUBJECT, operator=models.ClaimOperator.IS, value="peter")])])


@pytest.mark.parametrize(
    ("field", "operator", "value"),
    [
        ("WORD", "NOT_IN", ["AIS"]),  # WORD takes IS/IN only
        ("WORD", "BEFORE", DEC5),  # time operator on an identity field
        ("SUBJECT", "BEFORE", DEC5),
        ("ASSERTED_AT", "IS", "peter"),  # identity operator on a time field
        ("ASSERTED_AT", "BEFORE", "not-a-time"),
        ("SUBJECT", "IS", ["a-list"]),  # IS takes a scalar
        ("SUBJECT", "IN", "not-a-list"),  # IN takes a list
        ("SUBJECT", "IN", []),  # and a non-empty one
        ("KEY", "IS", "area"),  # only a metric row has a key
        ("CONFIDENCE", "IS", 0.9),  # a number takes AT_LEAST/BELOW only (RFC 0016)
        ("CONFIDENCE", "SINCE", DEC5),
        ("CONFIDENCE", "AT_LEAST", 1.5),  # and one in the unit interval
        ("CONFIDENCE", "AT_LEAST", "0.9"),  # a number, not a string
        ("CONFIDENCE", "AT_LEAST", True),  # nor a bool
        ("SUBJECT", "AT_LEAST", 0.9),  # numeric operator on an identity field
        ("OBSERVED_AT", "BELOW", 0.9),  # numeric operator on a time field
    ],
)
def test_invalid_conditions_are_refused_in_a_definition(field: str, operator: str, value) -> None:
    with pytest.raises(ValidationError):
        models.CategoryDefinitionInput(
            rules=[
                models.ClaimRuleInput(
                    when=[
                        models.ClaimConditionInput(field=models.ClaimField.WORD, operator=models.ClaimOperator.IS, value="X"),
                        models.ClaimConditionInput(field=field, operator=operator, value=value),
                    ]
                )
            ]
        )


def test_an_unless_group_may_not_name_words() -> None:
    """Exceptions are about who and when, not vocabulary."""
    with pytest.raises(ValidationError, match="WORD"):
        models.CategoryDefinitionInput(
            rules=[
                models.ClaimRuleInput(
                    when=[models.ClaimConditionInput(field=models.ClaimField.WORD, operator=models.ClaimOperator.IS, value="X")],
                    unless=[models.ClaimConditionGroupInput(when=[models.ClaimConditionInput(field=models.ClaimField.WORD, operator=models.ClaimOperator.IS, value="Y")])],
                )
            ]
        )


def test_rule_evidence_refuses_words_and_requires_a_source() -> None:
    from tests.support import rules as R

    with pytest.raises(ValidationError, match="WORD"):
        models.DerivationRuleInput(source_node="ROI", key="k", evidence=R.evidence(R.rule(R.word("X"))))
    with pytest.raises(ValidationError, match="source_node"):
        models.DerivationRuleInput(evidence=R.evidence(R.rule(R.via("x"))))


def test_rule_evidence_accepts_observed_at() -> None:
    from tests.support import rules as R

    rule = models.DerivationRuleInput(source_node="ROI", key="k", evidence=R.evidence(R.rule(R.observed_since(DEC5))))
    stored = rule.model_dump(mode="json")["evidence"]
    condition = stored["rules"][0]["when"][0]
    assert condition["field"] == "OBSERVED_AT" and condition["operator"] == "SINCE" and condition["value"].startswith("2026-12-05")


def test_the_stored_shape_is_the_one_the_compiler_reads() -> None:
    definition = models.CategoryDefinitionInput(
        rules=[
            models.ClaimRuleInput(
                when=[
                    models.ClaimConditionInput(field=models.ClaimField.WORD, operator=models.ClaimOperator.IN, value=["AIS", "Axon"]),
                    models.ClaimConditionInput(field=models.ClaimField.SUBJECT, operator=models.ClaimOperator.IS, value="peter"),
                ],
                unless=[models.ClaimConditionGroupInput(when=[models.ClaimConditionInput(field=models.ClaimField.APP, operator=models.ClaimOperator.IS, value="sloppy")])],
            )
        ]
    )
    stored = definition.to_stored()
    assert stored["rules"][0]["when"][0] == {"field": "WORD", "operator": "IN", "value": ["AIS", "Axon"]}
    assert stored["rules"][0]["unless"][0]["when"][0] == {"field": "APP", "operator": "IS", "value": "sloppy"}
    assert selector.asserted_as_keys(stored) == ["AIS", "Axon"]


# --------------------------------------------------------------------------- compilation


def _classify(organization, word: str, subject: str, *, app_id: str = "pytest", action_name: str | None = None, asserted_at=None) -> str:
    term = writer.ensure_term(organization, "ENTITY", word)
    assertion = writer.create_assertion(organization, subject=subject, app_id=app_id, action_name=action_name, asserted_at=asserted_at)
    node = evidence_models.Instance.objects.create_for_organization(organization=organization, kind=evidence_models.Instance.Kind.ENTITY, term=term, assertion=assertion)
    writer.create_link(organization, kind=evidence_models.Link.Kind.CLASSIFIES, source_ref=str(node.pk), target_ref=str(term.pk), assertion=assertion, term=term)
    return str(node.pk)


def _matched(organization, definition: dict) -> set[str]:
    claims = evidence_models.Link.objects.for_organization(organization).filter(kind=evidence_models.Link.Kind.CLASSIFIES)
    return {str(ref) for ref in claims.filter(selector.classification_filter(definition)).values_list("source_ref", flat=True)}


@pytest.mark.django_db(transaction=True)
def test_rules_union_and_conditions_intersect(organization) -> None:
    peter_early = _classify(organization, "AIS", "peter", asserted_at=datetime(2026, 11, 1, tzinfo=timezone.utc))
    peter_late = _classify(organization, "AIS", "peter", asserted_at=datetime(2026, 12, 20, tzinfo=timezone.utc))
    karl_late = _classify(organization, "Axon", "karl", asserted_at=datetime(2026, 12, 20, tzinfo=timezone.utc))

    definition = _definition(
        {"when": [_condition("WORD", "IS", "AIS"), _condition("SUBJECT", "IS", "peter"), _condition("ASSERTED_AT", "BEFORE", DEC5.isoformat())]},
        {"when": [_condition("WORD", "IS", "Axon"), _condition("SUBJECT", "IS", "karl"), _condition("ASSERTED_AT", "SINCE", DEC5.isoformat())]},
    )
    assert _matched(organization, definition) == {peter_early, karl_late}, "any rule admits; all conditions within a rule must hold"
    assert peter_late not in _matched(organization, definition)


@pytest.mark.django_db(transaction=True)
def test_an_unless_group_blocks_a_matching_rule(organization) -> None:
    good = _classify(organization, "Probe", "peter", app_id="curation-ui")
    sloppy = _classify(organization, "Probe", "peter", app_id="sloppy-import")

    definition = _definition(
        {"when": [_condition("WORD", "IS", "Probe"), _condition("SUBJECT", "IS", "peter")], "unless": [{"when": [_condition("APP", "IS", "sloppy-import")]}]},
    )
    assert _matched(organization, definition) == {good}, f"the exception blocks the sloppy import, nothing else ({sloppy} excluded)"


@pytest.mark.django_db(transaction=True)
def test_not_in_does_not_drop_claims_with_no_action(organization) -> None:
    """`ACTION NOT_IN [x]` must keep claims that carry no action at all — SQL's
    NULL-swallowing NOT IN is compiled around, not inherited."""
    human = _classify(organization, "Probe", "peter", action_name=None)
    botted = _classify(organization, "Probe", "peter", action_name="auto-segment")

    definition = _definition({"when": [_condition("WORD", "IS", "Probe"), _condition("ACTION", "NOT_IN", ["auto-segment"])]})
    assert _matched(organization, definition) == {human}, f"the human claim (no action) survives; the bot action is excluded ({botted})"


@pytest.mark.django_db(transaction=True)
def test_a_word_only_rule_restricts_trust_for_nobody(organization) -> None:
    definition = _definition({"when": [_condition("WORD", "IS", "Probe")]})
    assert selector.trust_predicate(definition, kind="EXISTENCE") is None, "vocabulary alone places no trust restriction — the fast path stays"
    scoped = _definition({"when": [_condition("WORD", "IS", "Probe"), _condition("SUBJECT", "IS", "peter")]})
    assert selector.trust_predicate(scoped, kind="EXISTENCE") is not None


# --------------------------------------------------------------------------- KIND (RFC 0011)

from tests.support import rules as R  # noqa: E402


def test_a_rule_without_kind_covers_every_kind() -> None:
    stored = R.rule(R.word("X"), R.by("peter"))
    for kind in ("CLASSIFICATION", "EXISTENCE", "SAMENESS", "EVIDENCE", "MEASUREMENT"):
        assert models.rule_covers(stored, kind), kind


def test_kind_coverage_math() -> None:
    only_sameness = R.rule(R.of_kind("SAMENESS"), R.by("curator"))
    assert models.rule_covers(only_sameness, "SAMENESS")
    assert not models.rule_covers(only_sameness, "EXISTENCE")

    two = R.rule(R.of_kind("EXISTENCE", "SAMENESS"), R.by("peter"))
    assert models.rule_covers(two, "EXISTENCE") and models.rule_covers(two, "SAMENESS")
    assert not models.rule_covers(two, "MEASUREMENT")

    carved = R.rule(R.word("X"), R.by("peter"), R.not_kind("SAMENESS"))
    assert models.rule_covers(carved, "CLASSIFICATION") and models.rule_covers(carved, "EXISTENCE")
    assert not models.rule_covers(carved, "SAMENESS")

    # Several KIND conditions AND: covered only where all admit.
    both = R.rule(R.by("peter"), R.of_kind("EXISTENCE", "SAMENESS"), R.not_kind("SAMENESS"))
    assert models.rule_covers(both, "EXISTENCE") and not models.rule_covers(both, "SAMENESS")


def test_kind_refusals() -> None:
    with pytest.raises(ValidationError):  # bad kind value
        models.CategoryDefinitionInput(rules=[models.ClaimRuleInput.model_validate(R.rule(R.word("X"), R.of_kind("NONSENSE")))])
    with pytest.raises(ValidationError, match="KIND"):  # KIND in unless
        models.ClaimRuleInput.model_validate(R.rule(R.by("p"), unless=[[R.of_kind("SAMENESS")]]))
    with pytest.raises(ValidationError, match="KIND"):  # KIND in rule.evidence
        models.DerivationRuleInput(source_node="ROI", key="k", evidence=R.evidence(R.rule(R.of_kind("MEASUREMENT"))))
    with pytest.raises(ValidationError, match="BEFORE"):  # time operator on KIND
        models.ClaimConditionInput.model_validate(R.condition("KIND", "BEFORE", "SAMENESS"))
    with pytest.raises(ValidationError, match="WORD"):  # classification-covering rule needs WORD
        models.CategoryDefinitionInput.model_validate(R.definition(R.rule(R.by("peter"))))
    with pytest.raises(ValidationError, match="WORD"):  # non-classification rule may not carry WORD
        models.CategoryDefinitionInput.model_validate(R.definition(R.rule(R.word("X")), R.rule(R.word("Y"), R.of_kind("EXISTENCE"), R.by("c"))))
    with pytest.raises(ValidationError, match="KEY"):  # KEY outside MEASUREMENT-only
        models.CategoryDefinitionInput.model_validate(R.definition(R.rule(R.word("X"), R.key("area"))))


def test_any_rule_may_bound_observation_time() -> None:
    """OBSERVED_AT is world time on every claim (RFC 0015): a classification
    rule, an existence rule and a measurement rule may all bound it — it was
    MEASURED_AT and metric-only, so a category could not say "cells seen
    before the treatment"."""
    definition = models.CategoryDefinitionInput.model_validate(
        R.definition(
            R.rule(R.word("X"), R.observed_before(DEC5)),
            R.rule(R.of_kind("EXISTENCE"), R.by("peter"), R.observed_since(DEC5)),
            R.rule(R.of_kind("MEASUREMENT"), R.via("scope"), R.observed_since(DEC5)),
        )
    )
    assert definition.rules[0].when[1].field == models.ClaimField.OBSERVED_AT
    assert definition.rules[1].when[2].field == models.ClaimField.OBSERVED_AT
    assert definition.rules[2].when[2].field == models.ClaimField.OBSERVED_AT


def test_any_rule_may_bound_confidence() -> None:
    """CONFIDENCE is a number on every claim (RFC 0016): legal on any kind, in
    `unless`, and in a property's evidence; it compiles to a bound on the
    claim's own column, which a claim without a number never satisfies."""
    definition = models.CategoryDefinitionInput.model_validate(
        R.definition(
            R.rule(R.word("X"), R.at_least(0.9)),
            R.rule(R.of_kind("EXISTENCE"), R.by("peter"), unless=[[R.below(0.3)]]),
            R.rule(R.of_kind("MEASUREMENT"), R.at_least(0.5)),
        )
    )
    assert definition.rules[0].when[1].operator == models.ClaimOperator.AT_LEAST
    assert definition.rules[1].unless[0].when[0].operator == models.ClaimOperator.BELOW
    evidence = models.DerivationRuleInput(source_node="ROI", key="k", evidence=R.evidence(R.rule(R.at_least(0.8))))
    assert evidence.evidence is not None

    classification = selector.trust_filter(definition.to_stored(), kind="CLASSIFICATION")
    assert "confidence__gte" in str(classification) and "0.9" in str(classification)
    existence = selector.trust_filter(definition.to_stored(), kind="EXISTENCE")
    assert "confidence__lt" in str(existence) and "0.3" in str(existence)
    assert "confidence__isnull" not in str(existence), "silence is not below anything, and not above anything either"
    assert "confidence__gte" in str(selector.rule_metric_filter(evidence))


def test_trust_filter_selects_only_applicable_rules() -> None:
    definition = R.definition(
        R.rule(R.word("X"), R.by("peter"), R.not_kind("SAMENESS")),
        R.rule(R.of_kind("SAMENESS"), R.by("curator")),
    )
    existence = selector.trust_filter(definition, kind="EXISTENCE")
    sameness = selector.trust_filter(definition, kind="SAMENESS")
    assert "peter" in str(existence) and "curator" not in str(existence)
    assert "curator" in str(sameness) and "peter" not in str(sameness)


def test_no_applicable_rule_means_nothing_counts_for_that_kind() -> None:
    """Strict grants: carving a kind out of every rule is an explicit act, and
    it means nobody — never everybody."""
    definition = R.definition(R.rule(R.word("X"), R.by("peter"), R.not_kind("SAMENESS")))
    predicate = selector.trust_filter(definition, kind="SAMENESS")
    assert predicate.children, "the contradiction, never the collapsed match-everything Q()"


def test_vocabulary_reads_classification_covering_rules_only() -> None:
    definition = R.definition(
        R.rule(R.word("X"), R.by("peter")),
        R.rule(R.of_kind("SAMENESS"), R.by("curator")),
    )
    assert selector.asserted_as_keys(definition) == ["X"]


# --------------------------------------------------------------------------- property evidence is a rule list, KEY (RFC 0014)


def test_rule_evidence_is_a_rule_list() -> None:
    """The flat condition list is gone: `evidence` has the definition's shape."""
    with pytest.raises(ValidationError):
        models.DerivationRuleInput(source_node="ROI", key="k", evidence=[R.via("x")])
    rule = models.DerivationRuleInput(source_node="ROI", key="k", evidence=R.evidence(R.rule(R.via("v3")), R.rule(R.via("v2"), R.observed_before(DEC5))))
    assert rule.evidence is not None and len(rule.evidence.rules) == 2
    assert rule.evidence.to_stored() == R.evidence(R.rule(R.via("v3")), R.rule(R.via("v2"), R.observed_before(DEC5)))


def test_rule_evidence_takes_unless_and_metric_fields_everywhere() -> None:
    rule = models.DerivationRuleInput(
        source_node="ROI",
        key="k",
        evidence=R.evidence(R.rule(R.not_by("bot"), R.key("vector_length"), unless=[[R.via("old-pipeline"), R.observed_before(DEC5)]])),
    )
    assert rule.evidence is not None
    stored = rule.evidence.to_stored()
    assert stored["rules"][0]["unless"][0]["when"][1]["field"] == "OBSERVED_AT"


def test_rule_evidence_refuses_words_and_kinds_in_unless_too() -> None:
    with pytest.raises(ValidationError, match="WORD"):
        models.DerivationRuleInput(source_node="ROI", key="k", evidence=R.evidence(R.rule(R.via("x"), unless=[[R.word("X")]])))
    with pytest.raises(ValidationError, match="KIND"):
        models.DerivationRuleInput(source_node="ROI", key="k", evidence=R.evidence(R.rule(R.via("x"), unless=[[R.of_kind("MEASUREMENT")]])))


def test_key_is_an_identity_field() -> None:
    assert models.ClaimConditionInput.model_validate(R.key("a", "b")).operator == models.ClaimOperator.IN
    with pytest.raises(ValidationError, match="KEY"):
        models.ClaimConditionInput.model_validate(R.condition("KEY", "BEFORE", DEC5))


def test_key_is_allowed_only_where_a_rule_is_about_measurements() -> None:
    ok = models.CategoryDefinitionInput.model_validate(R.definition(R.rule(R.word("X")), R.rule(R.of_kind("MEASUREMENT"), R.via("a"), R.key("vector_length"))))
    assert ok.rules[1].when[2].field == models.ClaimField.KEY
    with pytest.raises(ValidationError, match="KEY"):  # on a classification rule
        models.CategoryDefinitionInput.model_validate(R.definition(R.rule(R.word("X"), R.key("vector_length"))))
    with pytest.raises(ValidationError, match="KEY"):  # in an unless group of a definition rule
        models.CategoryDefinitionInput.model_validate(R.definition(R.rule(R.word("X"), unless=[[R.key("vector_length")]])))


def _sql(predicate) -> str:
    return str(predicate)


def test_rule_metric_filter_unions_rules_and_honours_unless() -> None:
    rule = models.DerivationRuleInput(
        source_node="ROI",
        key="k",
        evidence=R.evidence(
            R.rule(R.via("v3")),
            R.rule(R.via("v2"), R.observed_before(DEC5), unless=[[R.by("intern")]]),
        ),
    )
    compiled = _sql(selector.rule_metric_filter(rule))
    assert "OR" in compiled and "v3" in compiled and "v2" in compiled
    assert "observed_at__lte" in compiled and "NOT" in compiled and "intern" in compiled


def test_metric_scope_standing_half_skips_the_key_and_reads_time_from_at() -> None:
    """A standing has no key, so the standing predicate drops KEY; it does
    have world time — its own `at` (RFC 0015) — so OBSERVED_AT compiles against
    that column rather than the claim's `observed_at`."""
    rule = models.DerivationRuleInput(source_node="ROI", key="k", evidence=R.evidence(R.rule(R.via("v3"), R.key("vector_length"), R.observed_before(DEC5))))
    claim, standing = selector.metric_scope(None, rule)
    assert "key__in" in _sql(claim) and "observed_at__lte" in _sql(claim)
    assert standing is not None and "key" not in _sql(standing) and "observed_at" not in _sql(standing) and "v3" in _sql(standing)
    assert "'at__lte'" in _sql(standing)

    unconstrained = models.DerivationRuleInput(source_node="ROI", key="k", evidence=R.evidence(R.rule(R.key("vector_length"))))
    _, standing = selector.metric_scope(None, unconstrained)
    assert standing is None, "a rule that only names keys restricts nobody's standing — the fast path stays"


def test_key_in_a_measurement_only_definition_rule_compiles_on_the_metric_side_only() -> None:
    definition = R.definition(R.rule(R.word("X"), R.not_kind("MEASUREMENT")), R.rule(R.of_kind("MEASUREMENT"), R.via("a"), R.key("vector_length")))
    claim = selector.trust_filter(definition, kind="MEASUREMENT", asserted_at_column="asserted_at", include_metric_fields=True)
    assert "key__in" in _sql(claim)
    standing = selector.trust_predicate(definition, kind="MEASUREMENT")
    assert standing is not None and "key" not in _sql(standing)
