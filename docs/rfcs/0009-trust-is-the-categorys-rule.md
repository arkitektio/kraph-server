# RFC 0009 — Trust is the category's rule: there is no graph selector

- **Status:** **Implemented**, respelled by RFC 0010: the clause shape shown below was replaced by explicit (field, operator, value) rules with `when`/`unless`; the per-category semantics this RFC established are unchanged. The decision was taken in design discussion with
  nothing deployed depending on `Graph.selector`, so — like RFC 0005's AGE
  removal — there was no migration to weigh, only a design to keep honest.
- **Question:** Evidence scope was split across two mechanisms: per-entity-category
  `definition` clauses (RFC 0007, classification claims only) and a graph-global
  `Graph.selector` (one flat conjunction, applied uniformly to every claim kind
  per RFC 0008). The user's question, verbatim: *"I don't think we need selector
  at all — what counts for what is a property of the entity/rel/event
  definition. Why have it global for the graph?"* Is the selector redundant?
- **Recommendation (taken):** Yes. Everything a view draws belongs to a
  category, so trust can live where meaning already lives. A category's
  `definition` — the union of clauses — becomes the **complete** rule for its
  word; a derived property's `rule.evidence` is that property's own metric
  rule; `Graph.selector` is removed outright.

## What a category's clauses now govern

One clause = `asserted_as` words × `assertion_filter{subjects, app_ids,
action_names}` × `[since, as_of]`; clauses union (`any_of`). Two readings of
the same clauses, split on purpose (`evidence/selector.py`):

- **`classification_filter`** — the whole clause, words included: which claims
  *mean* this category. As before for CLASSIFIES; new for a relation or event
  category's own link claims (its edges draw from the claims its clauses
  admit — so a defined relation category can derive from other relation words,
  exactly as entity categories derive from other entity words).
- **`trust_filter`** — the who-and-when half, words ignored: whose claims and
  standings *count* for things already of this category. Applied to:
  - node **existence** standings — `resolve_categories` resolves the category
    *first*, then folds retraction under that category's clauses (the order
    flipped: it used to fold existence under the selector before resolving);
  - the **standings** of a relation/participation claim (a standing follows
    its target's rule — trusting Karl's relations means trusting his relation
    retractions);
  - **INFORMS routing** — who may attach evidence under a node is the node's
    category's question;
  - the **metrics** a property folds, *by default* — see below.

**`rule.evidence`** (`DerivationRuleInput.evidence`: assertion filter +
belief window + observation window) is the property's own metric rule.
**Replacement with a default, not intersection**: when present it *is* the
metric scope; when absent the category's clauses apply; a primitive category
folds everything. Intersection was rejected because classification annotators
and measurement producers are usually disjoint populations — ANDing them would
routinely produce an empty fold (`selector.metric_scope` records this).

A **primitive** category (no definition) is unscoped everywhere — any claim
naming its word counts, standings organization grain. The old behaviour, and
the default.

## What was removed

`Graph.selector` (column, `GraphSelectorInput`, the `selector` params on
`createGraph`/`updateGraph`, the `Graph.selector` field, and
`claim_filter`/`view_predicate`/`metric_filter` in `evidence/selector.py`).
Also, dead inputs the audit found: `DerivationRuleInput.conflict_policy` + the
`ConflictPolicy` enum (read by nothing), `ActionRuleInput.filter`
(`required_roles`/`required_scopes` matched against extractors that always
returned empty sets), and `SetSchemaPayload` (wired to no mutation). Stored
JSON is swept by `core/migrations/0016_sweep_dead_rule_keys.py` — the
`0005_strict_input_models` precedent: sweep, no read-side tolerance.

## What this deliberately rolls back from RFC 0008

- **The panel is organization grain again** (`evidence/panel.py`, keyed by ref
  alone in the loaders). It answers "what does the log say"; what a view counts
  is the drawing's business, folded per category where categories are applied.
  A per-category panel would have to pick one category per row of a
  cross-category component — a guess, not a fold.
- **Sameness is organization grain, always.** `component_refs_for_view` is
  deleted. A view cannot veto a merge claim: with no graph-level trust left and
  components spanning categories, there is no coherent per-category predicate
  for the walk. If a merge is wrong, retract the claim — for everyone.
  *(Amended by RFC 0011: the premise "components span categories" was wrong —
  sameness is within a category, across words — so a coherent per-category
  predicate exists after all, and the view-scoped fold returned, rule-driven,
  via `KIND SAMENESS`. The org-grain cache stays the no-view answer.)*

RFC 0008's core survives, relocated: `claims.standing(predicate=…)` is
unchanged, both halves (claim scope + standing fold) still apply everywhere a
rule is in scope — the predicate is just built from the category's clauses
(`trust_predicate`) instead of a selector.

## What this closes from earlier RFCs

- The **versioning gap** (RFC 0007 open item): `snapshot_definition` now
  includes `Category.definition`, so trust edits are schema versions and ride
  the existing `schema_hash` staleness machinery. The selector had neither
  history nor staleness detection; its successor has both for free.
- The **RFC 0008 regression** in `api/types.py::_contributing_metrics`
  (`contributingAssertions`/`supportingEvidence` applied no scoping) and the
  half-scoped `links_in_graph` (participation lists used view membership but
  org-grain standing) — both now fold under the category's rule, pinned by
  `tests/api/test_reads_fold_under_category_trust.py`.

## Costs, stated plainly

- "Trust Peter for everything" must be said once per category; there is no
  global shorthand and no quick `updateGraph` trust switch — every trust change
  is a definition change (which is also why it is now versioned and triggers
  the rebuild in the category mutations).
- One clause set governs classification *and* existence *and* edges for a
  category: "Peter classifies but only Karl retracts" is inexpressible. Chosen
  as a feature — one rule, one reader (`_clauses` stays the single walker).
- Whole-view time travel ("this graph as of Dec 5") is per-clause now; there is
  no single `as_of` knob cutting every category at once.

## Acceptance

`tests/api/test_category_trust.py` is the design discussion's example
definition executing end to end; `tests/projector/test_rule_evidence_filters.py`
pins the metric-rule semantics (including the gating fix: a rule filter narrows
even on an otherwise unscoped graph, where it would previously have been
silently inert); `tests/projector/test_projector_protocol.py`'s fences are
untouched.

## What would count as regressing this RFC

- A graph-level evidence scope growing back, under any name.
- A claim-kind read that folds under one category's clauses while its write
  lane (`_reproject_*`) folds under another's — the two lanes share the
  per-category dispatch (`categories_by_term`, including derived words) so they
  cannot disagree; keep it that way.
- `rule.evidence` widening beyond what its own filter says (it replaces the
  category default; it must never *add* to a fold the category already
  refused... note the deliberate asymmetry: replacement may admit assertions
  the clauses would not, for the disjoint-populations reason above — the
  regression is a *silent* widening, e.g. ignoring the filter).
- A second walker of the stored clause shape beside `_clauses`.
