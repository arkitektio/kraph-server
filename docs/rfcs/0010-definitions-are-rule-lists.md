# RFC 0010 — Definitions are rule lists: (field, operator, value), `when`, `unless`

- **Status:** **Implemented.** A record, like its predecessors.
- **Question:** RFC 0009 made a category's `definition` the complete evidence
  rule but kept RFC 0007's clause shape. The user rejected it, verbatim: *"I
  don't like this composed category definition input, with too and children
  filters. It should be more clear, with operators — like a rule system. It's
  not a formal system I like."* What replaces it?
- **Recommendation (taken):** An explicit rule system in the platform's one
  existing formal language — the `(field, operator, value)` triple with an
  operator enum that `TableQueryPlan`'s `WhereClauseInput` already uses.
  Completely breaking: the clause shape is neither read nor converted
  (`core/migrations/0017` clears what stored it).

## The shape

```
definition: { rules: [ { when: [condition, …], unless: [{when: [condition, …]}, …]? }, … ] }
condition:  { field: WORD|SUBJECT|APP|ACTION|ASSERTED_AT|MEASURED_AT,
              operator: IS|IN|NOT_IN|BEFORE|SINCE,
              value: string | [string] | datetime }
```

**Semantics — three sentences, all visible in the structure:** a claim counts if
any rule matches; a rule matches when all its `when` conditions hold and no
`unless` group does; a group holds when all its conditions do. A property's
`rule.evidence` is a bare condition list (all must hold) in the same vocabulary,
plus `MEASURED_AT`, which only a measurement has.

## What the old shape got wrong, and where each sin went

| Clause-shape sin | Now |
|---|---|
| Two spellings (flat XOR `any_of`) | one shape; `min_length=1` everywhere |
| Invisible logic (AND-within / OR-across implied) | `rules` = any, `when` = all, in the syntax |
| Nested `assertion_filter` with three parallel lists | flat conditions with named fields |
| Wordless clause silently meant *every word* | every definition rule must carry a `WORD` condition — unspellable |
| `any_of: []` silently meant *nothing* | `rules: []` refused at the write |
| "Everyone except the bot" inexpressible | `NOT_IN`; and compound exceptions via `unless` groups |

Write-time refusals (each named, never silent): unknown field/operator combos
(`IS/IN/NOT_IN` on identity fields, `BEFORE/SINCE` on time fields only), value
typing per operator, `WORD` in `unless` or in `rule.evidence`, `MEASURED_AT`
anywhere in a definition, `WORD NOT_IN` (a definition names its words, it does
not exclude them).

## Compilation notes (evidence/selector.py — still the single home)

- `_rules` replaced `_clauses` as **the** single reader of the stored shape;
  `_condition_q` is the one condition→predicate map, shared by
  `classification_filter` (whole rule, WORD included) and `trust_filter`
  (who-and-when, WORD skipped) — the two readings RFC 0009 established, intact.
- `NOT_IN` compiles to `NOT (col IN …)` **plus `OR col IS NULL` for the
  nullable `ACTION` column**: SQL's NOT IN swallows NULL rows, and "everyone
  except the bot" must not silently drop a human claim that carries no action.
  Pinned by `tests/evidence/test_rule_compilation.py`.
- A rule whose `when` is only WORD conditions places no *trust* restriction
  (vocabulary alone restricts nobody) — the `CurrentStanding` fast path stays.
- `definition_matches_every_word` was deleted: the case it tolerated is
  unspellable, and its `refs_admitted_by` branch went with it.

## Breaking, by sanction

The user's answer to the migration question was "this can be completely
breaking": `core/migrations/0017` clears any non-`rules`-shaped stored
definition to `{}` (primitive) and drops old-shape `rule.evidence`, logging each
by graph/category — no converter, no dual reader. `AssertionFilterInput`,
`CategoryDefinitionClauseInput` and `RuleEvidenceInput` are gone from inputs,
read-back types and the SDL; `ClaimCondition(Group)/ClaimRule` replace them.
Tests build the shape through `tests/rules.py` — one dict serves GraphQL
variables, pydantic validation and stored JSON, because the field names are
identical in all three.

## Growth path, named not built

`rule.evidence` as a plain conjunction can later become a rule list with
`unless` exactly like the definition; a `WORD`-like field over metric *keys*
would slot into the same condition language. *(Exercised: RFC 0011 added
`KIND` as exactly such a field.)* Anything beyond that (nested
combinators) was considered and declined — the user chose bounded `unless`
groups over a general expression tree.
