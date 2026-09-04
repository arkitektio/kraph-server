# RFC 0017 — A claim can cite the claims it came from

- **Status:** Implemented.
- **Question:** Nothing in the log said *where a claim came from*. A
  classifier that calls a node "Cell" because a ROI measured 40 µm² had no
  way to name that measurement; `supersedeMetricValue` tied the corrected
  value to the one it replaced only by their sharing an assertion id, which a
  reader had to know to look for; a relation concluded from two other claims
  could not point at them. How should a claim cite what it derives from?
- **What was done:** One more link kind. `Link.Kind.DERIVED_FROM` runs from
  the new claim (`source_ref`) to the claim it came from (`target_ref`), and
  either end may be any claim row — an `Instance`, a `Link`, a `Metric` or a
  `Structure`. It is written under the **same assertion** as the claim that
  cites, through `derivedFrom` on every claim-making input, and
  `supersedeMetricValue` writes one from the new value to the old on its own.
  It is never drawn, no view folds it, and it is read back as `derivedFrom`
  and `derivations` on the four claim types.

## Changes

### The kind

`DERIVED_FROM` is the ninth member of `Link.Kind`. No new column: the two ref
columns stay opaque uuids and `kind` stays the only thing that says what they
name, as `evidence/models.py` has always said. What is new is that this is
the first kind open at *both* ends across all four claim tables —
`_ENDPOINT_TABLES[DERIVED_FROM] = ("claim", "claim")` — where every other
kind fixes at least one end. The id namespaces are disjoint uuid4 keys, so a
ref names at most one row and `_resolve_any_claim` probes the four tables in
turn, through the per-operation loaders, at most four queries for a page of
citations.

Direction: from the derived claim to what it derives from, so that
`derivedFrom` is a query on `source_ref` and `derivations` — what was
concluded from this — on `target_ref`. Both are indexed already.

### One act

A citation is not a separate statement. "This is a Cell, because of that
measurement" is one thing somebody said, and recording the "because" as a
second assertion would fragment it exactly the way the batch mutations exist
to avoid. So the controller resolves `derivedFrom` **before** the transaction
— `_resolve_citations`, which refuses a ref naming no claim in the caller's
organization, before anything is written — and writes the links inside it,
under the claim's own assertion, through `_cite`. A refused citation means no
assertion and no claim; the error names `derivedFrom`.

The tenant check matters more here than elsewhere: a ref is a bare uuid, so
without it a citation would cross the organization boundary silently and the
foreign claim would appear, resolved, under `derivedFrom`.

Every claim-making input carries the field — `EntityInput`, `EventInput`,
`ParticipantInput` (in an event and in `assertParticipations`),
`AssertParticipationInput`, `ClassificationInput`, `AssertSameInstanceInput`,
`StructureInput`, `RelationInput` (relation, structure relation, measurement)
and `MetricInput` (metric value, structure metric, supersede). Where one input
produces several links — the pair links of `assertSameInstance`, the
per-participant links of a batch — each link cites, because each is what the
caller concluded.

`supersedeMetricValue` cites without being asked: `update_metric` passes the
superseded metric's id to `_record_metric` as `also_derived_from`, so the new
value's `derivedFrom` names the old one and the old one's `derivations` names
the new, under the corrective assertion. The caller's own `derivedFrom` is
kept beside it.

### Organization grain, never drawn

Lineage relates claims, not the things the claims are about. Its ends may be
a metric, a structure or another link, none of which is a vertex, so there is
nothing to draw and `Projector` is untouched. No `ClaimKind` is added and
`rule_covers` is untouched, because nothing view-scoped reads lineage:
whether a citation stands is the organization-wide `CurrentStanding` answer,
the same fold a retracted metric uses. `retractLinks` accepts the link like
any other, `_reproject_claim` falls through for it (retracting a citation
changes nothing any view shows), and the panel's positively-enumerated
`_CONNECTION_KINDS` leaves it out — lineage has fields of its own rather than
appearing as a "connection".

### Reads

`derivedFrom: [Link!]!` and `derivations: [Link!]!` on `Instance`, `Link`,
`Metric` and `Structure`, standing citations only, oldest first, through two
grouped loaders (`lineage_by_source`, `lineage_by_target`). They return the
**link** rather than the cited claim so that the citation itself is
addressable — its id goes to `retractLinks`, its `assertion` says who cited —
and the cited claim is one hop away through `Link.source`/`Link.target`,
which now resolve a `DERIVED_FROM` end through `_resolve_any_claim`.
`ClaimEndpoint` gains `Metric` for that, since a claim may come from a
measurement. `Derivation implements Edge` is the subtype `retractLinks`
returns for one, with `ClaimEndpoint` ends.

## Tests

`tests/api/test_lineage.py`: an entity citing a metric reads back as a
`DERIVED_FROM` link whose target is the `Metric`, under the entity's own
assertion, and the metric's `derivations` names the instance; a relation
cites a metric and an instance at once, an instance cites the relation link,
and `Link.source`/`target` resolve every shape; `supersedeMetricValue` cites
the replaced value under the corrective assertion; retracting a citation
empties both lists; a ref naming no claim is refused with no assertion
written; a foreign organization's claim is refused with no link written;
`connections` stays empty while `derivedFrom` answers.
`tests/api/test_term_surface.py` pins the enum to the model,
`tests/test_print_schema.py` the `Derivation` registration and
`tests/api/test_loaders.py` the three new loaders.
