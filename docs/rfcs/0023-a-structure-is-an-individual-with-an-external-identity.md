# RFC 0023 — A structure is an individual with an external identity

**Status: Implemented** (2026-09-09).

## Question

`Structure` was minted by `get_or_create` on `(identifier, object)` and the
second claimant's assertion was dropped — the shape of a vocabulary row, not a
claim. The API offered `assertStructureExists`, `retractStructure` and
`attestStructure` as if it were a claim, and `retract_structure` wrote a
standing that nothing downstream read: the metrics of a retracted datum kept
feeding every derived value it informed, and `State.recompute` read INFORMS
links unfolded. Is a structure a claim or an identifier?

## Argument

Neither, as posed. An ROI, an image, a file is a *thing in the world*, like a
cell — an individual. What differs is where its identity comes from: a cell's
is minted per observation and joined by sameness claims; a datum's is given by
the system that produced it. So observing it twice is two claims about one
individual, not two individuals. Its existence has a standing, like any
individual's; the claims *about* it — INFORMS, metrics, comments — are ordinary
claims that stay on the record whatever its standing, but count only while it
stands, exactly as a relation between two entities is drawn only while both
stand.

## Decision

- **The row stays one per external identity.** `ensure_structure` keeps its
  `get_or_create`; a *reference* (a metric, a comment, supporting evidence)
  records no new existence claim, as a relation claim does not re-assert its
  endpoints. An *explicit* second `assertStructureExists` is agreement and is
  recorded as a `Standing(stands=True)` under the second act — countable, and
  visible through `standings(id:)`.
- **Every claim has the two columns.** `observed_at` (RFC 0015) and
  `confidence` (RFC 0016) on `Structure` (evidence migration 0017), accepted by
  `assertStructureExists`, read back on `Structure`. `OBSERVED_AT` and
  `CONFIDENCE` rules are now total over claim kinds that a rule can name.
- **The folds honour the datum's standing.** `state._structures_informing`
  folds INFORMS standing and structure standing; `_structure_ids_informing` and
  `active_metrics_for_structures` exclude retracted datums;
  `retract_structure` / `attest_structure` refold every `State` row the datum
  feeds (`state.refold`) and redraw the nodes it informs. Retracting an
  INFORMS link refolds before it redraws.
- **A measurement is one claim written as two rows.** Retracting or attesting a
  MEASUREMENT link does the same to its sibling INFORMS link under the same
  act, and `attest_link` corrects the projection through the same per-kind
  dispatch a retraction uses.
- **Names say what the acts are.** `updateStructure` → `recordMetrics`,
  `linkStructureToEntity` → `assertInforms`; `ensureStructure`, which was
  `assertStructureExists` under another name, is gone.

## Rejected: a structure as a claim minted per observation

One `Instance`-shaped row per observation with implicit sameness by external
key would make the FK from `Metric` and the INFORMS `source_ref` address a
representative that a fold could reassign, and every path that relies on
`ensure_structure`'s idempotency — `create_measurement`, `record_metric`,
`comment_on_structure`, `_materialize_supporting_evidence` — would need a
fold before it could address anything. Nothing is gained: the external key
already says which observations are one thing.
