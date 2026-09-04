# Evidence Graph Architecture

Status: **historical**. Most of this has since been built, and several of the gaps it names are
closed. Read [`LOG.md`](./LOG.md) for what the system does now — it is the current-state document
and this one is the reasoning that got there.

Where the two disagree, `LOG.md` is right. In particular, this document predates: identity being a
bare uuid rather than a `{age_name}:` composite; `Claim` replacing `LifecycleEvent`, so existence is
evidence rather than a status; the projection holding only what exists, so no vertex carries
`__lifecycle_state`; `State` becoming organization grain with the selector applied on read; and the
**write API naming a term rather than a graph's category**, so a claim can be recorded before any
view exists to hold it and a view can be declared over history it did not witness.

It also predates everything that made the projection *droppable in practice*: §1's "inside a
single AGE label space" describes evidence as AGE labels, which it has not been since the
`evidence` app landed (§4.2's D2 shipped); `rollup.py` and `insights/` no longer exist
(`graph_engine/aggregate.py` and `api/{mutations,queries}/insights/` are what there is); the
projection has a named seam (`graph_engine/projection/`), a bookkeeping row and an outbox
(`graph_engine/models.py`, `watermark.py`), and an incremental `reproject`. Read
[`VOCABULARY.md`](./VOCABULARY.md) §3 for the current shape of the projection layer.

Finally, it predates the end of Apache AGE itself: the drawing lives in ordinary Postgres tables
now (`graph_engine.models.ProjectionVertex` / `ProjectionEdge`, drawn by
`graph_engine/projection/table.py::TableProjector`), and there is no Cypher, no agtype and no
engine layer anywhere in the repo. Every mention of AGE, Cypher round-trips, or agtype below
describes the implementation this document was reasoning about, not the one that exists — see
[`rfcs/0005-retire-the-cypher-projection.md`](./rfcs/0005-retire-the-cypher-projection.md).

One conclusion in here was not merely overtaken but **reversed**, and it is load-bearing enough to
flag up front. §2.1 argues that only filterable properties need materializing and that the rest can
be derived on read "with no observable difference". The code implemented that faithfully, and the
difference turned out to be observable and to grow with the result set. The rule now is: **a graph
is rules plus the log, materialized by an event; a read is a graph query and nothing else.** §2.1
carries the full reasoning and the bill that comes with it.

Scope: the derivation layer of Kraph — how entity and relation properties come to exist from
evidence, where they are stored, and how they survive schema change.

This document describes the architecture as it then was, identifies where it diverged from the
model promised in [BIOLOGIST.md](./BIOLOGIST.md), and proposes a target design with a migration
order.

---

## 1. The architecture as built

Kraph stores each `Graph` as one Apache AGE graph inside PostgreSQL (`Graph.age_name`), with the
schema held separately in Django as polymorphic `Category` models plus versioned
`GraphSchema.definition` JSON.

Inside a single AGE label space, two tiers currently coexist:

| Tier | Labels | Nature |
|---|---|---|
| **Evidence** | `Assertion`, `Structure`, `Metric`, `Claim`, `Link`, `Node` | append-only facts |
| **Projection** | `Entity`, relation edges, `__`-prefixed properties | derived, stored and mutated in place |

Evidence is written as:

```
(Assertion)-[:ASSERTED]->(Metric)-[:DESCRIBES]->(Structure)-[:INFORMS]->(Entity)
(Assertion)-[:GENERATED]->(Entity)
(superseded) (Assertion)-[:GENERATED]->(ShadowLink)-[:REIFIES_AS_SOURCE|REIFIES_AS_TARGET]->(node)
-- `evidence.Link` replaced all of it; nothing has ever written these edges.
```

Projection happens in `GraphController._recalculate_entity` (`graph_engine/controller.py:486`),
which runs one Cypher query per defined property — built by `graph_engine/rollup.py` — and `SET`s
each result onto the entity node, alongside `__lifecycle_state`, `__schema_version` and
`__last_derived`.

**This is a write-time materialized cache, not a virtualized view.** It carries the cost of
materialization without the guarantees that make materialization safe: there is no invalidation
protocol, no dependency tracking, no rebuild path, and no version enforcement.

### 1.1 Where the code diverges from the documented model

BIOLOGIST.md promises that entities are lazy, recalculate on new evidence, and expose the
provenance behind every value. The following gaps are load-bearing, not cosmetic:

- **New evidence does not update entities.** `create_metric` (`controller.py:1247`) writes the
  metric and returns. It never re-derives the entities the structure informs. The fan-out helper
  needed for this already exists — `list_entities_informed_by_structure` (`controller.py:648`) —
  and is called from no write path. The headline claim of the design ("attach a new ROI, the AIS
  updates its length") is unimplemented.
- **`link_structure_to_entity` raises.** At `controller.py:1496` it calls
  `self._recalculate_entity(entity.local_id, entity.kind, effective_schema)` — three arguments
  against a two-argument signature. `TypeError` on the primary "add evidence" flow.
- **Relations are non-functional end to end.** `_recalculate_relation` (`controller.py:553`) uses
  `relation_label` and `shadow_link_id` before assignment, accesses `.materialization.properties`
  on `rel_def` which is a list, and references `vocab.Measurement`, which does not exist
  (`vocab.py` defines `Metric` only). Both `create_relation` and `create_measurement` call it,
  then reference an undefined `relation_name` in their error paths and return
  `EntityCreationResult` where the annotation says `RetrievedRelation`.
- **The batch escape hatch is a no-op.** `link_structure_to_entity` grew a `recalculate=False`
  flag for bulk operations (`api/mutations/structure.py:144-155`), with `recalculate_entity`
  (`api/mutations/entity.py:157`) documented as the follow-up. That mutation calls `get_node` and
  returns; the `_recalculate_entity` call is missing from the body. Anyone who followed the
  documented batch workflow has silently stale entities.
- **`__schema_version` is written and never read.** A schema change leaves every existing entity
  carrying values derived under the old rules, with no backfill path and no way to detect it.
- **Internal properties leak to the API.** `RESERVED_PROPERTY_KEYS` (`retrieved.py:22`) filters
  un-prefixed names (`schema_version`, `last_derived`, `lyfecyle_status` — typo) while the writer
  emits `__schema_version`, `__last_derived`, `__lifecycle_state`. These pass through
  `cleaned_properties` (`retrieved.py:246`) into the public GraphQL `properties` field.
- ~~**Three unrelated meanings of "materialized".**~~ **Closed by deletion, not renaming.**
  `MaterializedRelationEdge` / `MaterializedMeasurementEdge` were schema-level category-pair
  expansions; `MaterializedView` was a query snapshot; `_recalculate_entity` was instance-level
  projection. The first two families are **gone** — the edge cross-products had no invalidation at
  all (RFC 0001 §6), and `MaterializedView` had no reader, writer or GraphQL type.
  `_recalculate_entity` is `projector.project` / `project_refs` now. Only sense (3) remains, so the
  word is no longer overloaded.
- **Two half-built temporal mechanisms.** `valid_from` / `valid_to` are reserved property keys and
  `node_valid` (`insights/graph/parser.py:94`) filters on them in insights templates. Nothing
  populates either. `MaterializedView` had a third pair and is deleted. (Since: `valid_from` /
  `valid_to` are the drawn observation window, `projector._observation_window`, folded from the
  informing metrics' `observed_at`; the dead `EventBaseInput.valid_from/valid_to` inputs went with
  RFC 0015.)

### 1.2 The framing question

"The graph is just a virtualized view" requires explicit answers to three things the code leaves
implicit:

1. **What is the base relation?** — the evidence subgraph in AGE
2. **What is the view definition?** — `defined_properties` on Django category models
3. **Where is it evaluated?** — eagerly, at write time, into the same store as the base

The third answer is the problem. The rest of this document is about changing it.

---

## 2. Should the graph be materialized at all?

The decision to materialize is defensible. The decision to do it synchronously, per fact, across
all properties, is not.

### 2.1 The one argument that justifies materialization

> **Superseded.** The conclusion this section reached — materialize what you filter on, derive the
> rest on read — was implemented, and has since been reversed. The rule now is: **a graph is rules
> plus the log, materialized by an event; a read is a graph query and nothing else.** Everything a
> client can ask for is physically on the vertex before the query runs. The argument below is kept
> because the half of it that still holds is the half that decided the reversal.

`_build_entity_where_clause` emits predicates like `e.length > 40`, and `_build_entity_order_clause`
emits `ORDER BY e.length DESC`. Both operate directly on entity properties.

If `length` were only computable as an aggregate over a subgraph, filtering on it would mean a
correlated subquery per candidate node — unindexable, unplannable, and degrading with graph size
rather than result size. Pagination makes it worse: `SKIP 200 LIMIT 200` over a derived predicate
requires deriving the property for every entity in the category before anything can be skipped.

So derived values appearing in `WHERE`, `ORDER BY`, or traversal predicates must be physically
present somewhere indexable. That part was and is correct.

The step that did not survive was the next one: *"but that argument covers filterable properties
only — values read after a node is already selected can be derived on read through a DataLoader with
no observable difference."* Three things were wrong with it.

**The difference was observable, and it grew with the result set.** `PropertyDefinitionInput.index`
defaults to `False`, so the split was not "a few extras computed lazily" but "everything is lazy
unless you opt in". Per entity per read: one `Category` query, then per property a `StructureKind`
lookup, a `MetricKind` query, and either a `State` read or — when the graph carries a selector — a
scan of `Metric`, the highest-churn table. All behind `sync_to_async`, so each was a thread hop as
well as a round-trip. For N entities and P derived properties that is ≈ `N × (1 + 3P)` queries;
200 entities × 5 properties ≈ 3,200 round-trips where a materialized read is one Cypher query.
A DataLoader would have collapsed the constant, not the growth in N.

**The asymmetry settles it.** The read cost is unbounded in result-set size. The write-side increase
is bounded by properties-per-category, a constant. Unbounded-in-N is the one that cannot be outrun
by hardware or caching.

**And "filterable" was not a property of the data.** Whether you could `WHERE` or `ORDER BY` a value
depended on a flag someone had to set in advance, and `index` never built an Apache AGE index — it
only decided whether the property was materialized at all. Materializing everything makes every
derived property filterable and sortable: a capability gain, not just a speed one.

#### What that costs, and where the bill arrives

Adding a property is no longer free. It needs a rematerialization, because the vertex is now the
answer rather than a cache of the cheap half of it. That is paid in three places:

- `api/mutations/schema/_rematerialize.py` — a category edit that moves the property hash redraws
  every vertex the category draws, and `REMOVE`s the keys a dropped property left behind. Cypher
  `SET` only adds and overwrites, so without the explicit removal a value no rule still derives
  would stay on the vertex answering queries forever.
- `manage.py rematerialize` — the same work out of band, since the redraw is unbounded in the size
  of the graph and this service has no job queue. `--stale` selects on `__schema_version`, the stamp
  `projector.project` writes onto every vertex, so an unfinished redraw is detectable rather than
  silent.
- `manage.py reproject` — still the answer when *membership* is wrong rather than the values, since
  moving a node between labels is what AGE cannot do in place.

#### Two consequences worth stating

**Per-view values are materialized per view.** A graph's selector can make the same entity carry a
different number in a different view, which is why `_scoped_state` existed on the read path. That is
not a reason to compute on read — each graph has its own AGE namespace, so the scoped value is
materialized into *that* namespace, and the selector becomes an input to materialization rather than
to the query.

**Provenance drill-down stays a Postgres lookup.** `contributing_assertions` and
`supporting_evidence` answer "which measurements produced this number" for one already-selected
node. They return rows, they are unbounded in length, and nothing filters or sorts on them. The rule
is that no value a query *returns as a property, filters on, or sorts by* is computed at read time —
not that a node can never be asked a follow-up question.

#### The gap this leaves open

**Edges derive nothing.** `projector.project_edges` writes `category_id` and `__assertion_count`
onto an edge and stops. But `createRelationCategory` accepts `properties` and stores them in
`property_definitions` — so a relation can declare a derivation rule that nothing has ever run.
`bio_graph_schema`'s `IS_CONNECTED_TO.distance` (a `EUCLIDEAN_RANGE` rollup) is exactly such a rule.
This is the same family of defect as the read-time derivation removed above, one layer over: the
node side was fixed and the edge side was not. `update_relation_category` and
`update_structure_relation_category` carry comments saying so rather than a rematerialization hook,
because there is nothing yet to rematerialize.

### 2.2 Why the current form fails regardless

The dominant write pattern in this domain is bulk: a segmentation run emits thousands of ROIs and
metrics in a burst. Under per-fact recalculation, adding N metrics to a structure informing one
entity triggers N full entity recomputes, each issuing one AGE round-trip per defined property,
each rescanning the whole evidence subgraph. That is `O(N² × P)` for a batch that should be
`O(N + P)`.

The `recalculate=False` flag is evidence this was already hit in practice. It is the right
instinct — an ad-hoc dirty-flag protocol — but implemented by hand at one call site, opt-in per
caller, and with a follow-up mutation that does nothing.

### 2.3 The property that dissolves the tradeoff

Every aggregate in `AggregationFunction` — `MEAN, SUM, MAX, MIN, COUNT, RANGE, EUCLIDEAN_RANGE,
LATEST` — is a monoid over a small piece of running state, and evidence is append-only. So all of
them are **incrementally maintainable in O(1) per new fact**:

| Aggregate | State kept | On new fact |
|---|---|---|
| `SUM`, `COUNT` | `sum`, `n` | `+= v`, `+= 1` |
| `MEAN` | `(sum, n)` | as above; divide on read |
| `MIN` / `MAX` / `RANGE` | `(min, max)` | two comparisons |
| `LATEST` | `(value, ts)` | one comparison |
| `EUCLIDEAN_RANGE` | `(first_by_ts, last_by_ts)` | two comparisons |

A new metric merges into the entity's state in constant time regardless of how much evidence
already exists. The current code re-derives from scratch on every write; that rescan — not
materialization itself — is the actual waste.

With O(1) maintenance you get indexable properties *and* cheap ingest, which is the combination
the present design is reaching for and missing.

**Caveat — retraction.** Archiving a metric breaks incrementality for `MIN`/`MAX`/`RANGE`/`LATEST`
(you cannot un-max). `SUM`/`COUNT`/`MEAN` survive by subtracting the delta. Correct handling is to
treat retraction as the rare path that triggers a scoped full recompute, keeping the append path
fast. `archive_*` is already a distinct and infrequent operation, so the split is clean.

---

## 3. Schema evolution without a job queue

The concern that every schema change forces an asynchronous mass recalculation is well-founded for
the current design, but it follows from the state representation rather than from schema evolution
itself.

### 3.1 Store sufficient statistics, not computed scalars

Storing `e.length = 45.2` — the *output* of `MEAN` — entangles the value with the aggregation
function, so changing `MEAN` → `MAX` invalidates it.

Instead, keep a fixed state vector per `(entity, source_category, metric_key)`:

```
{ n, sum, min, max, first_ts, first_val, last_ts, last_val, first_pt, last_pt }
```

Every aggregate in the enum is computable from this vector without reading a single `Metric` node.
At roughly 80 bytes per (entity, key), it buys:

| Schema change | Rescan required? |
|---|---|
| Aggregation swap (`MEAN` → `MAX` → `LATEST` → …) | **No** — reinterpret existing state |
| Change type, unit, label, description, ontology reference | **No** |
| Remove a property | **No** |
| Add a new entity or relation category | **No** — no instances yet |
| Add a property over an already-tracked `(source, key)` | **No** |
| Add a property over a new `(source, key)` | Yes — scoped to that key |
| Re-point a property at a different source or key | Yes — scoped to that property |

The change users iterate on most during schema design — "is length the mean or the max of the
ROIs?" — becomes a read-side reinterpretation: no backfill, no queue, instant.

### 3.2 Prerequisite: version every category mutation

`update_entity_category` (`api/mutations/schema/entity_category.py:29`) calls
`update_from_entity_definition` and mutates the category in place without creating a new
`GraphSchema`. The versioning substrate — immutable definitions, monotonic `index`, `is_active` —
is bypassed by the mutation that most needs it.

Without a version per change there is nothing to diff, so nothing can be scoped, which is exactly
why the work looks like "recalculate everything." Every category mutation must emit a new
`GraphSchema`; then diffing `v_n.definition` against `v_n+1.definition` yields the precise set of
`(category, property)` pairs needing work. `jsonpatch` is already a project dependency and is a
natural fit for producing that diff.

This converts *"recalculate the category"* into *"recalculate these two properties on entities
holding evidence for key X."* It is a prerequisite for everything else in this section.

### 3.3 Expand–contract removes the latency pressure

Because `GraphSchema` is immutable and versioned:

1. **Create** `v_n+1` inactive — O(1), nothing computed.
2. **Expand** — backfill new or changed properties under versioned keys (`length@4`). Readers are
   pinned to `v_n` and remain correct.
3. **Activate** — flip `is_active`. O(1), atomic cutover.
4. **Contract** — drop `length@3` at leisure.

The system stays available and correct throughout step 2. Nothing is observably half-migrated,
because readers resolve against the active version. The backfill is therefore on no critical path:
it need not be fast, transactional with the mutation, or reliable on first attempt — only
restartable and idempotent, which it is by construction.

`manage.py backfill_schema --graph X --to-version 4` is a complete solution with zero new
infrastructure. A queue can follow if anyone ever complains about running it.

Cost calibration: a scoped backfill is one grouped aggregate over metrics matching a single key —
under a relational evidence store (§4.2) literally one `INSERT ... SELECT ... GROUP BY`. For 10⁶
metrics that is seconds. The present implementation feels expensive because it is N per-entity
queries × P properties through AGE, which is a property of the implementation, not the problem.
 
 
### 3.5 What remains genuinely hard

- **Re-pointing a property at a new source.** A real full rescan for that property — unavoidable,
  but scoped, restartable, and off the critical path under expand–contract.
- **Retraction during backfill.** If a metric is archived mid-backfill, the state vector's
  `min`/`max`/`latest` cannot be repaired incrementally (§2.3). Have the backfill record its
  high-water assertion id and have retractions inside that window mark affected entities for a
  second pass.

---

## 4. Target architecture

Four design decisions. They are separable, and the recommended order is in §5.

### 4.1 D1 — Make the projection disposable

Enforce the two tiers as an invariant rather than a convention.

- **Evidence is append-only.** No `SET`, no `DELETE`, ever. `update_structure`'s
  `SET s.object = $obj` (`controller.py:1123`) becomes a new `Structure` plus a supersede
  assertion.
- **Projection is droppable.** Everything on `Entity` beyond `id` and `category_id` is derivable
  from evidence plus a `GraphSchema` version.

Replace the scattered `_recalculate_*` calls with a single `Projector` owning three operations:
`dirty(node_ids)`, `project(entity_ids, schema)`, `rebuild(graph, schema)`. Every evidence write
emits a dirty set; `create_metric` walks the `INFORMS` closure using the existing helper.

Two things make this real rather than cosmetic:

1. **`__schema_version` becomes load-bearing.** A read finding
   `__schema_version != category.schema_hash` reprojects lazily (for non-indexed properties) or is
   resolved through the expand–contract flow (§3.3).
2. **Ship `manage.py reproject`.** Drop the projection tier for a graph, replay evidence. This is
   the honest test of the whole architecture: if the graph cannot be rebuilt from the evidence,
   the evidence is not the source of truth, whatever the documentation says.

### 4.2 D2 — Move the evidence base out of AGE

The evidence layer is not graph-shaped. `Assertion`, `Structure`, `Metric` are flat, append-only,
high-volume, and accessed by key — never by variable-length path. Keeping them in AGE pays agtype
serialization, a `LOAD 'age'` per cursor, label-per-category DDL, and the string interpolation in
`_substitute_params` (`age_engine.py:176`) standing in for real parameter binding — all for what is
a fact table.

```
evidence_assertion (id, graph_id, subject, app_id, action_name, action_args, asserted_at)
evidence_structure (id, graph_id, category_id, identifier, object, assertion_id)
evidence_metric    (id, graph_id, structure_id, category_id, key,
                    value_num, value_txt, value_json, unit,
                    confidence, confidence_type, observed_at, asserted_at, assertion_id)
evidence_link      (id, graph_id, category_id, source_ref, target_ref, assertion_id)
evidence_lifecycle (id, target_ref, status, at, assertion_id)
```

Rollups become SQL aggregates with real indexes, planning, and parameter binding.
`_recalculate_entity`'s round-trip-per-property loop collapses into one grouped statement per
category. Partition `evidence_metric` by graph.

AGE then holds only entities and relation edges — the part that genuinely needs path queries
(`insights/graph/path.py`, pairs, table renders). It stays small, making the D1 rebuild cheap
enough to be routine.

### 4.3 D3 — Virtualize reads

Split `defined_properties` into **indexed** and **derived-on-read**. A property is materialized
only if declared filterable or orderable (§2.1); everything else resolves through a DataLoader at
query time — `api/loaders.py` already carries the pattern.

For derived-on-read properties, generate a Postgres view per entity category from
`GraphSchema.definition`:

```sql
CREATE VIEW entity_ais_v AS
  SELECT entity_id,
         avg(value_num) FILTER (WHERE key = 'vector_length') AS length,
         ...
```

Schema change regenerates the view; the staleness class ceases to exist for those properties.
`REFRESH MATERIALIZED VIEW CONCURRENTLY` becomes an available tuning knob rather than a
requirement.

This requires D2. Adopt it per category rather than wholesale. Pure virtualization is elegant but
fights `insights/graph/` — hence the indexed/derived split rather than an all-or-nothing choice.

### 4.4 D4 — Make disagreement and time first-class

Orthogonal to D1–D3, and the decision that separates an evidence graph from a graph with an audit
log.

Today every derived property collapses to one scalar. The premise in BIOLOGIST.md is "add
conflicting evidence" and "45.2µm (confidence 98%), derived from ROI #555, asserted by
AI_Model_X." The projection can express neither. `RichProperty` in `api/types.py` is the right hook
with nothing behind it.

- **Project to value + provenance + agreement**, not a scalar:
  `{value, n_evidence, spread, contributing_assertion_ids, confidence}`. The §3.1 state vector
  already carries most of this.
- **Add `ConflictPolicy` alongside `AggregationFunction`.** When two subjects disagree past a
  threshold: pick by subject priority, flag, or go multi-valued. `PRIORITY_LATEST` already exists
  in the enum with a `# Same as LATEST for now` stub (`rollup.py:275`) — that is the seed.
- ~~**Split `asserted_at` from `measured_at`.** A single `timestamp` field currently does both jobs.~~
  **Done, and then widened.** Metrics got the two columns with the evidence base; RFC 0015 gave
  every claim the world-time column under one name, `observed_at` (`Standing.at` for positions),
  and made `OBSERVED_AT` a rule field on every claim kind. "What did we believe on March 3rd" is
  `ASSERTED_AT BEFORE`; "how was the world on March 3rd" is `OBSERVED_AT BEFORE`.

---

## 5. Recommended sequencing

| Order | Work | Rationale |
|---|---|---|
| 0 | Fix the defects in §6 | Silent staleness and dead code paths; independent of any pivot |
| 1 | **D1** — `Projector`, dirty tracking, `manage.py reproject` | Cheapest change that makes the documented model true |
| 2 | §3.1–3.2 — state vector + per-change schema versioning | Removes most schema-change backfill; unblocks the fear driving §3 |
| 3 | **D4** — provenance-carrying properties, bitemporality | What the product is actually for; mostly schema/type work, storage-independent |
| 4 | **D2** — relational evidence base | The scaling bet; do it once D1 has proven the rebuild path |
| 5 | **D3** — indexed/derived split and per-category views | Follows naturally from D2; adopt incrementally |

---

## 6. Defects to fix regardless of direction

1. `recalculate_entity` (`api/mutations/entity.py:157`) never recalculates — the
   `_recalculate_entity` call is absent. Silent staleness for anyone following the documented
   batch workflow.
2. `create_metric` (`controller.py:1247`) and `update_structure` (`controller.py:1123`) do not
   re-derive downstream entities.
3. `link_structure_to_entity` (`controller.py:1496`) calls `_recalculate_entity` with three
   arguments against a two-argument signature.
4. `_recalculate_relation` (`controller.py:553`) cannot execute: undefined `relation_label` and
   `shadow_link_id`, `.materialization.properties` accessed on a list, and non-existent
   `vocab.Measurement`. Callers reference undefined `relation_name` and return the wrong type.
5. `_recalculate_entity` issues one AGE round-trip per property; a single query — or the SQL of
   D2 — replaces the loop.
6. Property keys reach Cypher `SET e.{k}` unvalidated; `_validate_property_key` exists but is not
   applied on that path.
7. `RESERVED_PROPERTY_KEYS` (`retrieved.py:22`) does not match the `__`-prefixed keys actually
   written, leaking internal properties through the GraphQL `properties` field. Fix the
   `lyfecyle_status` typo while there.
8. ~~Rename the three distinct "materialized" concepts (§1.1).~~ **Done** — two of the three were
   deleted outright rather than renamed; see §1.1.
