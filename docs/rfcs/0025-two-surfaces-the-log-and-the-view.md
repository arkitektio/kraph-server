# RFC 0025 — Two surfaces: the log and the view

**Status: Implemented** (2026-09-09). Deferred items listed at the end.

## Question

`Node` carried `term`, `standings`, `sameAs`, `conflicts` (claim grain: exact,
complete, never stale) beside `properties`, `schemaVersion`, `drawnLabels`,
`members`, `categoryIds` (view grain: folded, as of a projection cursor), and
nothing on the type said which was which or as of what. Every edge's endpoint
was a `Node` built with **no view**, whose view half read as "drawn nowhere"
for individuals drawn everywhere. `Entity.categoryIds` read the vertex stamp,
so a cache miss reported as "no category". `Entity.kind` was the drawn label
when drawn and the word when not. Edge singulars borrowed the lowest-pk
category of any view. Claim lists ordered by arrival time and offered no
other order.

## Decision

There are two grains and an answer is one or the other.

- **The view surface.** A `Node` is one view's drawing of an individual and is
  only ever built inside a view (`nodes(graph:)`, `node(id:, graph:)`, a
  write's `drawings`). It names that view (`Node.graph`), the log position the
  drawing is as of (`Node.asOfSeq`, the view's projection cursor), and the
  claim beneath it (`Node.claim`, an `Instance`). Its categories come from the
  view's **rule** (`RetrievedNode.rule_category_ids`, stamped by
  `retrieved_in` and `drawings_for_instance` from `resolve_categories`), never
  from the vertex stamp — the stamp stays as `drawn_category_ids` for the
  projection's own "behind the rule" warning. `schemaVersion`, `lastDerived`
  and `Entity.kind` are gone from the interface; `validFrom`/`validTo` stay as
  derived properties.
- **The log surface.** Everything reached through an edge's endpoint is the
  claim — `Instance` — for `Relation`, `Sameness`, `Difference`,
  `Classification`, both participations, `Measurement.target`,
  `Description.target` and `Structure.informs`; `Instance.drawnIn` says which
  views draw it and `node(id:, graph:)` gives any of those drawings. An edge
  reached without a view (`relation(id:)` and its siblings) has no category and
  its label is the claim's kind: `_category_for_term` is deleted.
- **The panel is keyed by the view's pk**, never its handle, and a claim-grain
  read folds under no view.
- **Claim lists order by the log's own columns**: `seq` (the act's position,
  the default), `observedAt`, then `createdAt` and `id`.
- **Additive corrections are named for what they are**: `supersedeRelation`,
  `supersedeStructureRelation` (were `update*`).
- **Every root field says its grain** in its description; `renderGraphTable`
  says it answers from the drawing; the projection prose no longer names AGE;
  the product surface (upload grants, stats, plots, pins, mentions) is
  sectioned and labelled as not the model.

## Deferred

- `Link.role` is still a string the schema mints; a role is a word and should
  be a `Term` reference.
- `Instance/Link/Comment.createdAt` (arrival time) stay as columns and as an
  ordering; dropping them is a later breaking step.
- `relations(relationCategoryId:)` and its siblings keep their names; a
  single `links(filters: {term, kind})` reader would say the grain in the name.
