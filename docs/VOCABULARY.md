# Vocabulary

One word per concept, sorted by **which layer owns it**. The layer is the thing
worth knowing first: it tells you whether a word names something the organization
recorded, something one view declared about it, or something a projection
computed — and those three answer to different rules about who may change them
and what happens when they disagree.

The three layers, in the order data moves through them:

| Layer | Question it answers | Source of truth | Rebuildable? |
|---|---|---|---|
| **Evidence** | *What did somebody claim?* | Postgres, `evidence/` | **No.** Append-only. Losing it loses the facts. |
| **Schema** | *What does one view make of those claims?* | Postgres, `core/` | No, but deleting it takes no evidence with it. |
| **Projection** | *What does that view look like, drawn?* | `graph_engine.models.ProjectionVertex`/`ProjectionEdge` (ordinary Postgres tables), plus the `graph_engine.Projection` row that says how far along the log the drawing is | **Yes.** `manage.py reproject` rebuilds it from the other two; `reproject --incremental` applies what the outbox says is owed. |

The single most load-bearing consequence: **a projection is a cache and the
evidence is not.** If a projected value and a claim disagree, the claim wins and
the projection is stale. If a schema row is deleted, the claims it drew survive.

There is a fourth section below for the **API surface** — words that exist only
in GraphQL and name a *shape*, not a table.

---

## 1. Evidence — what the organization recorded

Django rows in `evidence/models.py`. Organization-scoped, never graph-scoped.
Append-only: corrections are new rows, never edits, and there is no hard delete.

### The act and its subjects

| Word | Means | Where |
|---|---|---|
| `Assertion` | The **act** — who claimed it, with what tool, when. Carries `seq`, the log's total order. Every write records exactly one | `evidence.Assertion` |
| *claim* | Any **recorded statement**. A prose word covering `Instance`, `Link`, `Metric`, `Structure` and `Comment` — not a table. An instance, link, metric or standing may carry a `confidence` in [0, 1]; null is silence, and a `CONFIDENCE` rule never admits silence (RFC 0016) | — |
| `Instance` | A claimed **individual**: `entity`, `natural_event` or `protocol_event`. Every observation mints its own. Carries `observed_at` — when it was seen, or for an event when it happened | `evidence.Instance` |
| `Link` | A claim **relating two things**. Ten kinds: `RELATION`, `SAME_AS`, `DIFFERENT_FROM` (negative sameness: vetoes the direct `SAME_AS` between its ends — RFC 0019), `CLASSIFIES`, `INFORMS`, `MEASUREMENT`, `STRUCTURE_RELATION`, `PARTICIPATES_AS_INPUT`, `PARTICIPATES_AS_OUTPUT`, `DERIVED_FROM` (lineage: this claim came from that one, either end any claim row — RFC 0017). Carries `observed_at` — when the relation held | `evidence.Link` |
| `Structure` | An **individual with an external identity** — an ROI, an image, a file — identified by `(identifier, object)` rather than minted per observation (RFC 0023). Never itself claimed to be an AIS; the thing metrics are *about* and INFORMS claims are *from*. Its existence has a standing the folds honour, and a second existence claim is recorded as agreement. Carries `observed_at` and `confidence` like every claim | `evidence.Structure` |
| `Metric` | A **measured value** about a structure. Carries `observed_at` (was `measured_at`) | `evidence.Metric` |
| `Comment` | A **remark** about a structure, with a threaded reply tree | `evidence.Comment` |

### Position on a claim

| Word | Means | Where |
|---|---|---|
| `Standing` | Somebody's **position** on whether a claim still holds (`stands=True/False`). Retraction and attestation both write one. `at` is when the position took effect — the world-time column an `OBSERVED_AT` rule reads over standings | `evidence.Standing` |
| `CurrentStanding` | The folded answer, a **cache** over `Standing` — the fold under the trust-everyone view, total over claim kinds since RFC 0024, instances included. What a *view* says about a node's existence is its category's rule (`resolve_categories`), which never reads this table | `evidence.CurrentStanding` |

### The organization's vocabulary

These are words, not rules. A claim names one of these; what a *view* makes of it
is a `Category` (§2).

| Word | Means | Where |
|---|---|---|
| `Term` | A **word** the organization uses, identified by `(organization, kind, key)`. What an `Instance` or `Link` names | `evidence.Term` |
| `StructureKind` | A kind of external datum, identified by `(organization, identifier)` — e.g. `@mikro/roi` | `evidence.StructureKind` |
| `MetricKind` | A kind of measurement, identified by `(organization, structure_kind, key, value_kind)`. **Dependent** — it hangs off a structure kind | `evidence.MetricKind` |

> Whether these three are really one thing is **RFC 0002, open**. The current
> answer: same *pattern*, not the same *thing*. Don't merge the tables.

All three are minted **lazily**, by `evidence.writer.ensure_*`: refusing to record
a fact because nobody had declared the word would be refusing it on a bookkeeping
technicality. All three are `PROTECT`ed from the rows that name them — a word
that has been used can be retired, never deleted.

A word's **identity is immutable** and its **presentation is not evidence** (RFC
0022). The identity columns — `(organization, kind, key)`, `(organization,
identifier)`, `(organization, structure_kind, key, value_kind)` — are what claims
reference, and a `BEFORE UPDATE` trigger refuses to rewrite them (evidence
migration 0016, same hatch as the log's). `label`, `description`, `purl`, `color`
and `image` are how the word shows; they may be edited in place and no act
records it, because nothing a rule reads depends on them.

### Two clocks

| Word | Means | Where |
|---|---|---|
| `asserted_at` | **Belief time** — when the claim was made. On `Assertion`, denormalized onto `Metric`. The `ASSERTED_AT` rule field | `evidence.Assertion` |
| `observed_at` | **World time** — when the world was as the claim says: an entity seen, an event happened, a relation held, a value measured. On every claim (`Instance`, `Link`, `Metric`), defaulting to the assertion's `asserted_at`, so never null. The `OBSERVED_AT` rule field (RFC 0015) | `evidence.Instance`, `evidence.Link`, `evidence.Metric` |
| `Standing.at` | The same axis for a **position**: when it took effect. `OBSERVED_AT` reads this column over standings (`selector` passes `observed_at_column="at"`) | `evidence.Standing` |

### Folded from evidence (caches, rebuildable)

Sit in the evidence app but are **derived**, so they belong with the projection
conceptually: each has a `--check`able rebuild.

| Word | Means | Rebuild |
|---|---|---|
| `InstanceIdentity` | Components folded from `SAME_AS` claims, less the pairs a standing `DIFFERENT_FROM` vetoes. Organization grain, lowest uuid as representative; **only merged nodes get a row**. What the panel reads; a view's drawing folds its own (`identity.view_components`) | `manage.py rebuild_identity [--check]` |
| `State` | Sufficient statistics for one derived property, kept incrementally. Grain `(claim_ref, source_kind, key, value_kind)`. Holds **statistics, not an answer** — switching MEAN→MAX changes the next read without writing anything | `evidence.state.recompute` |
| `CurrentStanding` | see above | `evidence.claims.record_current` |

---

## 2. Schema — what one view declares

Django rows in `core/models.py`. **Graph-scoped.** This is the ontology layer:
which node and edge kinds a `Graph` allows, and how it draws them.

Deleting any of it is free and takes no evidence with it. The `PROTECT` is on
`Term`, not here.

| Word | Means | Where |
|---|---|---|
| `Graph` | A **view** over the organization's claims. No selector (RFC 0009): each category's `definition` is the complete rule for its word. Not a container — a reconstruction | `core.Graph` |
| `Category` | One **view's rule for a word**: its `age_name` (the drawing's label), `definition`, derivation rules, layout, colour. `Category.term` is the join to the evidence layer | `core.Category` |
| `GraphSchema` | A **versioned, immutable** schema definition. Each graph has one active at a time; `index` increments | `core.GraphSchema` |
| `CategoryAssertedTerm` | The **joinable half** of `Category.definition` — which words a category *derives* from, normalized out of JSON. Stores the **key**, not a `Term` FK, because a definition routinely names a word nobody has minted | `core.CategoryAssertedTerm` |
| `GraphOntology` / `OntologyReference` | External ontology bindings (PURLs) for a graph and its categories | `core.GraphOntology`, `core.OntologyReference` |

`Category` is **one concrete table** with a `kind` column. The old
multi-table-inheritance class names survive as Django **proxies**:

- node categories — `EntityCategory`, `NaturalEventCategory`, `ProtocolEventCategory`
- edge categories — `RelationCategory`, `MeasurementCategory`, `StructureRelationCategory`

> That proxying matters when writing queryset code: `EntityCategory.objects.all().model.__name__`
> is `"EntityCategory"`, while `_meta.concrete_model.__name__` is `"Category"`.
> `api/types.py::_organization_filter` keys on the concrete model for exactly
> this reason — a lookup keyed on the proxy name fails open.

### Two words a graph can have for a term

| The graph… | …by | Joinable? |
|---|---|---|
| **declares** a word | `Category.term`, a foreign key | yes, directly |
| **derives from** a word | `definition.asserted_as`, a string in JSON | only via `CategoryAssertedTerm` |

Graph membership counts **both**, and is decided in exactly two functions —
`evidence.selector.instances_for` and `graph_ids_for_instance_ids` — which agree.

### Saved queries and plots

Also `core/models.py`, also graph-scoped. One kind: the **table** query.

| Table | Means | Where |
|---|---|---|
| `GraphQuery` (proxy `GraphTableQuery`) | A saved table query. Its **plan** — `graph_engine.query_ir.TableQueryPlan`: matches, wheres, returns, columns — is the contract a client writes and reads back; each projection kind compiles it (`Projector.render_table`). the `query` read-back field is gone with Cypher; a **legacy** row (plan null, raw Cypher stored) cannot render at all, and `manage.py list_legacy_queries` names it so it can be rebuilt | `core.GraphQuery` |
| `ScatterPlot` | Chart configuration over one table query's columns | `core.ScatterPlot` |

> `NodeQuery`, `EdgeQuery`, their proxies, and the `NODES` / `PATH` / `PAIRS` kinds
> had mutations and types but **no execution path anywhere**; they are gone. A new
> shape comes back as a plan kind.

---

## 3. Projection — what the view looks like, drawn

Drawn vertices and edges — rows of the projection tables — plus the derived properties on them. **Entirely
rebuildable**: `manage.py reproject` drops and replays it from evidence + schema.
Nothing here is a source of truth.

### The seam

| Word | Means | Where |
|---|---|---|
| `Projector` | The **protocol** one projection kind implements: a writer half (`draw_node`, `draw_edge`, `write_properties`, `erase_nodes`, `refresh_namespace`/`drop_namespace`, …) and a reader half (`drawn_nodes`, `drawn_edge`, `list_drawn`, `render_table`). Phrased in refs, labels and property dicts — no query language | `graph_engine/projection/protocol.py` |
| *namespace* | The per-graph Postgres schema (named by the *handle*) holding one view per node category, one per admitted endpoint pair, and one SQL/PGQ property graph — **derived** from the `Category` rows by `refresh_namespace`, droppable and rebuilt wholesale (RFC 0006). What `GRAPH_TABLE` queries; the schema's shape of the drawing, not a mirror of it | `graph_engine/namespace.py` (spec), `projection/table.py` (DDL) |
| `TableProjector` | The Postgres-table implementation, and the **only** module that reads or writes the projection tables | `graph_engine/projection/table.py` |
| `current_projector` | Which projector the operation draws through — bound per GraphQL operation by `api/extensions/projection.py`, read by `get_controller()`, the commands and the `pre_delete` signal | `graph_engine/projection/context.py` |

`graph_engine/projector.py` decides *what* to draw and never says how; `GraphController`
holds a `projector`, not an engine, and runs no query itself
(`tests/projector/test_projector_protocol.py` keeps both true). A second projection
kind — a per-view table — implements `Projector` and is chosen in `api/schema.py`.

### The bookkeeping

| Word | Means | Where |
|---|---|---|
| `Projection` | One view's drawing and its standing relative to the log: `status` (`consistent` / `needs_backfill` / `rebuilding`), `schema_hash` it was last fully derived under, `derived_at`, `rebuilt_at`, `kind` | `graph_engine.models.Projection` |
| `PendingProjection` | The **outbox**: an assertion whose synchronous projection has not finished. Written in the evidence transaction; deleted **by id only** by the write that drew it or by an org-wide replay that applied it | `graph_engine.models.PendingProjection` |
| *cursor* (`projectedThroughSeq`) | `min(min_pending_seq − 1, max_seq)` for a consistent graph, 0 otherwise. **Derived, never stored.** Every committed assertion at or below it is drawn | `graph_engine/watermark.py` |
| *lag* | `max_seq − cursor` | `watermark.position` |
| *handle* | `Graph.age_name` — random (`g` + 32 hex), internal. Since RFC 0006 it names the graph's *namespace* schema — a name for output only. Never an address: `graph:` is a primary key | `core.models.new_projection_handle` |

### What actually gets drawn

`projector.create_vertex` writes exactly `{id, category_ids, type}` and labels the
vertex with the `age_name` of **every** category that admits it, one
`ProjectionLabel` row each (RFC 0019). Everything else on it is derived. Since RFC 0018 a
vertex stands for an **individual** — every instance in one view-scoped sameness
component — and `ProjectionMember` lists them; `id` is the lowest member.

| Concept | Drawn? | Why |
|---|---|---|
| `Instance` (entity, natural event, protocol event) | **yes**, one vertex per **individual** — several instances the view's sameness claims join share one, listed on `ProjectionMember` | |
| `Link` of kind `RELATION`, `PARTICIPATES_AS_*` | **yes**, a drawn edge | |
| `Link` of kind `MEASUREMENT`, `STRUCTURE_RELATION` | **no** | endpoints have no vertex, or nothing projects it |
| `Link` of kind `INFORMS`, `CLASSIFIES`, `SAME_AS`, `DIFFERENT_FROM` | **no** | read from evidence directly |
| `Structure`, `Metric`, `Assertion`, `Comment` | **no** | evidence rows with no drawn presence at all |

### Vertex properties

| Property | Written by | Meaning |
|---|---|---|
| `id` | `create_vertex` | the individual's **representative**: the lowest member uuid, an `Instance` id. `Node.id` reports it, and `node(id: <any member>)` finds the vertex |
| `category_ids` | `create_vertex` | the `core.Category` pks this view drew it under, sorted — one per label. A predicate on it asks whether a value is *among* them |
| `type` | `create_vertex` | from `Instance.kind`. **The claim's own account**, never inferred from the label |
| `__schema_version`, `__measured__*` | `project` | derived; the `__` prefix is the projection layer's own encoding (`__last_derived` is no longer written — "when was this view derived" is `Projection.derived_at`) |
| everything else | `project` / `rollup` | derived properties from the category's rules |

> A vertex's **labels** are its categories' `age_name`s — one view's private renames
> of words ("Cell", "Mitosis"); a node holds every one that admits it. A label is
> *not* a type discriminator. Reading kind off the
> label is the defect `VocabNodeTypeMap` was deleted for.
>
> The drawing's **vertex id** is reassigned by every reproject and is never the
> identity. `RetrievedNode.vertex_id` is named for what it is so the name prevents
> the confusion.

### In-memory reading shapes

`graph_engine/retrieved.py` — adapters, not tables. A `Retrieved*` may be built
from a vertex **or** from an evidence row.

| Shape | Built from | Note |
|---|---|---|
| `RetrievedNode` | a vertex (`from_node`) or a row (`from_row`) | spans both grains; `unique_id` is the identity either way, `members` the instances it stands for (one, itself, when row-backed) |
| `RetrievedEdge` | **always** a row (`from_link`) | every edge the API builds is row-backed |
| `RetrievedStructure`, `RetrievedMetric` | rows only | `RetrievedNode` subclasses, but their GraphQL types implement no interface |
| `RetrievedVariable` | query renders | |

### Drawings

| Word | Means | Where |
|---|---|---|
| *drawing* | How **one view** draws one claim under **one category**: a vertex or an edge, and the category it drew it under. A node several categories admit has one drawing per category, on one vertex (RFC 0019) | `graph_engine/results.py` |
| `NodeDrawing` / `EdgeDrawing` | The two drawing shapes | `results.NodeDrawing`, `results.EdgeDrawing` |
| `Asserted` | What a write returns: the assertion, the claim, and **every** view that draws it — empty when none does | `results.Asserted` |

`drawings` being a **list** rather than a flag is the point: a claim several views
draw reports all of them, and "no view declares this word" is a count of zero
rather than a null. There is no `lifecycle` field anywhere — a node in a graph is
one the evidence says exists, so a flag beside it could only agree with its own
presence.

---

## 4. API surface — GraphQL shapes

These name a **response shape**, not a table. Nothing here is stored.

| Word | Means |
|---|---|
| `Node` | Interface for **one `Instance` row, typed by kind** — `Entity`, `NaturalEvent`, `ProtocolEvent`, exactly `Instance.Kind`'s three values |
| `Edge` | Interface for **one `Link` row, typed by kind** — exactly `Link.Kind`'s eight values. **Not** "drawable": several kinds are never projected |
| `Entity` | An instance that is **not an event**. Never means "any node" |
| `Structure`, `Metric` | Claim shapes. Implement **neither** interface — they are rows of different tables, not instances |
| `Instance`, `Link` | The **claim-grain** readers, served as the evidence row itself |
| `Asserted*` | What a write returns — `AssertedEntity`, `AssertedInstances`, `AssertedLinks`, … |
| `Standing` (GraphQL) | One position on a claim: `stands`, when, and whose |
| `ClaimEndpoint` | Union for either end of a `Link`: `Instance \| Structure \| Link \| Term` |
| `InformsTarget` | What a structure is evidence *for*: a node, or another claim |

### Grain: which reads answer at which layer

Two surfaces, never mixed silently (RFC 0025). **The log surface** — `Instance`, `Link`,
`Metric`, `Structure`, `Assertion`, `Standing`, `changes`, and every edge's `source`/`target`
— is exact, complete and never stale. **The view surface** — `Node` and its subtypes,
`nodes(graph:)`, `node(id:, graph:)`, a write's `drawings`, `renderGraphTable` — is one view's
fold of the log as of its cursor: every `Node` names its `graph`, its `asOfSeq`, and the
`claim` beneath it, and answers its categories from the view's rule. A reading with no view is
an `Instance`, never a `Node`. Identity is the view's (`Graph.samenessRule`, RFC 0024); a datum
is an individual with an external identity (RFC 0023); a claim is drawn under every category
that admits it, edges included (RFC 0021).

| Grain | Scope | Fields |
|---|---|---|
| **claim** | organization | `instance(id:)`, `link(id:)`, `standings(id:)`, `structure(id:)`, `metric(id:)`, `terms`, `structureKinds`, `metricKinds`, and every edge singular |
| **view** | one graph | `node(id:, graph:)`, `nodes(graph:)`, `entity(id:, graph:)`, `inputParticipations(graph:)`, … |

A singular fetcher that takes `graph:` is view-grain and **refuses** a node that
view does not admit; the claim-grain reader for the same row is `instance(id:)`.

---

## Three consequences, each of which was a bug before the words were separated

- **`Node` is graph-facing only.** `evidence.Instance` is narrower (no structures,
  no metrics) and a drawn vertex is narrower still. `RetrievedNode` spans all of
  it, so its vertex-only fields are named for what they are.
- **"Entity" never means "any node".** It used to, in ~108 identifiers. Those are
  `instance_refs`, `RetrievedNode` and `instance_refs_informed_by` now.
- **A `Standing` is not a claim.** `retractLinks` takes `Link` ids; it was
  `retractClaims`, which named neither the table it reads nor the one a retraction
  writes.

## Where identity lives

**Every id in the API is a bare uuid**, and it is the evidence row's primary key.
There is no composite form, no `GraphID` scalar, and never the drawing's vertex id.

| Thing | Its id |
|---|---|
| `Instance`, `Link`, `Structure`, `Metric`, `Comment`, `Assertion` | evidence primary key (uuid) |
| `Graph`, `Category`, `GraphSchema`, saved queries, `ScatterPlot` | Django integer pk |
| a `Graph`'s drawing | the `graph` key on the projection rows (`Graph.age_name` is a vestigial handle) — **not** an address; `graph:` takes the pk |
| a drawn vertex | **has none that survives** — reassigned by every reproject |

## See also

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — how the layers fit together
- [`LOG.md`](LOG.md) — what the append-only log records, and which operation writes which claim
- [`REMATERIALIZATION.md`](REMATERIALIZATION.md) — what redraws a projection when a category's properties change
- [`BIOLOGIST.md`](BIOLOGIST.md) — the domain rationale for the evidence/provenance model
- [`rfcs/`](rfcs/README.md) — open design questions. **Check the status line** before acting on one
