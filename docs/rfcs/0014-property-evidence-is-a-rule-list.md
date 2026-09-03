# RFC 0014 — Property evidence is a rule list, and a rule can name the metric key

- **Status:** Implemented.
- **Question:** `EXAMPLE.md` listed three things the rule language could not
  express: a property's `rule.evidence` was a flat list of conditions (no
  unions, no `unless`); no condition could test the metric key; and there was
  no whole-graph "as of" cursor. Which of these get built?
- **What was done:** The first two. `rule.evidence` is now the same
  `{rules: [{when, unless}]}` shape a definition uses, and `KEY` is a
  condition field wherever a rule is about measurements. The third was put
  to the user and declined ("Skip it"): a graph-wide cursor would be the
  graph-level scope RFC 0009 removed, under a different name. Freezing a view
  at a date stays an `ASSERTED_AT BEFORE` condition in each category's rules.

## Changes

### `rule.evidence` is a rule list

`DerivationRuleInput.evidence` was `List[ClaimConditionInput]`, all of which
had to hold. It is now `MetricEvidenceInput { rules: [ClaimRuleInput] }`
(`graph_engine/input_models.py`), with the definition's logic: any rule
admits, every `when` condition of a rule must hold, `unless` groups subtract.
The differences from a definition follow from what a metric row is:

- No `WORD` and no `KIND`, anywhere. A metric names no word (which key it is
  under is `KEY`, below) and a metric row has no kind to test.
- `KEY` and `MEASURED_AT` are allowed in `when` and in `unless`. A definition
  refuses them in `unless` because a claim has no key or observation time; a
  metric row has both.

So "segmenter-v3, or segmenter-v2 for anything measured before June" is two
rules on one property, and "everyone but the bot, unless it came through the
old pipeline" is one rule with an `unless`.

The compiler (`evidence/selector.py`): `rule_metric_filter` ORs
`_rule_trust_q(..., include_metric_fields=True)` over the rules;
`metric_scope`'s standing half ORs the same rules with the metric-only fields
skipped, and is `None` when any rule then constrains nobody, the same edge
`trust_predicate` takes. `_rule_trust_q`'s keyword was `include_measured_at`
and is `include_metric_fields`, over `_METRIC_ONLY_FIELDS = {MEASURED_AT,
KEY}`.

Stored shape changes. Migration `core/0019` converts each stored list `[c, …]`
to `{rules: [{when: [c, …]}]}`, which reads the same. The list form is not
accepted as input any more.

### `KEY`

`ClaimField.KEY` compiles to `Metric.key`. Identity-style: `IS`, `IN`,
`NOT_IN`, string values. Legal in `rule.evidence` (anywhere) and in the
`when` of a definition rule that covers MEASUREMENT alone; refused, with an
error naming the field, on a rule covering any other kind or in a
definition's `unless`, exactly where `MEASURED_AT` is refused.

With it, a category can say which key it trusts from which producer without
one property per producer:

```jsonc
{ "when": [ { "field": "KIND", "operator": "IS", "value": "MEASUREMENT" },
            { "field": "APP",  "operator": "IS", "value": "segmenter-v3" },
            { "field": "KEY",  "operator": "IS", "value": "vector_length" } ] },
{ "when": [ { "field": "KIND", "operator": "IS", "value": "MEASUREMENT" },
            { "field": "APP",  "operator": "IS", "value": "area-tool" },
            { "field": "KEY",  "operator": "IS", "value": "area" } ] }
```

A property reading `vector_length` then folds segmenter-v3's values only; one
reading `area` folds area-tool's only. `rule.key` still says which key a
property reads; `KEY` says which rows a rule admits. They compose by AND.

### GraphQL

`MetricEvidenceInput` / `MetricEvidence` (`api/inputs.py`, `api/types.py`),
`DerivationRuleInput.evidence: MetricEvidenceInput`, `ClaimField.KEY`. The
diff in `test.graphql` is those and the descriptions.

## Tests

- `tests/evidence/test_rule_compilation.py`, block "property evidence is a
  rule list, KEY (RFC 0014)": the shape, the refusals (flat list, WORD, KIND,
  KEY BEFORE, KEY on a classification rule, KEY in a definition `unless`), the
  compiled union with `unless`, the standing half skipping the metric-only
  fields, KEY in a MEASUREMENT-only definition rule compiling on the metric
  side only.
- `tests/projector/test_rule_evidence_filters.py`: `test_rule_evidence_rules_union`,
  `test_rule_evidence_unless_subtracts`, `test_key_in_rule_evidence`,
  `test_key_in_a_measurement_only_category_rule` — each folds real metrics
  through a drawn graph.
- `tests/schema/test_definitions_across_kinds.py`: the
  `entity-measurement-rules-name-keys` schema and two refusals.
- `tests/test_migration_0019.py`: the converter, and a flat list stored on a
  real category parsing through `defined_properties` after `convert`.
- `tests/rules.py` gained `key`, `not_key`, `evidence`.
