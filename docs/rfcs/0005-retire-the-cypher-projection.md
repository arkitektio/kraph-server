# RFC 0005 — Retire Apache AGE: the table projection is the projection

- **Status:** **Implemented.** Like RFC 0004, this file is a record rather than
  an open question: the decision was taken with nothing deployed on the AGE
  side, so there was no migration to weigh — only a design to keep honest. It
  exists so the next person knows *why* AGE left, which invariants the table
  projection must keep, and what would count as regressing them.
- **Question:** Apache AGE was the only projection kind. Given that every read
  that matters had already moved to the evidence tables (RFC 0004), that the
  repo emits **no** variable-length path, shortest-path, or graph-algorithm
  query anywhere — every query is a fixed-hop join wearing Cypher syntax — and
  that PostgreSQL 19 ships SQL/PGQ over ordinary tables, what was AGE still
  buying, and at what cost?
- **Recommendation (taken):** Nothing worth its costs. Replace `CypherProjector`
  with a `TableProjector` over two ordinary Postgres tables, delete the
  `CypherEngine` seam and every Cypher artifact, and keep the whole
  "graph is a projection" architecture — protocol, outbox, watermark,
  bookkeeping — unchanged.

## What AGE cost

Each of these was a scar the repo already carried, not a hypothetical:

- **The indexing story warped the API.** agtype properties in one column cannot
  be indexed sanely, so `has_property`/`search`/`matches` were guarded by an
  indexed-key rule and the drawing-scoped list was second-class.
- **A type-cache bug dictated test architecture.** Dropping and recreating an
  AGE graph on a live connection raises on stale label OIDs; the suite first
  leaked graphs between tests (order-dependence), then dropped-and-reconnected
  around it.
- **Unstable ids caused a bug class.** AGE vertex ids are reassigned by every
  reproject; `vertex_id` vs `unique_id`, the dead `globalId`, and the composite
  `{graph}:{vertex_id}` parsers were all fallout.
- **Version coupling.** AGE trails Postgres majors, so a custom image gated
  every upgrade, and the test stack needed that image rather than stock
  `postgres`.
- **A translation layer to nowhere.** AGE stores vertices and edges as tables
  underneath; the repo paid Cypher parsing and agtype marshalling to reach the
  storage model it could have addressed directly, with real indexes.

## What replaced it

Two rows in `graph_engine/models.py` — `ProjectionVertex` and `ProjectionEdge`
— and one module, `graph_engine/projection/table.py::TableProjector`, the only
code that reads or writes them. The protocol's convergence rules became unique
constraints (`(graph, ref)` for vertices, `(source, target, label)` for edges);
`DETACH` became an FK cascade; the namespace became the `graph` key on the rows,
so `create_namespace` is a no-op and a deleted `Graph` takes its drawing with it.
Saved-query plans compile to parameterized SQL
(`compile_table_plan_sql`) instead of Cypher — the plan IR from RFC 0004 is
what made the compiler swappable without touching a client.

One protocol repair rode along: `list_drawn` took query-language *fragments*
(a Cypher predicate string, an `ORDER BY` clause, a `SKIP/LIMIT` string, built
by the controller). It takes a structured `ListDrawnSpec` now, and each
projection kind compiles it — the last place the protocol spoke a query
language.

Because the drawing now lives in the same database as the evidence, a write's
draw commits **in the same transaction** as its assertion: in steady state the
outbox settles with the write and `lag` is structurally zero. The outbox,
derived watermark and `Projection` bookkeeping stay exactly as RFC 0004 built
them — they are what makes backfill, rebuild and any future *asynchronous*
projection kind correct, and they degenerate gracefully when the steady state
is synchronous.

## What "the graph is a projection" means now

The invariants transferred whole; only their enforcement moved:

| Invariant | Enforcement |
|---|---|
| Truth is evidence; the drawing is derived | unchanged — membership, identity, standings read evidence |
| Droppable and rebuildable | `drop_namespace` deletes rows; `manage.py reproject` re-derives them |
| One module addresses the storage | `tests/projector/test_projector_protocol.py` scans every production package for the table names |
| Nothing holds evidence in place | `ProjectionVertex.ref` is a plain uuid value, never an FK into `evidence` |
| Internal ids are opaque | row pks; reassigned by rebuild, carried on `RetrievedNode.vertex_id`, never identity |

The failure mode to watch for is convenience: the projection tables are ordinary
Django models now, and it will always be *easier* to join them from a resolver
than to go through the protocol. The fence test is the tripwire; this file is
the reason it must stay.

## What was deleted with it

`graph_engine/engine/` (the `CypherEngine` protocol, `AgeEngine`, the mock),
`projection/cypher.py`, agtype parsing, the `CypherLiteral` scalar and the
deprecated read-only `GraphQuery.query` field (the compiled-Cypher read-back).
A **legacy** saved-query row (plan null, raw Cypher stored) no longer renders at
all — no projection kind executes Cypher — and `renderGraphTable` says so;
`manage.py list_legacy_queries` still names such rows so they can be rebuilt
through the builder.

## Deliberately left

- **`Graph.age_name` and `Category.age_name`.** Both survive as names for
  things that still exist — the graph's opaque projection handle and the view's
  label for a word. Renaming them (`projection_handle`, `label`) is cosmetic
  follow-up; `Category.age_name` remains RFC 0001's question. Nothing may
  re-grow an *address* out of either.
- **`Projection.kind`** (default `"table"`) and the one-place projector choice
  in `api/schema.py`. Still the seam for a second kind — a search index, or a
  real graph engine if variable-length traversal ever becomes a real
  requirement. SQL/PGQ (`GRAPH_TABLE`, PostgreSQL 19) is the expected *query
  frontend* over these same tables if ad-hoc graph syntax is ever wanted: labels
  in PGQ attach to relations, so it would be per-label views plus one
  `CREATE PROPERTY GRAPH` per view, maintained by `materialize` — a frontend,
  never the storage.

## What would count as regressing this RFC

- A resolver, loader, or management command importing `ProjectionVertex` /
  `ProjectionEdge` directly (the fence test fails).
- An FK from an evidence or core row into a projection table, or the reverse
  beyond the existing `graph` key.
- A read that answers a *claim* question (membership, existence, standing) from
  the projection tables because they were closer to hand.
- Storing a per-graph "applied through seq" again — the outbox/watermark
  invariant from RFC 0004 is unchanged by this RFC.
