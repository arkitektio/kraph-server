# RFC 0022 — A word's identity is immutable; its presentation is not evidence

**Status: Implemented** (2026-09-09).

## Question

`Term`, `StructureKind` and `MetricKind` live in the evidence app and are the
only rows there written in place — `createTerm`, `updateTerm`,
`updateStructureKind`, `updateMetricKind`. They are absent from the append-only
trigger set of migration 0005. Is the vocabulary evidence, and if not, what
about it may change?

## Argument

A claim uses a word; the word's *identity* is what the claim references. A
term is `(organization, kind, key)`, a structure kind
`(organization, identifier)`, a metric kind
`(organization, structure_kind, key, value_kind)`. Rewriting any of those
re-points every claim ever recorded under it at a different word, silently —
which is a rewrite of the log by other means. The only thing standing between
the log and that was a docstring on `updateTerm` saying "descriptive fields
only". `MetricKind.value_kind` is additionally part of `State`'s grain, so an
in-place edit orphaned folded statistics with nothing to notice.

How a word *presents* — `label`, `description`, `purl`, `color`, `image` — is
not evidence. No rule reads it, no claim references it, no fold depends on it.
It is the same kind of thing as a category's label or colour: presentation
around the model. Editing it in place, with no act recorded, is correct.

## Decision

- **Identity is immutable in the database.** Evidence migration 0016 attaches a
  `BEFORE UPDATE OF <identity columns>` trigger to the three tables, in the
  shape of 0005's log guard and honouring the same session-local hatch
  (`SET LOCAL kraph.allow_log_rewrite = 'on'`), so `manage.py redact` and a
  deliberate migration can still rewrite by name and nothing can by accident.
  Deletion stays as it was: a word nothing names may be retired; the `PROTECT`
  foreign keys refuse one that has been used.
- **Presentation stays mutable and unlogged.** The four mutations are unchanged.
  Where presentation *lives* — on the evidence row today — is left as is; the
  view already carries its own (`Category.label/color/image`), and moving the
  organization-wide default beside it is a product question, not a model one.

## Not decided here

Whether RFC 0002's three vocabularies are one table. This RFC only says what
may change on any of them.
