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
        ("MEASURED_AT", "SINCE", DEC5),  # a claim has no observation time
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
    with pytest.raises(ValidationError, match="WORD"):
        models.DerivationRuleInput(source_node="ROI", key="k", evidence=[models.ClaimConditionInput(field=models.ClaimField.WORD, operator=models.ClaimOperator.IS, value="X")])
    with pytest.raises(ValidationError, match="source_node"):
        models.DerivationRuleInput(evidence=[models.ClaimConditionInput(field=models.ClaimField.APP, operator=models.ClaimOperator.IS, value="x")])


def test_rule_evidence_accepts_measured_at() -> None:
    rule = models.DerivationRuleInput(source_node="ROI", key="k", evidence=[models.ClaimConditionInput(field=models.ClaimField.MEASURED_AT, operator=models.ClaimOperator.SINCE, value=DEC5)])
    stored = rule.model_dump(mode="json")["evidence"]
    assert stored == [{"field": "MEASURED_AT", "operator": "SINCE", "value": DEC5.isoformat().replace("+00:00", "Z")}] or stored[0]["value"].startswith("2026-12-05")


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

from tests import rules as R  # noqa: E402


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
        models.DerivationRuleInput(source_node="ROI", key="k", evidence=[models.ClaimConditionInput.model_validate(R.of_kind("MEASUREMENT"))])
    with pytest.raises(ValidationError, match="BEFORE"):  # time operator on KIND
        models.ClaimConditionInput.model_validate(R.condition("KIND", "BEFORE", "SAMENESS"))
    with pytest.raises(ValidationError, match="WORD"):  # classification-covering rule needs WORD
        models.CategoryDefinitionInput.model_validate(R.definition(R.rule(R.by("peter"))))
    with pytest.raises(ValidationError, match="WORD"):  # non-classification rule may not carry WORD
        models.CategoryDefinitionInput.model_validate(R.definition(R.rule(R.word("X")), R.rule(R.word("Y"), R.of_kind("SAMENESS"), R.by("c"))))
    with pytest.raises(ValidationError, match="MEASURED_AT"):  # MEASURED_AT outside MEASUREMENT-only
        models.CategoryDefinitionInput.model_validate(R.definition(R.rule(R.word("X"), R.measured_since(DEC5))))


def test_a_measurement_only_rule_may_bound_observation_time() -> None:
    definition = models.CategoryDefinitionInput.model_validate(
        R.definition(
            R.rule(R.word("X")),
            R.rule(R.of_kind("MEASUREMENT"), R.via("scope"), R.measured_since(DEC5)),
        )
    )
    assert definition.rules[1].when[2].field == models.ClaimField.MEASURED_AT


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
