# RFC 0027: Structures are drawn where a view mounts them, and a pairs query's run is a training set

**Status: Implemented** (2026-11-08). Amends RFC 0006 and RFC 0012 where they say a
structure is never a vertex.

## Question

A training action (CARE, cellpose) needs pairs of data: an image and its ground truth.
The organization claims those pairs in the log as structure relations
(`GROUND_TRUTH_OF` between two `@mikro/arraylens`). How does a trainer get *exactly* the
pairs it learned from, chosen by a rule the view states, and cite them afterwards?

kraph has three layers: the **log** records everything claimed, the **graph** (a view's
drawing) holds what the view's rules admit, and a **query** over the graph is an
insight. A training set is an insight: a query's answer. Reading pairs straight off the
log through a category skips the graph and the query layers, and a category is not
something a trainer can write a selection in.

## Finding

Structures were never vertices. Since M1 a structure has been an organization-scoped
evidence row, and a structure relation "an evidence row and only an evidence row"
(`create_structure_relation` settled its outbox row and drew nothing). That was argued
from storage (AGE vertices per graph) and tenancy, and both reasons went with the AGE
projection (RFC 0005, 0006): the table projection draws per graph into shared tables, and
a structure's tenancy is its organization, exactly as an instance's is.

So no query could ever return a structure, and a saved query could not select pairs.

## Decision

- **A view mounts a structure kind.** A `STRUCTURE` category (`StructureCategory`, with
  `structure_kind` pointing at the organization's `StructureKind`) is the vertex label
  that view draws data of one identifier under: `@mikro/arraylens` mounted as `Image`.
  It is declared in the graph definition (`extensions.structures`) or with
  `createStructureCategory`, the view's counterpart of a service declaring the
  structures it hosts. One mount per kind per view.
- **A structure relation's ends name mounted identifiers.** An end naming an identifier
  the view does not mount is refused at definition time
  (`core.managers.refuse_unmounted_ends`). An open end admits every mounted kind.
- **Admission** (`projector.admitted_structure_relations`) follows three rules:
  - The category's rule admits the claim, with standings under its trust, as for every
    edge (RFC 0009, 0026).
  - Both endpoint structures stand at organization grain.
  - Each endpoint's identifier is mounted and named by its end.
- **A structure is a vertex only where an admitted claim touches it.**
  - It is labelled by its mount and carries `identifier` and `object`, the address the
    datum has outside kraph, so a query can return it.
  - It is a vertex of one member, itself: structures have no sameness.
  - The claim is an edge under the structure-relation category's label, with
    `__assertion_count`.
- **One drawing path.**
  - The write path (`create_structure_relation`, `retract_relation`, `attest_link`,
    `retractStructure`) draws after the act under `_draw_after`, through
    `_reproject_structures_everywhere`.
  - `project_all` and `rebuild` draw every admitted claim, and `converge` redraws touched
    structures.
  - `touched_refs` maps a structure relation to both ends, and a structure that a
    relation names to itself.
  - A rule change rebuilds, and so do mounting and unmounting.
- **The namespace** has a vertex element per mount and an edge element per
  `(structure-relation category, source mount, target mount)`.
- **A pairs query is a saved query kind** (`GraphQuery` kind `PAIRS`, `GraphPairsQuery`).
  - Its plan is a match over the drawing plus the two nodes that are the pair
    (`query_ir.PairsQueryPlan`).
  - It lowers to a table plan returning both ends' `id`, `identifier` and `object`, so
    one compiler, validation and cost bound serve both kinds.
  - `renderGraphPairs` previews it live.
- **A run is the stored insight** (`datasets.PairsQueryRun`). The drawing has no "as of"
  (RFC 0014), so the only exact record of what a model learned from is the answer
  itself, kept with:
  - its distinct pairs, sorted;
  - the plan as it was run;
  - `as_of_seq`: the lower of the view's projection cursor and the log's committed
    horizon, read before the render. Every pair was drawn from a log that reached at
    least that seq.

  A run is refused while the view is not drawn consistently. An end that is a drawn
  instance rather than a structure travels as `@kraph/entity`.
- **A model cites a run.**
  - `TrainedModel.trained_on` restricts deletion of the run, and the run restricts
    deletion of its query.
  - `createModel(trainedOnQuery:)` runs the query for the model (`auto`).
- **Ports find them by `requires`.** `@kraph/pairsquery` and `@kraph/pairsrun` are
  hosted structures whose descriptors carry the identifiers their ends are constrained
  to, or that every pair shares. Every key is always present, and null where it does
  not apply, so a null fails an `EQUALS` in both evaluators.

## What this replaces

The previous cut (never released or migrated) read a structure-relation category's
pairs directly from the log "as of a seq" and pinned them (`PairedDataset`). It is gone:
`links_for_category_as_of`, the category's `pairs`/`horizon`/`descriptors` fields and its
`requires` filter, and `@kraph/structurerelationcategory` as a hosted structure.

## Open

- An instance end of a pairs query (`@kraph/entity`) is carried but no service resolves it.
- The live preview renders the whole answer and pages it in Python; it has the same
  statement timeout as every table query.
- A pairs query's `@kraph/*_identifier` descriptors are computed when it is saved. A query
  saved before its mount exists keeps null, and typed ports don't see it until it is saved
  again; `restore_descriptors` fills only missing keys.
- Mounting goes through `Category.save`, which mints a STRUCTURE-kind `Term` under the
  mount's key (`Image`), as every category mints its word.
