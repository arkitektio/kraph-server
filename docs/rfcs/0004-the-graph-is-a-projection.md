# RFC 0004 — Where was the graph still not a projection, and what would a second projection kind need?

- **Status:** **Implemented.** This file is the record of an audit and of the
  changes it led to, kept as the reasoning rather than as an open question. The
  audit itself (24 findings with file:line references) is linked from the
  project memory; its headline findings are restated below so the file stands
  alone.
- **Question:** The architecture says the Apache AGE graph is a *projection* of
  the evidence log — droppable, rebuildable, never a source of truth — and that
  a second projection kind (a per-view table, a search index) should be able to
  sit beside it. Where did the code still treat AGE as truth, and where was
  "there is exactly one projection and it is Cypher" hard-wired?
- **Recommendation (taken):** Name the seam, move the three facts that lived only
  on vertices into Postgres, make the saved-query contract a plan rather than a
  query string, and make the view's handle random and internal. Leave
  `Category.age_name` alone — that row is RFC 0001's open question.

## What the audit found

The write path honoured the principle throughout: evidence first, in one
transaction, projection after; `evidence/` had no Cypher, no graph foreign key
and no vertex id; identity was a bare uuid; membership was the rule evaluated
from claims; ids and payloads were claim-shaped. What did not was the *shape of
the code around it*, in four groups.

**A. AGE consulted as truth.** A write's `drawings` reported the `category_id`
stamped on the vertex, not the rule's answer, so a stale vertex made the write
payload stale. `rematerialize --stale` decided whether work was owed by counting
vertex stamps in Cypher — the ledger inside the cache it audited, destroyed by
the `reproject` that fixes it. `__last_derived` was a wall-clock millisecond on
every vertex, the one projected value a rebuild could not reproduce. `rebuild`
refolded `CurrentStanding` before reading it but trusted `CategoryAssertedTerm`
and `InstanceIdentity` unverified. And nothing knew whether a write's projection
had *finished*: a process that died between the evidence commit and the drawing
left no trace.

**B. A `Graph` was one AGE namespace by construction.** `Graph.age_name` was
non-null, globally unique, derived from user input, interpolated unescaped into
`cypher('…')`, and — through `get_accessible_graph` — the public address of a
view, resolved unscoped. `GraphProtocol`'s only method was `get_age_name()`. The
projector was a module of free functions duck-typed on `controller.engine` and a
private Cypher validator; the controller ran Cypher at seven sites of its own,
two of them writes. One engine was bound at import under a ContextVar named for
the query language. Raw Cypher was the saved-query contract (`CypherLiteral` on
thirteen output positions, `GraphQuery.query`, a render filter regex-spliced
before the last `RETURN`), while the builder's neutral IR was written by one
mutation and readable by no field — `builderArgs` raised on select.
`RetrievedNode` hashed on `(graph_name, vertex_id)`, so every undrawn node equalled
every other.

**C. The view's rule bent to AGE physics.** `resolve_categories` refused a node two
definitions admit "because Apache AGE allows one label per vertex"; definitions
matched words by key alone, so an entity category could admit events, which the
plural lists then wrapped as `Entity`.

**D. Lifecycle outside the controller.** Only the `deleteGraph` mutation dropped
the namespace; every other deletion path left an orphan. Docs disagreed with each
other about whether "a read is a graph query" (it is for properties, not for
membership).

## What shipped

1. **Random internal handle** (`core.models.new_projection_handle`): `g` + 32 hex,
   `editable=False`, 63 chars max; `graph:` resolves by primary key, scoped to the
   caller's organization; `Graph.ageName` stays read-only in the SDL; the
   `GraphManager` / `GraphName` / `SimpleGraph` / `create_age_name` surface is gone.
2. **Projection bookkeeping** (`graph_engine/models.py`, `watermark.py`): a
   `Projection` row per view (status, `schema_hash`, `derived_at`, `rebuilt_at`,
   `kind`) and a `PendingProjection` outbox row written in the evidence
   transaction and deleted by id once the write's projection finished. The cursor
   is **derived** — `min(min_pending_seq − 1, max_seq)` for a consistent graph —
   which is safe against both a late-committing lower seq and a
   commit-then-crash. (The first design stored a per-graph cursor advanced per
   write and swept the outbox by seq; a stress test found the counterexample and
   it was replaced before anything shipped.) `Graph.projection` exposes it;
   `reproject --incremental --organization` applies what is owed; `rematerialize
   --stale` reads `schema_hash` from Postgres; `__last_derived` is gone and
   `Node.lastDerived` deprecated; `create_vertex` is `MERGE` and `reproject_node`
   clears first.
3. **The seam** (`graph_engine/projection/`): `Projector` — writer half and reader
   half, phrased in refs/labels/dicts — with `CypherProjector` as the only module
   that emits Cypher for a drawing; `graph_engine/projector.py` decides what to
   draw and calls `controller.projector.*`; the controller holds a projector and
   runs no query; `api/extensions/projection.py` binds one per operation through
   `graph_engine/projection/context.py`. A write's `drawings` report the rule's
   category; `Retrieved*` hash on `(graph_name, unique_id)`; a `pre_delete` signal
   drops the namespace on every path.
4. **Rules**: definitions and the derived vocabulary match `(key, kind)`; plural
   lists dispatch on the claim's kind; the one-category-per-node refusal is stated
   as the view's policy.
5. **Saved queries are plans** (`graph_engine/query_ir.py`): `GraphQuery.plan` is
   the contract, `TableQueryPlanInput` / `TableQueryPlan` the types,
   `Projector.render_table` compiles per kind (`CypherProjector` emits
   `MATCH … WITH … WHERE … RETURN`, every value a parameter, render filters on
   returned aliases); `query: CypherLiteral` is deprecated and read-only; legacy
   raw-Cypher rows still render and `manage.py list_legacy_queries` names them;
   the eight saved-query kinds that had no execution path are removed.

## What was deliberately left

- `Category.age_name` and the AGE edge-label constants on the event categories —
  RFC 0001 §1–5, open.
- `CypherEngine` keeps its name: it *is* the Cypher driver seam, now referenced
  only by the Cypher projector, the driver and the mock.
- One projector per process, chosen in `api/schema.py`. A registry keyed by
  `Projection.kind` is the next step once a second kind exists; nothing reads
  `kind` yet.
- `classify_nodes` still calls `rebuild_projection` when a label moves. With
  `reproject_node` now clearing first, a per-node relabel is possible; it was left
  as a follow-up because it is a performance change, not a correctness one.

## See also

[`VOCABULARY.md`](../VOCABULARY.md) §3, [`REMATERIALIZATION.md`](../REMATERIALIZATION.md),
[`LOG.md`](../LOG.md) "Known gaps", `graph_engine/watermark.py`, `graph_engine/projection/protocol.py`.
