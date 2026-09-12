# RFC 0011 — KIND: rules say what kind of claim they govern

- **Status:** **Implemented.** A record, like its predecessors.
- **Question:** RFC 0009/0010 made a category's rule list the complete evidence
  rule, but the rules could not say *which kind of claim* they cover:
  classification and existence shared one who-and-when, and sameness (SAME_AS)
  was ungoverned entirely. The user: *"I guess we need something for entities
  to distinguish existence from sameness?"* — with the correction, verbatim,
  that settled the sameness model: *"No cross category sameness. It's just
  within a category but across terms."*
- **Recommendation (taken):** `KIND` as an ordinary condition field — no new
  syntax, no named blocks. A rule covers every kind its KIND conditions do not
  exclude; carving a kind out of a broad rule is ordinary `NOT_IN`.

## The extension

New `ClaimField.KIND`, taking `IS/IN/NOT_IN` over the `ClaimKind` enum:

| ClaimKind | Governs |
|---|---|
| CLASSIFICATION | which claims admit/label (whole rule, WORD included) — and an edge category's own link claims |
| EXISTENCE | whose standings count: node retraction/attest, an edge category's link standings |
| SAMENESS | whose SAME_AS may merge this category's nodes |
| EVIDENCE | whose INFORMS may route evidence under this category's nodes |
| MEASUREMENT | the default metric scope, when a property has no `rule.evidence` |

The motivating example — Peter decides what exists, only the curator may merge:

```jsonc
"rules": [
  {"when": [ {"field": "WORD", "operator": "IS", "value": "AIS"},
             {"field": "SUBJECT", "operator": "IS", "value": "peter"},
             {"field": "KIND", "operator": "NOT_IN", "value": ["SAMENESS"]} ]},
  {"when": [ {"field": "KIND", "operator": "IS", "value": "SAMENESS"},
             {"field": "SUBJECT", "operator": "IS", "value": "curator"} ]}
]
```

**Semantics.** One sentence on top of RFC 0010's three: *when folding claims of
kind K, a rule applies unless its KIND conditions exclude K.* Grants union, so
a broad rule keeps granting a kind until it is carved out with `NOT_IN` — which
is why the example's first rule excludes SAMENESS explicitly. **No applicable
rule for K means nothing counts for K** (strict grants): reachable only through
an explicit carve-out, never by accident. Old stored rules carry no KIND, cover
every kind, and keep their meaning — additive, no migration.

**Coverage is implemented once** — `rule_covers` in
`graph_engine/input_models.py`, called by both the write-time validator and the
compiler (`evidence/selector.py`), so they cannot disagree.
`trust_filter`/`trust_predicate` take a **required** `kind=` keyword; every
call site names its fold (`resolve_categories` EXISTENCE, link standings
EXISTENCE, INFORMS EVIDENCE, `metric_scope` MEASUREMENT,
`classification_filter` restricts itself to CLASSIFICATION-covering rules, and
the vocabulary (`asserted_as_keys`) reads WORDs from those rules only).

**Refusals extend the RFC 0010 matrix:** KIND values validated against the
enum; KIND in `unless` refused (spell it `NOT_IN` in `when`); KIND in
`rule.evidence` refused (a metric row has no kind to test); the WORD
requirement became conditional — a rule covering CLASSIFICATION must name
WORDs, one that does not must not; `MEASURED_AT` is now legal in a definition
rule **iff** the rule covers only MEASUREMENT (it bounds the category-default
metric scope's observation time — `test_rule_evidence_filters.py` pins it).

## Sameness: within a category, across words

The user's correction dissolved the design question this RFC's draft asked
(whose rules govern a merge between categories): **identity lives within a
kind.** An AIS and an AxonInitialSegment may be one individual — two words, one
category; an AIS and a Cell may not — a thing is one kind of thing, which the
one-category-per-node rule already enforces for drawing.

So the view-scoped fold returns — rule-driven this time, not RFC 0008's
selector walk:

- `evidence/identity.py::view_sameness_links(graph, refs)`: a SAME_AS claim
  counts in a view when **both endpoints resolve to the same category** there
  (`projector.resolve_categories`, batched) and the claim and its standing fold
  under that category's `KIND SAMENESS` trust. A primitive category trusts
  every merger — but still never unions across categories.
- `component_refs_for_view(graph, refs)`: the frontier walk over those links.
- Surfaced on **drawn** `Entity.component`/`sameAs` (the known-about loader is
  keyed `(graph_handle, ref)` again); claim-grain `Instance` reads and the
  `InstanceIdentity` cache stay organization grain — the cache remains the
  no-view answer. This partially reverses RFC 0009's panel rollback, for
  components and sameness only; labels and connections stay organization grain.

## Acceptance

`tests/api/test_category_trust.py::test_existence_and_sameness_are_distinct_rules`
is the motivating scenario end to end: Peter retracts, the curator merges, the
bot and Peter cannot merge, the org-grain fold still unions everything, and a
curator merge across AIS/Cell never unions in the view.
`tests/evidence/test_rule_compilation.py` pins the coverage math, the strict
uncovered-kind contradiction, and the refusal matrix.

## What would count as regressing this RFC

- A second coverage implementation beside `rule_covers`.
- A `trust_filter` call site passing the wrong kind for its table — the keyword
  is required precisely so none can be *omitted*; the fold table above is the
  reference for which is *right*.
- Cross-category sameness reappearing in any view-scoped read.
- "No applicable rule" silently widening to everyone for any kind.
