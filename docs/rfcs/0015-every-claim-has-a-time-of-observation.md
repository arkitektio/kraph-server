# RFC 0015 — Every claim has a time of observation

- **Status:** Implemented.
- **Question:** Only a `Metric` carried world time (`measured_at`). An
  `Instance` and a `Link` had `Assertion.asserted_at` and nothing else, so a
  natural event had no time of occurrence, a relation had no time it held,
  and `MEASURED_AT` was a metric-only rule field by necessity rather than by
  design. "Cells as they were before the treatment" could not be written as a
  rule. Should every claim carry the second clock?
- **What was done:** Yes. `observed_at` on `Instance`, `Link` and `Metric`
  (the metric column renamed from `measured_at` — one word for one axis),
  defaulting to the assertion's `asserted_at` so it is never null and a time
  rule is total. `Standing.at` keeps its name: it already meant "when the
  position took effect" and is the same axis. The rule field is `OBSERVED_AT`,
  legal on every claim kind and in `unless`. `KEY` is the one field left that
  only a metric row can answer.

## Changes

### The column

`evidence` migration 0011 adds `observed_at` (indexed, non-null) to `Instance`
and `Link`, backfilled from the assertion's `asserted_at` — under
`SET LOCAL kraph.allow_log_rewrite = 'on'`, since the append-only triggers
refuse an `UPDATE` otherwise — and renames `Metric.measured_at`. The default
is applied in two places so no writer can miss it: `writer.create_instance`
/ `create_link` / `record_metric` and `record_standing_for_ref` default to
`assertion.asserted_at`, and the model `save()` fills it for the
`create_for_organization` callers that bypass the writer.

What the column means depends on what the claim says, and that is the point
of one name: an entity was *seen* then, an event *happened* then, a relation
*held* then, a classification *applied* then, a value was *measured* then.
A duration is a metric; an event is a point in time, not an interval. The
dead `EventBaseInput.valid_from`/`valid_to` inputs are deleted; the drawn
`valid_from`/`valid_to` window (`projector._observation_window`) keeps its
name and folds the informing metrics' `observed_at`.

### The rule field

`ClaimField.MEASURED_AT` is `OBSERVED_AT`. It compiles wherever a rule
compiles — `when`, `unless`, `rule.evidence`, a rule covering any kind — with
`BEFORE`/`SINCE` as before. `_METRIC_ONLY_FIELDS` in both
`graph_engine/input_models.py` and `evidence/selector.py` is `{KEY}`.

Which column it reads is the queryset's business, not the rule's.
`selector._condition_q` takes `observed_at_column` beside
`asserted_at_column` (default `"observed_at"`), threaded through
`_rule_trust_q` and `trust_filter`. Over `Standing` rows the column is `at`:
`trust_predicate` passes it, so do the standing halves of `metric_scope`
and the projector's EXISTENCE fold. Everything else — classification links,
sameness links, INFORMS links, relation and participation links, metric
rows — reads `observed_at`.

So on one category:

```jsonc
{ "rules": [
  { "when": [ { "field": "WORD",        "operator": "IS",     "value": "Cell" },
              { "field": "OBSERVED_AT", "operator": "BEFORE", "value": "2026-06-01T00:00:00Z" } ] } ] }
```

admits the cells classified as seen before the treatment, keeps only the
retractions dated before it, draws only the relations that held before it and
folds only the values measured before it — no `KIND`, so one bound covers
every kind. An event category with `OBSERVED_AT SINCE` admits the events that
happened after the date and, since participations carry the event's time,
their participations too.

### Stored definitions

`core` migration 0020 rewrites `MEASURED_AT` to `OBSERVED_AT` in every stored
`Category.definition` and `property_definitions[*].rule.evidence`, walking
`when` and `unless`. This one is not optional: `_condition_q` returns no
predicate for a field it does not know, so an un-migrated condition would be
*dropped*, and a property that folded only last summer's measurements would
quietly fold all of them.

### Writes and reads

Every instance, link and metric input takes `observedAt: DateTime`
(`EntityInput`, the event inputs, `RelationInput` and its structure-relation
and measurement forms, `ClassificationInput`, `AssertParticipationInput`,
`AssertSameInstanceInput`, `MetricInput` — whose `timestamp`, an epoch in
milliseconds, is gone). Every `retract*`/`attest*` input takes `at: DateTime`,
the standing's time, which `writer.record_standing` accepted and no mutation
exposed. Silence means the assertion's time in both cases.

`Instance.observedAt`, `Link.observedAt`, `Metric.observedAt` (was
`measuredAt`), `Standing.at` as before. The `__measured_at` vertex property is
`__observed_at`. Ordering by world time — `state.py`'s first/last, the
writer's latest-metric lookups, the loaders — reads the renamed column.

## Tests

- `tests/evidence/test_observed_at.py`: the default (instance, link,
  standing, and a direct `create_for_organization`); an explicit value
  stored; the round-trips through `assertNaturalEventExists`,
  `assertRelationExists`, `assertMetricValue` and `retractEntity(at:)`; and
  four rule tests against a drawn graph — classification by seen-time,
  existence by `Standing.at`, a relation by held-time, an event and its
  participations by happened-time.
- `tests/test_migration_0020.py`: the walker over `when` and `unless`,
  idempotent; and a pre-0015 definition stored on a real category compiling
  to no time predicate before `rename` and to `observed_at__gte` after, in
  both the definition and the property's evidence.
- `tests/evidence/test_rule_compilation.py`: `OBSERVED_AT` accepted on a
  WORD rule, an EXISTENCE rule and a MEASUREMENT rule; `KEY` still refused
  outside measurement rules; the standing half of `metric_scope` skipping the
  key and reading time from `at`.
- `tests/schema/test_definitions_across_kinds.py`: `OBSERVED_AT` on a plain
  measurement rule accepted.
- `tests/rules.py`: `observed_before`/`observed_since`. `tests/claims.py`:
  `mint`/`classify`/`relate`/`participate`/`measure` take `observed_at=`,
  `retract_node` takes `at=`.
