# RFC 0007 — A definition is a union of clauses

- **Status:** **Implemented.** A record, like 0004–0006: it exists so the next
  person knows what the clause language can and cannot say, why it is one level
  deep, and which asymmetry was looked at and deliberately left.
- **Question:** A big part of what these graphs are *for* is statements like
  "in this view, 'Cell' means what Peter called 'Cell' and what Karl called
  'StemCell' after the 5th of December" — several people's words, subsumed
  under one label. `Category.definition` could not say it: the predicate was
  one flat conjunction (one `asserted_as` list, one `assertion_filter`, one
  `as_of`, applied uniformly), so the closest flat encoding was a
  cross-product that also admitted **Karl's Cells** and **Peter's StemCells**;
  there was no lower time bound anywhere ("after Dec 5" was inexpressible);
  and it could not be faked with two sibling categories, because
  `resolve_categories` refuses a node matching more than one defined category
  — and subsumption needs one label anyway. On top of that, neither
  `Category.definition` nor `Graph.selector` had any GraphQL surface: both
  were hand-written JSON set from Python, with unknown keys silently ignored.
- **Recommendation (taken):** Make a definition a **union of clauses** —
  `{"any_of": [{asserted_as, assertion_filter, as_of, since}, …]}` — where each
  clause binds its own words, annotators and time bounds, and the definition
  matches a claim iff any clause does. Add `since` (`asserted_at` lower bound)
  beside `as_of` in all three sibling filters. Give both predicates a
  structured, validated GraphQL surface.

## The language

A **clause** is the old flat definition plus `since`. The flat form stays valid
and means one clause; internally every reader consumes `_clauses(definition)`
(`evidence/selector.py`), so the predicate (`classification_filter`) and the
vocabulary (`asserted_as_keys` — the choke point feeding `CategoryAssertedTerm`,
membership, `refs_admitted_by`, and `backfill_category`'s rebuild decision)
cannot walk the shape differently. That single-reader rule is the invariant:
the historical bug class here is a definition that matches claims the graph
cannot see.

Rules, and where each is enforced:

- **Flat keys and `any_of` are mutually exclusive** — refused by
  `CategoryDefinitionInput` at every write path. The read side stays
  permissive (definitions are JSON and rebuilds must not crash on old rows):
  there, `any_of` wins whole, so the failure mode of a hand-written hybrid is
  a dead flat half, never divergence.
- **One level only.** A clause has no `any_of` field — nesting is refused
  structurally, not by a validator someone can forget. Unions of conjunctions
  are expressive enough for every scenario anyone has stated; arbitrary
  boolean nesting would make `asserted_as_keys` and the admitted-refs
  narrowing genuinely hard to keep honest.
- **Every clause names `asserted_as`** at the write. The read side tolerates a
  word-less clause as "matches every word the graph sees", and
  `refs_admitted_by` detects that case
  (`selector.definition_matches_every_word`) and skips its candidate
  narrowing rather than silently dropping what the clause admits.
- **The OR-over-empty-Q footgun**, written down because it will bite again:
  Django collapses `Q() | Q(x)` to `Q(x)`, and a fold over zero clauses
  returns the match-everything `Q()`. So `classification_filter` returns an
  explicit contradiction for `any_of: []` (matches *nothing*) and an explicit
  `Q()` when any clause is unconstrained (matches *everything*) — both cases
  spelled out rather than left to the collapse.

`since` also landed top-level in `claim_filter` (whose existence claims a graph
counts) and `metric_filter` (denormalized column), keeping the three siblings
the same shape. `Graph.selector` gets no `any_of` — nothing stated needs it.

## The API surface

`CategoryDefinitionInput` / `CategoryDefinitionClauseInput` /
`AssertionFilterInput` / `GraphSelectorInput` (StrictModel — an unknown key is
now an error at the mutation, where the raw JSON used to swallow it).
Entity-first, deliberately: `EntityDefinitionInput` carries `definition`, which
also means **a schema handed to `materialize` can declare defined categories**;
`UpdateEntityCategoryInput` adds `definition` + `clearDefinition` (exclusive).
The natural/protocol event inputs can grow the same one field later without
redesign. Read-back is structured (`Category.definition`, `Graph.selector`),
null meaning primitive / everything.

Changing a meaning changes membership, so the update paths reproject before
returning: `updateEntityCategory` with a changed definition rebuilds the graph
(a definition can move a vertex between labels, and only rebuild moves a label
honestly — the same reasoning as `backfill_category`); `updateGraph` with a
changed selector rebuilds too, because the drawing standing at that moment was
folded under the old scope. Synchronous and O(graph): the accepted limit every
schema edit already has.

## Retraction became symmetric with attestation

Found while building the existence tests: `retract_node` blanket-erased the
node from **every** graph, while its own comment promised "a view that does not
count this subject still draws the node" — the write path disagreed with the
very next rebuild. It now calls `projector.reproject_node` per graph, exactly
as `attest_node` always did: the fold under each graph's `claim_filter` decides,
so a scoped view keeps its node at write time, not only after a reproject.

## Deliberately left

- **Link standing is organization-wide.** Instance existence folds per view
  (`resolve_categories` → `retracted_ids` → `claim_filter`), but every other
  claim kind folds through `CurrentStanding`, which is a selector-less cache —
  so a *link* retracted by somebody a view does not count still loses its edge
  everywhere. Changing that means a per-view standing fold (or folding
  standings at projection time per graph), a real design with real cost, and
  nothing asked for it yet. `tests/api/test_graph_selector.py::
  test_link_retraction_is_organization_wide` pins the behavior as documented.
- **`versioning.snapshot_definition` still omits the predicate** from schema
  versions — a pre-existing Tier-2 gap its own comments acknowledge; a
  definition change is reprojected but not versioned.
- **Python-set definitions stay unvalidated.** Fixtures and shell writes keep
  today's permissiveness; the validation lives at the mutation, and
  `CategoryDefinitionInput.model_validate` is there for any tool that wants
  the check.

## What would count as regressing this RFC

- A second reader of the definition shape that does not go through
  `_clauses`/`asserted_as_keys`.
- A validator on the read side — a rebuild that crashes on a historic
  definition is worse than a dead clause.
- Nested `any_of`, or a clause accepted without `asserted_as` at a write path.
- A retraction path that erases without folding under the graph's selector.
