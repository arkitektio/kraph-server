# Rules

This document describes how a graph decides which evidence it shows. It is the
reference for `Category.definition` and `rule.evidence`. The RFCs (0007 to
0014) record why the design is the way it is; this document only says what it
does. `EXAMPLE.md` shows one full schema and what it makes of the log.

## The idea

Everything anyone records is a claim in the organization's log: "this is an
AIS", "these two are the same cell", "this ROI measured 45.2", "this no longer
exists". Claims are never edited or deleted. A graph is a view over that log.

A graph does not filter the log directly. Its categories do. A category is the
graph's rule for one word, and the rule says which claims count for that word:
who may classify things under it, who may retract them, who may merge them,
whose measurements feed its properties. There is no graph-wide filter. If a
category has no rules, everything counts, which is the default.

## Where rules live

- `Category.definition` holds the rules for one category. Every family can
  carry one: entities, relations, events (natural and protocol), structure
  relations and measurements. It is set in the graph definition at
  `createGraph` (or `createProtocolEventCategory`), and changed with the
  matching `update*Category` mutation. Changing it rebuilds the drawing before
  the mutation returns where something is drawn; structure relations and
  measurements are not drawn, so their lists just read the new rules.
- `PropertyDefinition.rule.evidence` holds the rules for one derived property.
  It overrides the category's rules for that property's measurements only.

A category without a definition is called primitive. Any claim naming its word
counts, from anyone.

## The shape

```jsonc
"definition": {
  "rules": [
    {
      "when":   [ condition, ... ],
      "unless": [ { "when": [ condition, ... ] }, ... ]   // optional
    }
  ]
}
```

A condition is:

```jsonc
{ "field": "SUBJECT", "operator": "IS", "value": "peter" }
```

The logic:

- A claim counts if any rule matches it.
- A rule matches when every condition in `when` holds and no `unless` group
  applies.
- An `unless` group applies when every condition in it holds.

That is all of it. There is no other nesting.

## Fields

| Field | What it tests | Values |
|---|---|---|
| `WORD` | the term the claim names | strings, e.g. `"AIS"` |
| `SUBJECT` | who made the assertion | user ids |
| `APP` | which app it came through | app ids |
| `ACTION` | which action produced it | action ids; many claims have none |
| `KIND` | what the claim says (see below) | `CLASSIFICATION`, `EXISTENCE`, `SAMENESS`, `EVIDENCE`, `MEASUREMENT` |
| `ASSERTED_AT` | when the claim was made | datetime |
| `OBSERVED_AT` | when the world was as the claim says | datetime; every claim (RFC 0015) |
| `CONFIDENCE` | how sure the claimant was | number in [0, 1]; every claim, when the claimant gave one (RFC 0016) |
| `KEY` | the metric key | strings, e.g. `"vector_length"`; measurements only |

## Operators

| Operator | Meaning | Value |
|---|---|---|
| `IS` | equals | one string |
| `IN` | any of | list of strings |
| `NOT_IN` | none of | list of strings |
| `BEFORE` | at or before | datetime |
| `SINCE` | at or after | datetime |
| `AT_LEAST` | greater than or equal | number in [0, 1] |
| `BELOW` | less than | number in [0, 1] |

`BEFORE` and `SINCE` work on the time fields, `AT_LEAST` and `BELOW` on
`CONFIDENCE`, the rest on everything else. `NOT_IN` on `ACTION` keeps claims
that have no action at all; excluding an action does not exclude the people
who never used one.

Invalid combinations are rejected when the definition is written, with an error
that names the problem. Nothing is silently ignored.

## KIND: what a claim says

Claims about a category's things come in five kinds:

- `CLASSIFICATION`: "this is an AIS". Decides what the category admits.
- `EXISTENCE`: "this is gone" / "this is really there". Retractions and
  attestations.
- `SAMENESS`: "these two are one individual".
- `EVIDENCE`: "this ROI informs this cell". The links that route measurements
  to a node.
- `MEASUREMENT`: the measurements themselves, when a property has no
  `rule.evidence` of its own.

A rule without a `KIND` condition covers all five. A rule with one covers only
what the condition allows. Rules grant; they do not override each other. So if
one rule grants Peter everything and another grants the curator sameness, Peter
can still merge, because the first rule covers sameness too. To reserve merging
for the curator, take sameness away from Peter's rule:

```jsonc
"rules": [
  { "when": [ { "field": "WORD",    "operator": "IS",     "value": "AIS" },
              { "field": "SUBJECT", "operator": "IS",     "value": "peter" },
              { "field": "KIND",    "operator": "NOT_IN", "value": ["SAMENESS"] } ] },
  { "when": [ { "field": "KIND",    "operator": "IS",     "value": "SAMENESS" },
              { "field": "SUBJECT", "operator": "IS",     "value": "curator" } ] }
]
```

If no rule covers a kind, nothing counts for that kind in this category. You
can only get there by writing a `NOT_IN` in every rule, so it never happens by
accident.

Two constraints follow from what the kinds mean. A rule that covers
CLASSIFICATION must have a `WORD` condition, because classification is about
words; a rule that does not cover it must not have one, because retractions and
merges do not name words. `KEY` is only allowed in the `when` of a rule that
covers MEASUREMENT alone; other claims have no key, so it cannot appear in an
`unless` either. `OBSERVED_AT` used to be under the same restriction, as
`MEASURED_AT`; every claim carries an observation time now, so it goes anywhere
`ASSERTED_AT` goes.

With `KEY`, a category can trust one key from one producer and another key
from another, without one property per producer:

```jsonc
{ "when": [ { "field": "KIND", "operator": "IS", "value": "MEASUREMENT" },
            { "field": "APP",  "operator": "IS", "value": "segmenter-v3" },
            { "field": "KEY",  "operator": "IS", "value": "vector_length" } ] },
{ "when": [ { "field": "KIND", "operator": "IS", "value": "MEASUREMENT" },
            { "field": "APP",  "operator": "IS", "value": "area-tool" },
            { "field": "KEY",  "operator": "IS", "value": "area" } ] }
```

A property reading `vector_length` folds segmenter-v3's values only; one
reading `area` folds area-tool's only.

## Sameness is within a category

A sameness claim merges two observations into one individual. That only makes
sense inside one category: an AIS observed by Peter and an AxonInitialSegment
observed by Karl can be the same axon initial segment, because the category
defines both words as one kind of thing. An AIS and a Cell can never be merged
in a view, no matter who claims it. A thing is one kind of thing.

The organization-wide component (what you see without a graph in scope) still
unions every standing sameness claim. The per-view component applies the
category's rules and the within-category constraint. Since a node may hold
several categories of one view (below), two nodes merge when any category they
*share* trusts the claim.

### Saying two things are different

`assertDifferentInstance` records the opposite claim, `DIFFERENT_FROM`, one per
pair. It is read under the same rule as sameness — a rule that covers `SAMENESS`
covers both — and does exactly one thing in every fold: a standing, trusted
difference between a and b removes every *direct* sameness claim between a and
b. If a and b are still joined through a third instance (a~b, b~c, a≠c), they
stay one individual and the difference is reported under `conflicts` on the
node, for a person to settle by retracting one of the claims that disagree. The
fold never guesses whose other claim to drop.

## A node holds every category that admits it

A view draws a node under **every** category whose rule admits it — a defined
Pyramidal and a defined Excitatory both matching one cell is a cell with two
labels, not an ambiguity. Existence is judged per category: a retraction the
Pyramidal rule counts but the Excitatory rule does not leaves the node under
Excitatory alone. Its properties are the union of both categories' properties.
The one thing two categories may not do is define the **same** property key
differently — one vertex has one value per key — and a node caught between two
such categories is refused with a reason naming both. Identical definitions are
fine.

## Property rules

A derived property can carry its own rules for its measurements:

```jsonc
{ "key": "avg_length", "valueKind": "FLOAT", "derivation": "ROLLUP",
  "rule": {
    "sourceNode": "ROI", "key": "vector_length", "aggregation": "MEAN",
    "evidence": {
      "rules": [
        { "when": [ { "field": "APP", "operator": "IS", "value": "segmenter-v3" } ] },
        { "when": [ { "field": "APP",         "operator": "IS",     "value": "segmenter-v2" },
                    { "field": "OBSERVED_AT", "operator": "BEFORE", "value": "2026-06-01T00:00:00Z" } ],
          "unless": [ { "when": [ { "field": "ACTION", "operator": "IS", "value": "old-pipeline" } ] } ] }
      ]
    }
  }
}
```

`evidence` is a rule list with the same logic as a definition: a measurement
counts if any rule matches; a rule matches when every `when` condition holds
and no `unless` group applies. The one above reads "segmenter-v3, or
segmenter-v2 for anything measured before June that did not come through the
old pipeline".

Two differences from a definition, both from what a measurement is. `WORD`
and `KIND` are not allowed: a measurement names no word (the key is `KEY`)
and has no kind. `KEY` is allowed everywhere, `unless` included. `rule.key` still says which key the property reads; a `KEY`
condition says which rows the rule admits, and the two combine.

When `evidence` is present, it replaces the category's rules for this
property's measurements. When it is absent, the category's MEASUREMENT rules
apply, and for a primitive category everything does. It replaces rather than
intersects because the people who classify things and the pipelines that
measure them are usually different, and requiring both would usually leave
nothing.

## Time

`ASSERTED_AT` is when someone said it. `OBSERVED_AT` is when the world was
as they say — every claim carries one, and it is the assertion's time unless
the claimant gave another (RFC 0015). A correction made in March about a
measurement taken in June differs from the original only in `ASSERTED_AT`.
"The category as we believed it on March 3rd" is `ASSERTED_AT BEFORE
2026-03-03`, per rule. "Cells as they were before the treatment" is
`OBSERVED_AT BEFORE <treatment>` on the category — and with no `KIND` that
one bound governs every claim about a cell: a classification by when the cell
was seen, a death by when it took effect (a standing's own `at`), a relation
by when it held, an event by when it happened. There is no graph-wide time
cursor; if you want the whole view frozen, put the bound in every category's
rules.

Which column answers `OBSERVED_AT` depends on what the rule is being asked
about: `observed_at` on an instance, a link or a metric; `at` on a standing.
The selector does that routing (`trust_predicate` and the standing halves pass
`observed_at_column="at"`); a rule never names a column.

## Confidence

Any claim may carry a number from 0 to 1 saying how sure the claimant was — an
instance, a link, a metric, a standing (RFC 0016). It is optional, and an
absent number is **not** 1.0 and **not** 0.0: it is silence. A `CONFIDENCE`
condition compares the claim's own number, so a claim without one satisfies
no `CONFIDENCE` condition at all, in either direction:

- `CONFIDENCE AT_LEAST 0.9` in `when` admits only claims scored 0.9 or higher.
  A claim nobody scored is not admitted.
- `CONFIDENCE BELOW 0.3` in `unless` subtracts the claims scored under 0.3. A
  claim nobody scored is not subtracted — it stays.

So "only the confident model calls" is the first idiom, and "everything except
what the model itself doubted" is the second. Pick the one that says what you
mean about silence; the rule will not guess.

```jsonc
{ "rules": [
  { "when": [ { "field": "WORD",       "operator": "IS",       "value": "Cell" },
              { "field": "APP",        "operator": "IS",       "value": "classifier-v2" },
              { "field": "CONFIDENCE", "operator": "AT_LEAST", "value": 0.9 } ] },
  { "when": [ { "field": "WORD",       "operator": "IS",       "value": "Cell" },
              { "field": "SUBJECT",    "operator": "IS",       "value": "peter" } ] } ] }
```

The classifier's calls count when it was at least 90% sure; Peter's count
whether or not he gave a number. With no `KIND`, the first rule's bound also
governs the classifier's retractions and its measurements under this category;
the field works on every kind and in `rule.evidence`. `Metric.confidenceType`
— what sort of number a measurement's confidence is — stays on metrics only;
it annotates a measurement method.

## Versioning and rebuilds

Definitions are part of the schema. Editing one creates a schema version and
rebuilds the graph's drawing before the mutation returns. Editing a
`rule.evidence` moves the schema hash; `manage.py rematerialize --stale` picks
it up.

## What is settled and what is not

Settled and implemented:

- the rule shape (`rules` / `when` / `unless`, conditions as field, operator,
  value)
- all fields and operators above, including `KIND` with its five values
- per-view existence, edge trust, evidence routing and measurement scope
- definitions on all five category families (entities, relations, events,
  structure relations, measurements)
- per-view, within-category sameness, and its negative (`DIFFERENT_FROM`)
- a node under every category that admits it
- `rule.evidence` on properties, as a rule list with `unless`
- `KEY` in measurement rules
- `CONFIDENCE` on every claim, with `AT_LEAST`/`BELOW`

Decided against:

- A whole-graph "as of" cursor. Freezing a view at a date is an
  `ASSERTED_AT BEFORE` condition in every category's rules; a graph-wide one
  would be the graph-level scope RFC 0009 removed.

Separate from all of this:

- Who may *edit* definitions is separate from all of this and fixed: the
  graph's owner, an organization admin, or a superuser (RFC 0013). Everyone in
  the organization can still read and record claims.
