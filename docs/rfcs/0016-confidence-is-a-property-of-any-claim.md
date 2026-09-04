# RFC 0016 — Confidence is a property of any claim

- **Status:** Implemented.
- **Question:** Only a `Metric` could say how sure its claimant was. A
  classifier that reports "Cell, 0.62" had nowhere to put the 0.62 — the
  `CLASSIFIES` link carried a word and a time and nothing else — so a view
  could not say "count the model's calls only when it was confident", and a
  retraction could not be weaker than a flat one. Should every claim carry
  the number?
- **What was done:** Yes. `confidence`, a nullable float in [0, 1], on
  `Instance`, `Link` and `Standing` beside `Metric`'s, refused outside the
  interval by input validation first and a check constraint on all four
  tables last. `CONFIDENCE` is a rule field with a third operator family,
  `AT_LEAST` (≥) and `BELOW` (<), legal on every kind, in `when`, in `unless`
  and in `rule.evidence`. A claim without a number satisfies neither operator
  — silence is not 1.0 and not 0.0 — so a bound never admits it and never
  subtracts it. `confidence_type` stays on `Metric`.

## Changes

### The column

`evidence.Instance`, `evidence.Link` and `evidence.Standing` gain
`confidence = FloatField(null=True, blank=True)`; `Metric.confidence`, which
already existed, is redeclared through the same `_confidence_field()` so the
four columns share one help text. A `CheckConstraint`
(`confidence IS NULL OR confidence BETWEEN 0 AND 1`, named
`{table}_confidence_in_unit_interval`) sits on each table: the API refuses an
out-of-range number at the input boundary, and a writer that bypasses the
API is refused by the database. Migration `evidence/0012`.

Null means "the claimant gave no number". It is not backfilled, because
nobody scored the existing claims, and it is not coerced on read, because
neither 1.0 ("certain") nor 0.0 ("worthless") is what silence says. The
consequence for rules follows below.

`confidence_type` — a method's own score, a p-value — is not spread. It
annotates a measurement *method* and has no meaning on a classification or a
retraction; a rule cannot name it either.

### The rule field

`ClaimField.CONFIDENCE`, and two operators that form a family of their own
beside identity (`IS`/`IN`/`NOT_IN`) and time (`BEFORE`/`SINCE`):
`ClaimOperator.AT_LEAST` (inclusive) and `ClaimOperator.BELOW` (exclusive).
Input validation refuses a non-numeric operator on `CONFIDENCE`, a numeric
operator on any other field, a boolean, a string, and a number outside
[0, 1]. The field is legal on every claim kind — there is nothing metric-only
about it — and in `rule.evidence`.

The selector compiles it to a bound on the claim's own column,
`Q(confidence__gte=v)` or `Q(confidence__lt=v)`, with **no `isnull` branch**.
SQL compares NULL to nothing, so:

- `CONFIDENCE AT_LEAST 0.9` in `when` admits claims scored 0.9 or higher and
  not a claim nobody scored.
- `CONFIDENCE BELOW 0.3` in `unless` subtracts claims scored under 0.3 and
  leaves a claim nobody scored alone.

That is the opposite of `NOT_IN` on the nullable `ACTION`, which does keep the
claims that have no action — and deliberately so. An action is a fact about
how a claim was made, and "not through *that* tool" plainly includes "through
no tool". A confidence is a statement the claimant chose to make, and a rule
that names a bound is asking about that statement; a claim that made none has
no answer, in either direction. The two idioms a rule author has are "only
the confident ones" (`when … AT_LEAST`) and "everything except what the
claimant itself doubted" (`unless … BELOW`), and they differ exactly in what
they do with silence. `docs/RULES.md` documents both.

The column is called `confidence` on `Standing` too, so unlike `OBSERVED_AT`
(RFC 0015, which routes to `at` over standings) the field needs no column
routing: `trust_filter`, `trust_predicate`, the standing halves of
`metric_scope` and the projector's EXISTENCE fold all see the same name.

### Writes and reads

Every instance, link, metric and participation input gains
`confidence: Float = null` beside `observedAt`; every `retract*`/`attest*`
input gains it beside `at`. The controller threads it through
`writer.create_instance`, `create_link`, `record_metric` and
`record_standing` unchanged — it does not default, unlike `observed_at`,
because there is nothing to default it to.

Reads: `confidence` on the `Instance`, `Link` and `Standing` GraphQL types
and on the `Edge` interface (`RetrievedEdge.confidence`, set by `from_link`).
The two `RetrievedEdge` accessors that used to answer `confidence` and
`confidence_type` from a `properties` dict nothing ever wrote — and so always
returned `None` — are gone; the interface's field reads the claim.

## Tests

`tests/evidence/test_confidence.py`: the column exists on all three new
tables and is null when unscored; the constraint refuses `-0.1` and `1.1` on
each; the input refuses the same and the error names the field; a
classification rule `AT_LEAST 0.9` draws the 0.95 classification and neither
the 0.5 one nor the silent one; `unless BELOW 0.3` subtracts the 0.1
classification and keeps the 0.5 and the silent one; an `EXISTENCE` rule
`AT_LEAST 0.9` lets a 0.99 retraction remove the vertex and a 0.2 one not; a
property's `rule.evidence` `AT_LEAST 0.8` folds the mean over the two
confident metrics and ignores the doubtful and the silent; a relation category
with the bound draws the 0.95 edge and not the 0.6 one; and `confidence`
round-trips through `assertEntityExists`, `assertRelationExists` (claim and
drawn edge) and `retractEntity` (`standings { confidence }`).
`tests/evidence/test_rule_compilation.py`: the operator family — `IS` and
`SINCE` on `CONFIDENCE` refused, `AT_LEAST` on `SUBJECT`/`OBSERVED_AT`
refused, `1.5`/`"0.9"`/`True` refused — and a three-rule definition compiling
to `confidence__gte`/`confidence__lt` with no `confidence__isnull`.
