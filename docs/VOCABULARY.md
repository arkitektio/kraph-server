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
| **Projection** | *What does that view look like, drawn?* | Apache AGE + derived columns | **Yes.** `manage.py reproject` rebuilds it from the other two. |

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
| *claim* | Any **recorded statement**. A prose word covering `Instance`, `Link`, `Metric`, `Structure` and `Comment` — not a table | — |
| `Instance` | A claimed **individual**: `entity`, `natural_event` or `protocol_event`. Every observation mints its own | `evidence.Instance` |
| `Link` | A claim **relating two things**. Eight kinds: `RELATION`, `SAME_AS`, `CLASSIFIES`, `INFORMS`, `MEASUREMENT`, `STRUCTURE_RELATION`, `PARTICIPATES_AS_INPUT`, `PARTICIPATES_AS_OUTPUT` | `evidence.Link` |
| `Structure` | A pointer to an **external datum**, identified by `(identifier, object)` — an ROI, an image, a file. Never itself claimed to be an AIS | `evidence.Structure` |
| `Metric` | A **measured value** about a structure | `evidence.Metric` |
| `Comment` | A **remark** about a structure, with a threaded reply tree | `evidence.Comment` |

### Position on a claim

| Word | Means | Where |
|---|---|---|
| `Standing` | Somebody's **position** on whether a claim still holds (`stands=True/False`). Retraction and attestation both write one | `evidence.Standing` |
| `CurrentStanding` | The folded answer, a **cache** over `Standing`. Holds **no row for an instance** — whether an instance exists has no organization-wide answer, because a graph's selector decides whose claims it counts | `evidence.CurrentStanding` |

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

### Folded from evidence (caches, rebuildable)

Sit in the evidence app but are **derived**, so they belong with the projection
conceptually: each has a `--check`able rebuild.

| Word | Means | Rebuild |
|---|---|---|
| `InstanceIdentity` | Components folded from `SAME_AS` claims. Organization grain, lowest uuid as representative; **only merged nodes get a row** | `manage.py rebuild_identity [--check]` |
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
| `Graph` | A **view** over the organization's claims, with a `selector` saying which ones count. Not a container — a reconstruction | `core.Graph` |
| `Category` | One **view's rule for a word**: its `age_name` (the AGE label), `definition`, derivation rules, layout, colour. `Category.term` is the join to the evidence layer | `core.Category` |
| `GraphSchema` | A **versioned, immutable** schema definition. Each graph has one active at a time; `index` increments | `core.GraphSchema` |
| `CategoryAssertedTerm` | The **joinable half** of `Category.definition` — which words a category *derives* from, normalized out of JSON. Stores the **key**, not a `Term` FK, because a definition routinely names a word nobody has minted | `core.CategoryAssertedTerm` |
| `GraphOntology` / `OntologyReference` | External ontology bindings (PURLs) for a graph and its categories | `core.GraphOntology`, `core.OntologyReference` |

`Category` is **one concrete table** with a `kind` column. The old
multi-table-inheritance class names survive as Django **proxies**:

- node categories — `EntityCategory`, `NaturalEventCategory`, `ProtocolEventCategory`, `ReagentCategory`
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

Also `core/models.py`, also graph-scoped, and also `kind`-discriminated proxies
over three tables:

| Table | Proxies |
|---|---|
| `GraphQuery` | `GraphNodesQuery`, `GraphTableQuery`, `GraphPairsQuery`, `GraphPathQuery` |
| `NodeQuery` | `NodeTableQuery`, `NodePairsQuery`, `NodePathQuery` |
| `EdgeQuery` | `EdgeTableQuery`, `EdgePairsQuery`, `EdgePathQuery` |
| `ScatterPlot` | — (reaches an organization only through its query FKs) |

---

## 3. Projection — what the view looks like, drawn

Apache AGE vertices and edges, plus the derived properties on them. **Entirely
rebuildable**: `manage.py reproject` drops and replays it from evidence + schema.
Nothing here is a source of truth.

### What actually gets drawn

`projector.create_vertex` writes exactly `{id, category_id, type}` and labels the
vertex with `category.age_name`. Everything else on it is derived.

| Concept | Drawn? | Why |
|---|---|---|
| `Instance` (entity, natural event, protocol event) | **yes**, one vertex each | |
| `Link` of kind `RELATION`, `PARTICIPATES_AS_*` | **yes**, an AGE edge | |
| `Link` of kind `MEASUREMENT`, `STRUCTURE_RELATION` | **no** | endpoints have no vertex, or nothing projects it |
| `Link` of kind `INFORMS`, `CLASSIFIES`, `SAME_AS` | **no** | read from evidence directly |
| `Structure`, `Metric`, `Assertion`, `Comment` | **no** | Postgres rows with no AGE presence at all |

### Vertex properties

| Property | Written by | Meaning |
|---|---|---|
| `id` | `create_vertex` | the `Instance` uuid — **the identity** |
| `category_id` | `create_vertex` | the `core.Category` pk this view drew it under |
| `type` | `create_vertex` | from `Instance.kind`. **The claim's own account**, never inferred from the label |
| `__schema_version`, `__last_derived`, `__measured__*` | `project` | derived; the `__` prefix marks them internal |
| everything else | `project` / `rollup` | derived properties from the category's rules |

> A vertex's **label** is `category.age_name` — one view's private rename of a
> word ("Cell", "Mitosis"). It is *not* a type discriminator. Reading kind off the
> label is the defect `VocabNodeTypeMap` was deleted for.
>
> The AGE **vertex id** is reassigned by every reproject and is never the
> identity. `RetrievedNode.vertex_id` is named for what it is so the name prevents
> the confusion.

### In-memory reading shapes

`graph_engine/retrieved.py` — adapters, not tables. A `Retrieved*` may be built
from a vertex **or** from an evidence row.

| Shape | Built from | Note |
|---|---|---|
| `RetrievedNode` | a vertex (`from_node`) or a row (`from_row`) | spans both grains; `unique_id` is the identity either way |
| `RetrievedEdge` | **always** a row (`from_link`) | every edge the API builds is row-backed |
| `RetrievedStructure`, `RetrievedMetric` | rows only | `RetrievedNode` subclasses, but their GraphQL types implement no interface |
| `RetrievedVariable` | query renders | |

> `RetrievedRelation`, `RetrievedInforms`, `RetrievedDescribes`, `RetrievedAsserts`,
> `RetrievedReifiesAsSource` and `RetrievedEvent` are **constructed nowhere**.
> They are leftovers from the design in which provenance was an AGE edge.

### Drawings

| Word | Means | Where |
|---|---|---|
| *drawing* | How **one view** draws one claim: a vertex or an edge, and the category it drew it under | `graph_engine/results.py` |
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

| Grain | Scope | Fields |
|---|---|---|
| **claim** | organization | `instance(id:)`, `link(id:)`, `standings(id:)`, `structure(id:)`, `metric(id:)`, `terms`, `structureKinds`, `metricKinds`, and every edge singular |
| **view** | one graph | `node(id:, graph:)`, `nodes(graph:)`, `entity(id:, graph:)`, `inputParticipations(graph:)`, … |

A singular fetcher that takes `graph:` is view-grain and **refuses** a node that
view does not admit; the claim-grain reader for the same row is `instance(id:)`.

---

## Three consequences, each of which was a bug before the words were separated

- **`Node` is graph-facing only.** `evidence.Instance` is narrower (no structures,
  no metrics) and an AGE vertex is narrower still. `RetrievedNode` spans all of
  it, so its vertex-only fields are named for what they are.
- **"Entity" never means "any node".** It used to, in ~108 identifiers. Those are
  `instance_refs`, `RetrievedNode` and `instance_refs_informed_by` now.
- **A `Standing` is not a claim.** `retractLinks` takes `Link` ids; it was
  `retractClaims`, which named neither the table it reads nor the one a retraction
  writes.

## Where identity lives

**Every id in the API is a bare uuid**, and it is the evidence row's primary key.
There is no composite form, no `GraphID` scalar, and never the AGE vertex id.

| Thing | Its id |
|---|---|
| `Instance`, `Link`, `Structure`, `Metric`, `Comment`, `Assertion` | evidence primary key (uuid) |
| `Graph`, `Category`, `GraphSchema`, saved queries, `ScatterPlot` | Django integer pk |
| an AGE vertex | **has none that survives** — reassigned by every reproject |

## See also

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — how the layers fit together
- [`LOG.md`](LOG.md) — what the append-only log records, and which operation writes which claim
- [`REMATERIALIZATION.md`](REMATERIALIZATION.md) — what redraws a projection when a category's properties change
- [`BIOLOGIST.md`](BIOLOGIST.md) — the domain rationale for the evidence/provenance model
- [`rfcs/`](rfcs/README.md) — open design questions. **Check the status line** before acting on one
