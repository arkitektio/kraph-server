# RFC 0024 — Identity is the view's, and every fold is a fold under some view

**Status: Implemented** in part — see *Deferred* (2026-09-09).

## Question

The evidence app holds three folds — `CurrentStanding`, `InstanceIdentity`,
`State` — under the rule "no graph FK may enter `evidence/`", and answers
organization-grain questions from them. Sameness, meanwhile, was folded per
*category* (RFC 0011: "within a category, across words", under each
category's `KIND SAMENESS` trust), while a node is drawn under every category
that admits it (RFC 0019). Who owns identity, and what are those folds?

## Argument

A view is one function of the log. Within it there is exactly one answer to
"how many things are here". Folding sameness per category gave one view two:
instance *a* in one individual under `Cell` and another under `StemCell`, and
`view_components` had to pick. Trust about *what a word means* and *whose
existence claims count* is naturally a category's — it is about the word.
Trust about *whether two observations are one thing* is not about any word;
it is about the view's world. So it belongs to the view.

The three organization-grain folds are `view(log)` for the view whose trust
is "everyone". That is a fine view to have, but it is a view: its folds are
projections, not evidence, and its answers should be named as such.

## Decision

- **`Graph.sameness_rule`** (core migration 0024): a rule list in the
  definition's shape minus WORD, KIND and KEY; empty means everyone.
  `identity._trusted_in_view` folds a claim when both endpoints are nodes of
  the view and the claim and its standing pass the view's rule — whatever
  categories the endpoints are drawn under. `samenessRule` on `createGraph` /
  `updateGraph`, read back on `Graph`; a change emits a schema version (the
  rule is in `snapshot_definition`) and rebuilds the projection.
- **A category may not name `KIND SAMENESS`.** `CategoryDefinitionInput`
  refuses it, naming the view's rule; the migration strips it from stored
  definitions losslessly (a rule that covered SAMENESS alone governed nothing
  a category still governs, and is dropped).
- **The standing cache is total.** `CurrentStanding` caches instances too
  (`CACHED_TARGETS` gains `"node"`): the trust-everyone answer to whether a
  node exists is as well-defined as for a link. What a view says is unchanged —
  `resolve_categories` folds existence per category from the log.

## Deferred

The three folds still live in `evidence/` and are keyed by organization,
not by a `Graph` row. Naming the trust-everyone view as a real `Graph`
(`is_default`, one per organization, a primitive category per word kept in
step by a signal on `Term`) and relocating the folds to `graph_engine` keyed
by it would finish the layering; it changes no answer today, costs three data
migrations plus a projection into one more view on every write, and is
recorded here as the remaining step rather than done in this round. Until
then, an organization-grain field on the API (`Node.labels`,
`Node.connections`, `Instance.*`) is the trust-everyone fold, and its
description says so (RFC 0025).
