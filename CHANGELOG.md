# CHANGELOG


## v1.0.0-rc.11 (2026-09-01)

### Features

- Removal of age preparing for new postges 19
  ([`137a5b4`](https://github.com/arkitektio/kraph-server/commit/137a5b415d5e77f13b281f0fc53ddbb9e8d0580b))


## v1.0.0-rc.10 (2026-08-21)


## v1.0.0-rc.9 (2026-08-21)

### Bug Fixes

- Authentikate 4
  ([`d2a7504`](https://github.com/arkitektio/kraph-server/commit/d2a75041ef14f29196de8f401dca55c014e4d59d))

- Some filters
  ([`70816c2`](https://github.com/arkitektio/kraph-server/commit/70816c2c88634ed43ccaf7386c1f53d6d970af24))


## v1.0.0-rc.8 (2026-08-20)

### Bug Fixes

- Auhentikate
  ([`ee29ed9`](https://github.com/arkitektio/kraph-server/commit/ee29ed971eff71223025527cf43c4fca85b53b0a))


## v1.0.0-rc.7 (2026-08-20)

### Bug Fixes

- A view's rule admits words of its own kind, and lists dispatch on the claim's kind
  ([`f2713f5`](https://github.com/arkitektio/kraph-server/commit/f2713f506e4c1ac7b6384f8be4a31257193a5987))

`Term` identity is `(organization, kind, key)`, so "Mitosis" the natural-event word and "Mitosis"
  the entity word are two terms — but `selector.term_ids_for`'s derived half and
  `resolve_categories`' per-definition match compared keys alone, so an `EntityCategory` defined as
  `asserted_as: ["Mitosis"]` admitted every event classified under the event word, and the
  category-scoped plural lists (`entities()`, `naturalEvents()`, `protocolEvents()`,
  `Category.entities`) wrapped whatever came back in the list's own type. Same defect class the
  label-to-kind map was deleted for, reached through a constructor.

`CategoryAssertedTerm` now yields `(key, kind)` pairs (`keys_and_kinds_for_graph`) and both matches
  join on the deriving category's kind; the plural lists dispatch through
  `cast_node_to_graphql_type` like every singular read already did.

Also restates the "more than one definition matches" refusal as the view's policy — a view draws
  each node under exactly one category — rather than as a consequence of Apache AGE allowing one
  label per vertex. Behaviour unchanged.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

### Documentation

- The projection layer as it is now — seam, bookkeeping, plans; RFC 0004
  ([`2912912`](https://github.com/arkitektio/kraph-server/commit/2912912b19d05d12284eaa99090c667af36d938d))

REMATERIALIZATION.md stops saying "a read is a graph query and nothing else" (properties are;
  membership is the rule) and describes the Postgres `schema_hash` ledger; LOG.md closes the
  late-commit `seq` gap (outbox + derived cursor); VOCABULARY.md §3 gains the seam (`Projector`,
  `CypherProjector`, `current_projector`), the bookkeeping (`Projection`, `PendingProjection`,
  cursor, handle) and the saved-query plan; ARCHITECTURE.md's header names what it predates;
  CLAUDE.md's engine/extension/insights bullets are rewritten.
  `docs/rfcs/0004-the-graph-is-a-projection.md` is the record of the audit and of what shipped and
  what was deliberately left.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

### Features

- Projection bookkeeping — outbox, a safe cursor, and `reproject --incremental`
  ([`507161c`](https://github.com/arkitektio/kraph-server/commit/507161cef4e92afad50395106947c2219ff24fd5))

The projection had no record of how far along the log it was. Three facts lived only on vertices:
  which schema a drawing was derived under (`rematerialize --stale` counted vertex stamps in Cypher
  — the ledger inside the cache it audited, destroyed by the `reproject` that fixes it),
  `__last_derived` (a wall-clock millisecond, the one projected value a rebuild could not
  reproduce), and whether a write's projection had actually finished (it had not, if the process
  died between the evidence commit and the drawing — and nothing knew).

`graph_engine.models.Projection` — one row per view, status / schema_hash / derived_at / rebuilt_at
  — and `PendingProjection`, an outbox row written in the evidence transaction by
  `_create_assertion` and deleted **by id only** by the write that drew it (`_settle`) or by an
  org-wide replay that applied it. The cursor is *derived* from the outbox, never stored
  (`graph_engine/watermark.py`): `min(min_pending_seq - 1, max_seq)` for a consistent graph, 0 for
  one that is `NEEDS_BACKFILL` or mid-`REBUILDING`. That makes it safe against both things a bare
  `seq > N` scan cannot see — an uncommitted lower seq and a commit-then-crash — which the first
  design (a stored per-graph cursor advanced per write, swept by seq) was not.

`manage.py reproject --incremental --organization <slug> | --all` applies the outstanding assertions
  to every consistent graph of the organization by converging the touched refs, and settles exactly
  the rows it read; `--dry-run` prints every cursor. Full drop-and-replay marks `REBUILDING` before
  the drop and refolds `CategoryAssertedTerm` / flagged identity components / `CurrentStanding`
  before it reads them. `create_vertex` is `MERGE` and `reproject_node` clears first, so every
  per-node draw converges — `attest_node` on a standing node and `project_all` over a populated
  namespace no longer duplicate vertices. `rematerialize --stale` reads `Projection.schema_hash`
  from Postgres.

`Graph.projection { status projectedThroughSeq lag pending schemaStale … }` exposes it;
  `Assertion.seq` was already there, so a client can tell whether a view has drawn its write.

BREAKING CHANGE: `Node.lastDerived` is deprecated and always null; `__last_derived` is no longer
  stamped on vertices.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

- Saved queries are plans, compiled per projection kind — raw Cypher leaves the contract
  ([`662cc6e`](https://github.com/arkitektio/kraph-server/commit/662cc6e72d7ae5a28d732db12a4d306925bec20f))

A saved table query was a Cypher string the client wrote (or the builder wrote and handed back),
  stored verbatim and executed by `renderGraphTable` with the render filter regex-spliced before its
  last `RETURN` — wrong for `WITH`, `UNION` and exactly the aliased columns a client filters on. The
  query language was the public contract (`CypherLiteral` on thirteen output positions), the
  builder's neutral IR was written by one mutation and readable by no field (`builderArgs` raised on
  select), and eight of the nine saved-query kinds had mutations, types and filters but no execution
  path anywhere.

`GraphQuery.plan` — `graph_engine/query_ir.py::TableQueryPlan`: matches, wheres, returns, columns —
  is the contract now: `createGraphTableQuery(input: {plan: …})`, read back as `plan`, compiled by
  the projection kind in use through `Projector.render_table` (`CypherProjector` emits `MATCH … WITH
  … WHERE … RETURN` with every value a parameter and render filters on returned aliases; a second
  projection kind compiles the same plan to something else). `query` is the compiled form, read-only
  and deprecated. A **legacy** row saved as raw Cypher still renders but takes no filter/order/page;
  `manage.py list_legacy_queries` names them. `createGraphTableQueryThroughBuilder` stays one
  release as an alias that stores a plan. `NodeQuery`, `EdgeQuery`, their proxies and the
  NODES/PATH/PAIRS kinds are removed with their rows (migration `core 0011`); `ScatterPlot` is over
  one graph table query and its `label` field resolves. `WhereClauseInput.value` and
  `RenderGraphTableFilter.value` are JSON values, not Cypher literals; the second, disagreeing
  `WhereOperator` enum is gone.

BREAKING CHANGE: `createGraphTableQuery`/`updateGraphTableQuery` take `plan` and no `query`;
  `GraphTableQuery.builderArgs` is removed; `query` is deprecated on `GraphQuery`; the 32
  node/edge/pairs/path saved-query mutations and their queries, types, inputs and filters are
  removed; `RenderGraphTableFilter.search` is removed and `operator` is typed.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

- The graph's AGE handle is random and internal; `graph:` is a primary key
  ([`d752a91`](https://github.com/arkitektio/kraph-server/commit/d752a91fe4eb3be2c273cf06fcbb50ead0723d5d))

`Graph.age_name` was `{name}_{org_slug}` with a counter: derived from user input, interpolated
  unescaped into `cypher('…')` / `create_graph('…')` with an `isalnum()` filter in another module as
  the only defence, deduplicated per organization against a globally unique column, and — through
  `get_accessible_graph` — the public address of a view, resolved *unscoped*.

It is `g` + 32 hex now (`core.models.new_projection_handle`), assigned by the model default, never
  accepted as input, read only by the engine through `GraphProtocol.get_age_name()`. `graph:`
  arguments resolve by primary key, scoped to the caller's organization; the category-scoped lists
  authorize against the organization first like `relations()` already did. `GraphManager`,
  `GraphName`, `SimpleGraph` and `Graph.create_age_name` are gone; the projection commands name a
  graph by id or name (ambiguous names refused) and print `name (#pk)`.

`Graph.ageName` stays in the SDL, read-only, described as internal.

BREAKING CHANGE: `graph:` no longer accepts a graph's `age_name` string; pass the graph id. Log
  lines and command output identify graphs by name and id.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

### Refactoring

- Name the projection seam — `Projector`, and a controller that runs no query
  ([`ad1023d`](https://github.com/arkitektio/kraph-server/commit/ad1023d853cc3b4b0572aca914a9eabd97459524))

The projector was a module of free functions duck-typed on `controller.engine` and a private Cypher
  validator; the controller executed Cypher at seven sites of its own, two of them writes; the API,
  the commands and `materialize` each held an engine; and the ContextVar was named for the query
  language. Nothing named the seam a second projection kind would implement.

`graph_engine/projection/protocol.py::Projector` is that seam — a writer half (`draw_node`,
  `draw_edge`, `write_properties`, `clear_properties`, `erase_nodes`, `erase_edge`, namespaces,
  `validate_key`) and a reader half (`drawn_nodes`, `drawn_edge`, `list_drawn`, `render`), phrased
  in refs, labels and property dicts. `projection/cypher.py::CypherProjector` is the Apache AGE
  implementation and the only module that emits Cypher for a drawing. `graph_engine/projector.py`
  decides what to draw and calls `controller.projector.*`; `GraphController` holds a projector,
  never an engine, and runs no query (`test_projector_protocol.py` enforces both by reading the
  source). `api/extensions/projection.py` binds one per operation through
  `graph_engine/projection/context.py::current_projector`, with `current_or_default()` replacing
  four copies of the management commands' engine fallback. `GraphController(engine=…)` and
  `materialize(engine=…)` still accept an engine and wrap it.

Also: a write's `drawings` now report the **rule's** category (`resolve_categories`) and log when
  the vertex stamp disagrees, instead of reading the cache back as authoritative;
  `RetrievedNode`/`RetrievedEdge` hash and compare on `(graph_name, unique_id)`, so two undrawn
  nodes are two objects; a `pre_delete` signal drops a graph's namespace on every deletion path, not
  only the `deleteGraph` mutation; `Node.label`'s description says what it is.

BREAKING CHANGE: `api.extensions.cypher` (`CypherEngineExtension`, `cypher_engine`,
  `get_current_cypher_engine`) is gone; `create_schema` takes `projector=` (or `cypher_engine=` to
  wrap one).

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

### Breaking Changes

- `api.extensions.cypher` (`CypherEngineExtension`, `cypher_engine`, `get_current_cypher_engine`) is
  gone; `create_schema` takes `projector=` (or `cypher_engine=` to wrap one).

- `creategraphtablequery`/`updategraphtablequery` take `plan` and no `query`;
  `GraphTableQuery.builderArgs` is removed; `query` is deprecated on `GraphQuery`; the 32
  node/edge/pairs/path saved-query mutations and their queries, types, inputs and filters are
  removed; `RenderGraphTableFilter.search` is removed and `operator` is typed.


## v1.0.0-rc.6 (2026-08-18)


## v1.0.0-rc.5 (2026-08-17)

### Features

- More domain specific adaptions
  ([`0fa921b`](https://github.com/arkitektio/kraph-server/commit/0fa921b32fd931bd7684fb1210198448f325729d))


## v1.0.0-rc.4 (2026-08-17)

### Bug Fixes

- Honest arguments and descriptions across the API surface
  ([`d8edb76`](https://github.com/arkitektio/kraph-server/commit/d8edb76c28c6e7be8cdb3e5b0e762777dedf0b11))

The cleanup pass deferred from the grain-separation change — every item is a place where the schema
  said something the resolvers did not do:

- Advertised-but-refused filters are gone from the schema: hasProperty/ search/matches leave the
  node and edge filter inputs (every resolver refused them at runtime; the runtime guards stay as a
  backstop for internal pydantic callers), and property/category ordering leaves the node, edge and
  structure order inputs — it raised on node lists, was silently dropped on edge lists, and was
  silently reinterpreted as ordering by `object` on structures. StructureFilter keeps all three
  fields because `structures` genuinely honors them over Metric rows. EntityOrder.property survives
  at the pydantic layer for the drawing-scoped list_entities_for_category. - The vocabulary lists
  stop ignoring their arguments: terms/structureKinds/ metricKinds now apply their filters and
  pagination, and drop the ordering argument nothing ever wired (the order is canonical). TermOrder,
  StructureKindOrder, MetricKindOrder, MetricFilter, MetricPaginationInput and the PropertyOrder
  input leave the schema with their last references. - Descriptions stop teaching the removed model:
  nine root fields no longer say "composite graph ID" (and the last `split(":")` composite parse is
  gone from the structures filter); retract* inputs no longer describe themselves as "archiving
  (soft deleting)"; AttestNodeInput no longer references the removed archive* family; classification
  inputs say "word" where the field is term; participation roles are the caller's own word, not "as
  the event's category names it". - The Event interface is no longer described as "Interface for
  edges that track schema version and derivation time"; EventKind says what it is
  (intrinsic/extrinsic to the sample) instead of three conflicting accounts; Graph fields stop
  calling the graph "the category"; six edge descriptor fields and four render types lose their
  copy-pasted descriptions. - Vestigial code goes: LinkStructureResult (the last copy of the removed
  view-grain write-payload shape), the EdgeType literal now lists exactly the eight producible
  Link.Kind values instead of four impossible ones, and the RetrievedEdge "Assertion Properties"
  accessors for an edge type nothing can produce are deleted.

BREAKING CHANGE: hasProperty, search and matches are removed from the entity/node/event/edge filter
  inputs (they were runtime errors on every call); property and category are removed from the
  node/edge/structure order inputs; the terms/structureKinds/metricKinds ordering argument and the
  TermOrder/StructureKindOrder/MetricKindOrder/MetricFilter/ MetricPaginationInput/PropertyOrder
  inputs are removed (they were silent no-ops); terms/structureKinds/metricKinds now actually apply
  filters and pagination.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

### Features

- Comments on structures, as evidence
  ([`6026a07`](https://github.com/arkitektio/kraph-server/commit/6026a07c96a63086025d8705d1c9b6f36416a3aa))

The port of lok's komment app into the evidence model, so lok can carry its comments here: a Comment
  is a claim about a Structure — lok addresses a comment by (identifier, object), which is exactly a
  structure's identity — and the structure carries the thread, so the same ROI discussed from two
  experiments is one conversation.

What lok kept as mutable state arrives as appended rows:

- evidence.Comment: organization-scoped, append-only (the 0005 trigger is extended to it), assertion
  as author+time, parent FK for threading (PROTECT where lok cascades), and the rich descendant tree
  (LEAF/MENTION/PARAGRAPH) stored flat in one JSON column on the one row — never as rows or vertices
  of its own. text and mentions are folded from the tree at write time, because an append-only row
  has no after-the-fact to derive them in. A mention names a subject (Assertion.subject's
  vocabulary), never a user row. - Resolution is a Standing: retractComment says the remark no
  longer stands — resolved by a reviewer or withdrawn by its author, the standing's own assertion
  recording whose position it was (lok's resolved_by, as provenance) — and attestComment reopens it.
  Comments join CACHED_TARGETS, so CurrentStanding folds and refold_current replays them;
  Comment.resolved is the fold, honest at organization grain. - Writes follow the house shape:
  commentOnStructure takes (identifier, object, descendants, parent) and mints the structure if the
  datum is new, as one act under one assertion — the same shape as assertMetricValue — returning
  AssertedComment (assertion + comment, no drawings: a structure has no AGE presence, so neither
  does its discussion). The two mutations lok left as NotImplementedError arrive as what they were
  underneath: a reply is a comment naming parent (validated onto the parent's thread),
  resolveComment is retractComment. - Reads mirror lok's: comment(id:), commentsFor(identifier:,
  object:), myMentions, plus Structure.comments; threading via parent/replies; the descendant tree
  is served through a Descendant interface with Leaf/Mention/Paragraph types, shape-compatible with
  lok's.

No notify flag: kraph has no notification channel, and accepting a flag that does nothing is the
  silent no-op this API keeps removing.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

- More features about the grpah
  ([`3f97802`](https://github.com/arkitektio/kraph-server/commit/3f9780218cd761b7d6e2387acda9a0631fd169b5))

- More features that bridge the graph
  ([`62ee0c5`](https://github.com/arkitektio/kraph-server/commit/62ee0c5b7750e666fe2b3f980308e84d4b74f844))

- Separate claim-grain and view-grain reads on the API surface
  ([`1599b95`](https://github.com/arkitektio/kraph-server/commit/1599b95367af861a5e46941d6afb7c43803ac5d0))

The read side leaked view-grain shapes over claim-grain answers, with the grain switch invisible to
  clients. Five structural fixes, one act:

- Singular node fetchers name their view: node/entity/naturalEvent/ protocolEvent take a required
  graph argument and go through the same membership-then-drawing path as nodes(graph:) —
  admitted-but-undrawn answers as the bare row shape, a node the view does not admit is refused, and
  instance(id:) is the claim-grain reader. projected_instance (which answered from drawings[0], an
  arbitrary view) and get_node are deleted. - Structure and Metric are claims, not Node subtypes:
  neither has any AGE presence, so the inherited label ("the AGE graph label as recently
  materialized", actually a hard-coded constant) and the always-null externalId are gone; both are
  standalone types with their own id: ID!. NodeSubtype is exactly Instance.Kind's three values now.
  - Honest Edge shape: every edge the API builds is row-backed, so Edge.assertion is non-null, and
  the structurally-empty properties/richProperties/measuredFrom/measuredTo fields are removed from
  Relation, StructureRelation and Measurement. - One uuid, one scalar: Node.id, Edge.id and
  Edge.sourceId/targetId are ID!, matching Instance.id and Link.id/sourceRef/targetRef. - Stats
  resolvers are tenant-scoped: create_stats_type takes a required scope callable; the old
  model.objects.all() aggregated across organizations for the core models and raised
  UnscopedEvidenceAccess outright for structureKindStats/metricKindStats.

BREAKING CHANGE: node(id:), entity(id:), naturalEvent(id:) and protocolEvent(id:) require a graph
  argument; Structure and Metric no longer implement Node (label/externalId removed); Edge.assertion
  is non-null; Relation.properties/richProperties and the edge measuredFrom/measuredTo fields are
  removed; Node.id, Edge.id, Edge.sourceId and Edge.targetId are ID scalars instead of String.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

### Breaking Changes

- Hasproperty, search and matches are removed from the entity/node/event/edge filter inputs (they
  were runtime errors on every call); property and category are removed from the node/edge/structure
  order inputs; the terms/structureKinds/metricKinds ordering argument and the
  TermOrder/StructureKindOrder/MetricKindOrder/MetricFilter/ MetricPaginationInput/PropertyOrder
  inputs are removed (they were silent no-ops); terms/structureKinds/metricKinds now actually apply
  filters and pagination.


## v1.0.0-rc.3 (2026-08-15)

### Bug Fixes

- Removal of vestigal not evidence back graph writes
  ([`b8c2c5e`](https://github.com/arkitektio/kraph-server/commit/b8c2c5ed35e5801ff6de8c7b5e172873bc3ced9b))

- Remove of vestigal graph writes
  ([`077e652`](https://github.com/arkitektio/kraph-server/commit/077e6523822e54cd7a2b453d0c619b3f06ce21a4))


## v1.0.0-rc.2 (2026-08-12)

### Bug Fixes

- More projection fixes
  ([`c4ab199`](https://github.com/arkitektio/kraph-server/commit/c4ab1992bb60d490219e38612f0749d3ae3f9056))

### Features

- Ingest declares its value kind, and nothing infers
  ([`cc450ed`](https://github.com/arkitektio/kraph-server/commit/cc450edfed823a41ed768ec2efd6e5e8807dd1ef))

`ensure_metric_kind` guessed when the caller declared nothing: adopt the key's single existing term,
  infer one from `type(value)` and mint, or — with several terms — raise. That last branch was a
  dead end. Its message said "Declare one" while the inputs that reached it had no field to declare
  with: only `RecordMetricInput` carried a `value_kind`, so `createMetric`, `updateMetric` and
  supporting evidence all took the undeclared path. Once terms could differ by value kind, an
  organization with `roi.confidence` as both FLOAT and STRING could not write that key through any
  of them.

Guessing also caused an older problem on the same path: adopt-the-single-term adopted it even when
  the value could not live there, so an undeclared `"high"` against a FLOAT-only key adopted FLOAT
  and died inside `value_columns` with `could not convert string to float`.

So `value_kind` moves onto the `MetricInput` base as required, and the undeclared branch is removed
  rather than repaired. `ensure_metric_kind` is now one `get_or_create` over the four-field
  identity.

What this gives up, deliberately
  -------------------------------------------------------------------- The adopt-the-existing-term
  rule existed to stop inference forking a key into INT and FLOAT terms over `45` and `45.2`. With
  nothing inferring there is nothing to fork. A caller who declares `integer` once and `float` once
  still gets two terms — now their explicit choice, visible at the call site, and `NUMERIC_FAMILY`
  already folds the two for reads.

`infer_value_kind` is deleted, not kept as a utility: its only caller was the mint branch, and a
  guessing primitive with no caller is one the next write path reaches for. A test asserts its
  absence rather than trusting the deletion to stick.

The read side is untouched. `DerivationRule.source_value_kind` stays optional (decided with the
  user): writes being explicit means a key's terms are exactly what was declared, so the ordinary
  case is one term, and where it is not the projector already warns rather than guessing.

Errors now name the declaration --------------------------------------------------------------------
  With the kind required, a mismatch is the caller's own statement disagreeing with what they sent,
  so `value_columns` reports the key, the declared kind and the value instead of surfacing a bare
  `float()` failure that names none of them.

Verification -------------------------------------------------------------------- The load-bearing
  test was verified non-vacuous — and the first attempt at that was itself vacuous. Reverting only
  the pydantic model left the strawberry mirror intact, so the GraphQL schema still required the
  field and everything passed. Reverting both reproduces the real prior state: `Field 'valueKind' is
  not defined by type 'CreateMetricInput'`. The schema assertions are parametrized over all four
  measurement inputs so a field that goes optional again is caught, not only one that disappears.

BREAKING CHANGE: `MetricInput` gains a required `valueKind`, so `metrics: [{key, value}]` becomes
  `metrics: [{key, value, valueKind}]` on `createMetric`, `updateMetric` and every
  `supportingEvidence` metric. `writer.ensure_metric_kind` requires a value kind;
  `writer.infer_value_kind` is gone.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

### Breaking Changes

- `metricinput` gains a required `valueKind`, so `metrics: [{key, value}]` becomes `metrics: [{key,
  value, valueKind}]` on `createMetric`, `updateMetric` and every `supportingEvidence` metric.
  `writer.ensure_metric_kind` requires a value kind; `writer.infer_value_kind` is gone.


## v1.0.0-rc.1 (2026-08-12)

### Bug Fixes

- Add datalayer
  ([`801df21`](https://github.com/arkitektio/kraph-server/commit/801df213c39122b08827143884095fc97462f436))

- Add graph filter
  ([`42bbfdb`](https://github.com/arkitektio/kraph-server/commit/42bbfdb0aa8413302efff73b4b52b820fdebf219))

- Add materialize
  ([`61af15b`](https://github.com/arkitektio/kraph-server/commit/61af15b9295bf249f991acad52bf2616cc479caa))

- Add measurement stuff
  ([`f827a7f`](https://github.com/arkitektio/kraph-server/commit/f827a7f73a33b98f103295fa0a23ecbdfb8db8f1))

- Add relation
  ([`2aba7db`](https://github.com/arkitektio/kraph-server/commit/2aba7dbac28f45679b99cc6c40d8a68e4f12f974))

- Add the age words as keyword
  ([`08f8ef1`](https://github.com/arkitektio/kraph-server/commit/08f8ef1c3f7af92994fba7ec1add9d8f67968697))

- Add update entity elements
  ([`a71edc4`](https://github.com/arkitektio/kraph-server/commit/a71edc4a2948c898da42947a0a05be535da5eb68))

- Age
  ([`5c6cded`](https://github.com/arkitektio/kraph-server/commit/5c6cdedd856cb85ad02827ad61208dcaecb4fb60))

- Alles gut
  ([`2ef43d1`](https://github.com/arkitektio/kraph-server/commit/2ef43d11ad55d5b05720de4b57f04b6eded91e9e))

- Archive and delete
  ([`677993b`](https://github.com/arkitektio/kraph-server/commit/677993bdc50e7d75bb505e99e9f7640302b65b6b))

- Authentikate update
  ([`0dda413`](https://github.com/arkitektio/kraph-server/commit/0dda413427f697bc244066aa5fcd73c867b4f1cc))

- Categeotry filter
  ([`c9deac0`](https://github.com/arkitektio/kraph-server/commit/c9deac04fc73b04697d971a8b78b3a6b056188b7))

- Codex messing stuff up
  ([`9630b48`](https://github.com/arkitektio/kraph-server/commit/9630b4884343675e15b98cb49de05d413e45ab2a))

- Configuration update
  ([`2dbe735`](https://github.com/arkitektio/kraph-server/commit/2dbe7358f43f4897c9dba1e66652f764a13bb498))

- Controller
  ([`f48f181`](https://github.com/arkitektio/kraph-server/commit/f48f181793dec9c55c9388fae69858558b7056d8))

- Controller
  ([`999ec6f`](https://github.com/arkitektio/kraph-server/commit/999ec6f8bf962c105c8a2a9d4bbb5b7927712c54))

- Crud
  ([`54125d4`](https://github.com/arkitektio/kraph-server/commit/54125d4b2658317c3d879478d99528c3183b7468))

- Datalayer
  ([`bf53d9c`](https://github.com/arkitektio/kraph-server/commit/bf53d9ce146502fdaf11c2fefa4c8a5e9c95f73d))

- Datalayer
  ([`3fa0bf8`](https://github.com/arkitektio/kraph-server/commit/3fa0bf8143315df12c8070e6aef993a8f61e8f98))

- Fix measurement category
  ([`1df469f`](https://github.com/arkitektio/kraph-server/commit/1df469f40fbadade8d42e371020f55a21d72da9b))

- Frontend tests
  ([`f904346`](https://github.com/arkitektio/kraph-server/commit/f904346e63c504675c0095aaf59db65a5f0043af))

- Graph_query_stuff
  ([`187c4f6`](https://github.com/arkitektio/kraph-server/commit/187c4f6676c3c91a69d4b1ec07051c745cafb7c0))

- Graphql feature parity
  ([`b0f5f1d`](https://github.com/arkitektio/kraph-server/commit/b0f5f1d07db96ec5c005d0fa190d237ce98a53db))

- Identifier fields for structure category
  ([`016621b`](https://github.com/arkitektio/kraph-server/commit/016621b814fb795a2625e49eec7ef147b18ae0c3))

- Input models
  ([`77e7749`](https://github.com/arkitektio/kraph-server/commit/77e774949d31d087e7b6120a07809c7a6f4db721))

- Make the family read deterministic, and cover retraction across it
  ([`f423446`](https://github.com/arkitektio/kraph-server/commit/f4234464cf9990cc6e92f3e684c1840be71ac5bf))

Three follow-ups from review.

`state_for`'s queryset had no ordering, so when two terms carried metrics at the same `measured_at`,
  which one won LATEST depended on whatever order Postgres returned the rows in. Ordered by
  `value_kind`.

`combine()` was new code on the read path that no retraction test touched. Retraction still operates
  per term — `retract` finds its row by the metric's own value kind — while a numeric-family read
  spans both, so the two have to agree or an archived measurement keeps contributing to every
  combined read while looking correctly retracted in its own row. Covered, and verified non-vacuous:
  removing the pre-fold recompute leaves MAX reading the archived 60.

Third was a suspected spurious schema-version bump: `source_value_kind` defaults to None, so a
  pydantic re-serialization would emit the key where stored blobs lack it, rehashing every graph. It
  does not happen — `versioning._property_definitions` returns `category.property_definitions`
  verbatim, the stored JSON, so `compute_definition_hash` never sees a re-serialization. Only
  `materialize()` writes `model_dump()`, and that path already emits a version deliberately. No
  change needed; recorded because the absence of a bump is the non-obvious part.

Also documents that `state_for` may now return an unsaved row — `combine()` builds one rather than
  persisting a third grain over what two rows already hold, so callers read it and must not save it.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

- Make the fan-out precise, and prove it through the mutation
  ([`062e332`](https://github.com/arkitektio/kraph-server/commit/062e332813558aa0a516825c271ae9ef1184f069))

Three gaps in the previous commit.

`link_structure_to_entity` fanned out to every entity the structure informs, but linking S to E
  changes only E's statistics — the others cannot have moved, so re-deriving them was wasted work
  that also read as intent. `project_refs` now projects an exact set of refs, grouping them by
  graph, and `project_from_structures` is expressed in terms of it.

The fan-out test exercised `record_metric`, `dirty_across_organization` and `merge` by hand and
  called that proof. It tested three pieces, not the wiring between them — the same shape as the M6
  test that asserted `{} == {}`. There is now an end-to-end test: two graphs, an entity in each,
  both informed by one ROI, one `recordMetric` naming no graph, and both projected values must move
  from 40 to 50. Verified non-vacuous by narrowing the fan-out to one graph, which fails it with
  exactly the intended message.

`Structure.identifier` and `kind.identifier` are redundant and can drift, so the model now says
  which one counts: the denormalized column, because the unique constraint and every structure
  filter read it rather than the foreign key.

Also drops two graph fixtures a kind-idempotence test took and never used — the test proves
  `ensure_structure_kind` is idempotent, which does not involve a graph at all, and pretending
  otherwise misdescribed it.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

- Make the M6 split real on the read path, and its test non-vacuous
  ([`ec16e14`](https://github.com/arkitektio/kraph-server/commit/ec16e145ef404fc59e44de8880cb4e944e0cd1fe))

Three follow-ups to the indexed/derived-on-read split.

`test_only_the_indexed_property_is_projected` ran with no evidence, so both halves of the split were
  empty and the assertion reduced to `{} == {}`. The discrimination it claimed to prove was then
  re-implemented inline rather than exercised. It now has real measurements behind it — MEAN 20 for
  the indexed property, MAX 30 for the other — so confusing the two produces visibly different
  numbers instead of two empty dicts. This is the same vacuous-pass shape as `WHERE m.key = null`
  and the hardcoded `supporting_evidence: []`.

`NaturalEvent`, `ProtocolEvent` and `Reagent` still read only their stored keys, so every
  non-indexed derived property on an event was invisible — the bio schema's `Mitosis.cell_count`
  among them. The projector writes events, so the data was there and only the read path was missing.
  Nothing in the suite selected `properties` on an event.

The read path derived everything twice and subtracted, doubling the state-vector lookups on every
  entity read — an odd way to pay for a milestone about making properties cheaper.
  `split_properties` returns both halves in one pass.

Also collapses `projector._derived_properties` and `controller.indexed_property_keys`, which
  disagreed about what "derived" means while the read path diffed their results. One predicate,
  `projector.is_derived`.

The plan now records the M2–M6 deviations the way it records M1's: the M6 per-category Postgres
  views are **not** built, and the O(1) claim is about the write path only — listing N entities with
  P derived properties still costs O(N x P) state-vector lookups, and nothing measures it.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

- More
  ([`27c5bd9`](https://github.com/arkitektio/kraph-server/commit/27c5bd904dbb1e495b05936d43a0658ddd980cb4))

- More
  ([`f1cd97b`](https://github.com/arkitektio/kraph-server/commit/f1cd97b152ce1f6489fc836d95e630c1ce1350b7))

- More
  ([`c86b5a4`](https://github.com/arkitektio/kraph-server/commit/c86b5a478b768064b1011e5bb57da78f0ddd070e))

- More
  ([`ff54395`](https://github.com/arkitektio/kraph-server/commit/ff54395d6a6096c901da38810fdf3aaf3787b5a8))

- More and more
  ([`eec1f00`](https://github.com/arkitektio/kraph-server/commit/eec1f00b8bf61741daff31c9b57c1bc4a1cd57bc))

- More entity category things
  ([`2294080`](https://github.com/arkitektio/kraph-server/commit/2294080d80b9be859dae416dd6aa47a40831ff57))

- More fixes
  ([`47daa77`](https://github.com/arkitektio/kraph-server/commit/47daa770be29420d4e561b8590a931cc3b12284b))

- More stuff
  ([`3660d5a`](https://github.com/arkitektio/kraph-server/commit/3660d5a5fd4afc83e6e6a24b099a42e977b0f3fd))

- More stuff
  ([`9c61802`](https://github.com/arkitektio/kraph-server/commit/9c618027482595d50ba834cdd16cb6859b4e6dc9))

- More stuff
  ([`560cd3b`](https://github.com/arkitektio/kraph-server/commit/560cd3bdd358f60d79b6b7fc76e2164429d6b128))

- More stuff
  ([`6c6b0e0`](https://github.com/arkitektio/kraph-server/commit/6c6b0e0f9141ea4b1f9741b9d2695cb9ad13721c))

- More things
  ([`3ab1e4e`](https://github.com/arkitektio/kraph-server/commit/3ab1e4e155c03b17883ab7179b69e3a12e16a94b))

- More too be compliant
  ([`85c1142`](https://github.com/arkitektio/kraph-server/commit/85c11425d85c9c7173e55776afcf87a818632831))

- New
  ([`66ef829`](https://github.com/arkitektio/kraph-server/commit/66ef829c69acec8f6495589590f6af87d7b80e23))

- New datalayer
  ([`a6c57d7`](https://github.com/arkitektio/kraph-server/commit/a6c57d7182453792ad194f40239e7d6d813f21f8))

- New stuff
  ([`a31aa09`](https://github.com/arkitektio/kraph-server/commit/a31aa0946964c1310a6bad141b7b02052c00419c))

- New stuff
  ([`87df07a`](https://github.com/arkitektio/kraph-server/commit/87df07a8c711a2fdc5571988e99f3ebe92cab042))

- New stuff
  ([`07e7702`](https://github.com/arkitektio/kraph-server/commit/07e770218e47520685f282aef5611a114afc1136))

- New stuff
  ([`cbc0ae0`](https://github.com/arkitektio/kraph-server/commit/cbc0ae006158ad659a6ae8f3e33847b0697d106e))

- New stuff
  ([`713da0d`](https://github.com/arkitektio/kraph-server/commit/713da0db5b9a25f3e05cfe11517757734648c448))

- No docker compose
  ([`8979877`](https://github.com/arkitektio/kraph-server/commit/897987737efdf26995542880c8277dcd6f05f7d8))

- Node category
  ([`59036cf`](https://github.com/arkitektio/kraph-server/commit/59036cff626c8c5a56f2c0622be40e780615b21a))

- Okay
  ([`be9d046`](https://github.com/arkitektio/kraph-server/commit/be9d046b7634c405029aeff6462a47488adcc2ae))

- Participation
  ([`e74ddf1`](https://github.com/arkitektio/kraph-server/commit/e74ddf175319c84f158d688bb1087bf45ec7114b))

- Pin
  ([`672d05f`](https://github.com/arkitektio/kraph-server/commit/672d05f564aca006730c664bd321af08257609ac))

- Refactor
  ([`bac3f4c`](https://github.com/arkitektio/kraph-server/commit/bac3f4c76a1bb45b397f0d633ec8a91816fc4816))

- Rmeove datlaayer
  ([`0ff83a4`](https://github.com/arkitektio/kraph-server/commit/0ff83a4951b8b72a9b5471e08eb656d64fa0b355))

- Ruff
  ([`25d3f8b`](https://github.com/arkitektio/kraph-server/commit/25d3f8b4d4a2a83e721311feb1a3e2bd40acb313))

- Ruffed
  ([`d284161`](https://github.com/arkitektio/kraph-server/commit/d2841610c8e36435c2524477ab2f2aef5ce27eb3))

- Schema
  ([`a98fba3`](https://github.com/arkitektio/kraph-server/commit/a98fba35c6df63cfa2a3bf21779978fb32a7a82d))

- Schema tests
  ([`15b978e`](https://github.com/arkitektio/kraph-server/commit/15b978e36277755c3bae0d32ae79bfcd73581baf))

- Sdfsd
  ([`8214bb4`](https://github.com/arkitektio/kraph-server/commit/8214bb4ef36e1868b5a89d6d8a07f445da0c396f))

- Shit
  ([`10243d6`](https://github.com/arkitektio/kraph-server/commit/10243d61768b576ddf22306ca13a097100bfe2ed))

- Some errors not functional yet
  ([`a575988`](https://github.com/arkitektio/kraph-server/commit/a575988666589fb65b95082323675cf62c234964))

- Some little fixes
  ([`b870bd7`](https://github.com/arkitektio/kraph-server/commit/b870bd70e4ca4181066dfd4356495950adecd46b))

- Some more little things
  ([`3010f58`](https://github.com/arkitektio/kraph-server/commit/3010f58e810bddec804261ed1b24d49da07feb64))

- Some more tests
  ([`a9d8ce4`](https://github.com/arkitektio/kraph-server/commit/a9d8ce4cbe99911aa11e44788b2a7116a72b264e))

- Some stuff
  ([`5a25a04`](https://github.com/arkitektio/kraph-server/commit/5a25a042114b38b0ef87cfc7a78d3735446e0358))

- Some stuff
  ([`dbbb6be`](https://github.com/arkitektio/kraph-server/commit/dbbb6be03a6146cd9b0e2de2fb30b93806a89e67))

- Structure creation
  ([`51ef6f2`](https://github.com/arkitektio/kraph-server/commit/51ef6f2fea9dc6a1e18823f35d8c639616472368))

- Stuff
  ([`f22bf78`](https://github.com/arkitektio/kraph-server/commit/f22bf788cbdf28c11cdec3f251c40af8adc23e8e))

- Stuff
  ([`1ccadfd`](https://github.com/arkitektio/kraph-server/commit/1ccadfd4ae687d639ade5523f72b4758c8624fb1))

- Stuff
  ([`ea8044b`](https://github.com/arkitektio/kraph-server/commit/ea8044ba2dd50744e4d7fbba23318f4b500898a9))

- Stuff
  ([`08b632b`](https://github.com/arkitektio/kraph-server/commit/08b632bcc4cdfd6c2449bf4cecacb3c9a73531dd))

- Stuff
  ([`5294bad`](https://github.com/arkitektio/kraph-server/commit/5294bad3dcc56bb7d7f2fd0ec64b31406c32cec7))

- Stuff
  ([`859b2e0`](https://github.com/arkitektio/kraph-server/commit/859b2e0133de9d073106c61f6b8c581e65e99e10))

- Stuff
  ([`5853612`](https://github.com/arkitektio/kraph-server/commit/5853612a2dfddf40c590272c1a4da9ce855cbfd8))

- Stuff
  ([`c72ba0a`](https://github.com/arkitektio/kraph-server/commit/c72ba0a1b8fae05888b40ac5acc192c5bffc9678))

- Stuff
  ([`a50cf54`](https://github.com/arkitektio/kraph-server/commit/a50cf54e70d1dc81c65f9c96bb24a288ebb47f8f))

- Tests
  ([`cd58536`](https://github.com/arkitektio/kraph-server/commit/cd58536e3803ab7c6ccaf711cf014d6121baae43))

- Tests
  ([`6a491e5`](https://github.com/arkitektio/kraph-server/commit/6a491e510520baa24811c097a40b061bc65e523f))

- Tests
  ([`c1b1014`](https://github.com/arkitektio/kraph-server/commit/c1b10143e647a07986bde2e8a3dfe214c3747e73))

- Type and refactor datalayer
  ([`651341b`](https://github.com/arkitektio/kraph-server/commit/651341b66dbb99892b7bdb67855123e8f32d155f))

- Update authentikate dependency to version 0.15
  ([`d11898a`](https://github.com/arkitektio/kraph-server/commit/d11898a5450338aca78060bffc9716caf0fef8de))

- Update models
  ([`d08e60d`](https://github.com/arkitektio/kraph-server/commit/d08e60deb2f94be94f2f9ccb490031a597349d23))

- Update MY_SCRIPT_NAME configuration to use force_script_name
  ([`9e34e04`](https://github.com/arkitektio/kraph-server/commit/9e34e04cd46ecd1da520eb68cf4bfbb19994fbce))

- Wire the evidence surface that had no test holding it up
  ([`29f0e5c`](https://github.com/arkitektio/kraph-server/commit/29f0e5c609c9723a01137220da364e1911b1cafb))

Follow-up to the evidence base. Everything here was invisible to a green suite because nothing
  selected it.

`link_structure_to_entity` was dead code with a docstring claiming it was reinstated — no mutation,
  no schema field, no test — while being named in M1's own exit criteria. Now wired, with
  `metricsForStructure`, `informingStructures` and `measurementsForAssertion`, which were likewise
  resolvers nobody had registered. `measurementsForAssertion` was previously unimplementable at all:
  an assertion was an AGE vertex, so its id did not say which graph to look in.

`structure(id:)` and `metric(id:)` still split their argument on `:` to find a graph, which cannot
  work now that evidence ids are bare uuids. No test fetched a single structure or metric by id.

Three inherited `Node` fields would have 500'd on any evidence row: `graph()` looked up
  `get_graph_from_graph_name("")`, `globalId` raised on a property `from_row` never sets, and
  `graphId` returned 0 for everything. `graphId` and `graph` are now null — an evidence row has no
  vertex, and is shared by every projection over its organization, so there is no single graph to
  name.

Metric categories resolved through the wrong graph. Structures dedupe on `(organization, identifier,
  object)` and keep whichever category first created the row, so a structure introduced by graph A
  and measured through graph B resolved B's metric against A's schema — gating on A's permissions
  and filing auto-created categories under A, invisible to B. The acting graph is now threaded
  explicitly rather than read off `structure.category.graph`. This only bites once evidence is
  genuinely shared, which is what the previous commit enabled.

INT metrics round-tripped as floats: they share `value_num` with FLOAT so aggregation stays one
  column, but were never narrowed on read, and `3.0 == 3` meant the test could not see it.

Cleanups: `EvidenceModel` was abstract and never subclassed, so editing it did nothing — removed.
  `writer.ensure_structure` used the `all_objects` hatch while holding the organization; it now
  scopes properly, leaving three uses, each paired with an access check.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

- With filters
  ([`7c4010c`](https://github.com/arkitektio/kraph-server/commit/7c4010cf370118389888cfdaadb71e3c2852cddb))

### Features

- Add dev branch builds
  ([`1209376`](https://github.com/arkitektio/kraph-server/commit/120937658b71c3d13392d61a2e9eb079d155a870))

- Add django-health-check for improved health monitoring
  ([`c7c988d`](https://github.com/arkitektio/kraph-server/commit/c7c988de9c122d38b4e11665d13ecb86ae64b9b6))

- Add docker dev workflow
  ([`1cc87e4`](https://github.com/arkitektio/kraph-server/commit/1cc87e4d0c62c455545fd37cf7c81ec283140b77))

- Add filters
  ([`702c948`](https://github.com/arkitektio/kraph-server/commit/702c948fb0443ca55f1e2654174d59b134ca1201))

- Add get_age_entity_by_category_and_external_id function and corresponding GraphQL query
  ([`43625e0`](https://github.com/arkitektio/kraph-server/commit/43625e0a0b12bc53f9d75bd8c445ca08b4f8b98d))

- Add graph path builder
  ([`3638bed`](https://github.com/arkitektio/kraph-server/commit/3638bede92a556cb9694dc956e958be105a10917))

- Add GraphSequence model and related filters, mutations, and inputs
  ([`a19b822`](https://github.com/arkitektio/kraph-server/commit/a19b82208132a21279019d82450f02dc1dab3009))

- Add identifier and refactor to have age_names
  ([`660fffc`](https://github.com/arkitektio/kraph-server/commit/660fffc18a75652e70b4d8a181ffb299126d257f))

- Add KnowledgeView type and update knowledge_views query to return structured views
  ([`1e38f4b`](https://github.com/arkitektio/kraph-server/commit/1e38f4bcf7c346b7f293c82b4dcafa8ca415574d))

- Add node list and subjected as well as targeted by fields
  ([`5a6858b`](https://github.com/arkitektio/kraph-server/commit/5a6858b4cdc05aaae3d2019918a1a8a02f88421d))

- Add ParticipantKind enum and enhance entity category mutations with tags and relevant categories
  ([`7bf0af4`](https://github.com/arkitektio/kraph-server/commit/7bf0af42047fe9bff5e2792f2bbb4898a73d88e6))

- Add pinned filtering functionality to category filters
  ([`ae7cfb1`](https://github.com/arkitektio/kraph-server/commit/ae7cfb13abd10a6af984daa79b6a5b47a0285738))

- Add pinned_by field to Category model and update related mutations
  ([`2ba4d88`](https://github.com/arkitektio/kraph-server/commit/2ba4d8805cfa4cdb74c282fb69611b9a9cbe7a67))

- Add pinning functionality for graphs and node queries
  ([`053b1c0`](https://github.com/arkitektio/kraph-server/commit/053b1c0ebf826a24dd05570c357f5c39942d9af4))

- Add pinning functionality to various models and mutations
  ([`aded6be`](https://github.com/arkitektio/kraph-server/commit/aded6be037ec617d946d9c4bd09e84eff4e4cf08))

- Add ProtocolEventCategory model and related queries, mutations, and updates
  ([`debe300`](https://github.com/arkitektio/kraph-server/commit/debe300db4c6fb4c53b43b53f6eb1a42e8427f15))

- Add relevant_for field to GraphQuery and NodeQuery models
  ([`44ab27e`](https://github.com/arkitektio/kraph-server/commit/44ab27eaa741e7a464d7fcef37cd1aede1917567))

- Add settings
  ([`a16b9a2`](https://github.com/arkitektio/kraph-server/commit/a16b9a269dffa5f0d068d5b75c9c7fdfed4ce88f))

- Add stats
  ([`f9ad597`](https://github.com/arkitektio/kraph-server/commit/f9ad597f3802450f86061b5a0871b0803ff6df2a))

- Add StepCategory model and related mutations and filters
  ([`aeaf2d8`](https://github.com/arkitektio/kraph-server/commit/aeaf2d8a9394d58a31d6b4c0664bd92617575ae9))

- Add structure relations and pairs
  ([`71ff770`](https://github.com/arkitektio/kraph-server/commit/71ff770b67a42d258980468f1e40657df677a8be))

- Add update_graph_query mutation and related fields
  ([`3a46036`](https://github.com/arkitektio/kraph-server/commit/3a460367b19a529f39c3281e0cf9f7de75764e43))

- Api stuff
  ([`c8aae76`](https://github.com/arkitektio/kraph-server/commit/c8aae76a80ec5ecde660b6ef75a2aca70c01375b))

- Category and stuff
  ([`7e616b5`](https://github.com/arkitektio/kraph-server/commit/7e616b5f2e28f2ffaecd022d0e8fc24dc11380ff))

- Dd strawberry definition
  ([`ed0c59d`](https://github.com/arkitektio/kraph-server/commit/ed0c59d4eb0afbae36c6143224006300ad59e9ee))

- Derived values can explain themselves
  ([`a0b105c`](https://github.com/arkitektio/kraph-server/commit/a0b105c5d7dbba2bdc92a498e40871f4912d8faa))

The BIOLOGIST.md sentence — "45.2µm (confidence 98%), derived from ROI #555, asserted by AI_Model_X
  on Jan 15th" — is now one GraphQL query. None of it was answerable before:
  `RichProperty.supporting_evidence` returned a hardcoded empty list, so a value could be read but
  never accounted for.

`RichProperty` reads the state vector for `nEvidence`, `spread`, `measuredFrom`/`measuredTo`, the
  contributing metrics, and the assertions behind them. `Metric` exposes unit, confidence and both
  time axes; `Assertion` exposes subject, app and assertion time. All of it was already in the
  evidence base and simply unreachable through the API.

`api/loaders.py` is rewritten. The fifteen module-level `DataLoader` instances had three defects at
  once: a process-lifetime cache with no tenant boundary (a cross-tenant leak arriving past the
  evidence scoping guard), `for i in ids: await aget(i)` — N queries, which makes a DataLoader a
  cache with extra steps — and `aget` raising, so one dangling id failed every id batched with it.
  Loaders are now per-operation via a `LoaderExtension`, batch into one `id__in` query, and return
  None for misses.

PRIORITY_LATEST and LATEST_ASSERTION_TOOL are implemented rather than aliased. They cannot read the
  state vector — its grain has no subject discriminator, and adding one would multiply every row by
  the number of sources that ever measured — so they query metrics directly, ordered by the new
  `subject_priority` / `tool_priority` on the rule. An unlisted source can never outrank a listed
  one. `ConflictPolicy` names the four ways sources can disagree; averaging a human annotator with a
  segmentation model produces a number neither of them claimed.

`validFrom`/`validTo` are populated. Six GraphQL fields read them and every one returned null
  because nothing ever wrote them; they are now the `measured_at` window of the contributing
  evidence.

Two ref bugs found while wiring this up, both silent: - `RichProperty` looked up state by AGE vertex
  id while M3 keyed everything on the durable uuid, so it would have found nothing for every entity.
  - `archive_entity` wrote a vertex-id lifecycle ref the projector could never match, so archiving
  an entity never affected its projected state. `RetrievedNode.durable_ref` is now the single
  spelling. - `valid_from` parsed only numbers while `valid_to` parsed only ISO strings, so
  whichever format you wrote, one of the pair broke.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

- Enhance graph and relation mutations with age handling and validation improvements
  ([`797fbe6`](https://github.com/arkitektio/kraph-server/commit/797fbe6fb60226da6c7c16fb6364b55f177f7760))

- Enhance protocol event handling with variable mapping and new input types
  ([`88a7bac`](https://github.com/arkitektio/kraph-server/commit/88a7bac91aedef283db8297408c75784d8af5f91))

- Fix filters
  ([`48afc71`](https://github.com/arkitektio/kraph-server/commit/48afc71dbc717edf11b37fd69391a1af0bcac515))

- Fix identifier
  ([`757e4c3`](https://github.com/arkitektio/kraph-server/commit/757e4c3e5cccc7a5a5eebe99b342c50151ad8ce5))

- Fix metric
  ([`de750b7`](https://github.com/arkitektio/kraph-server/commit/de750b7e803a7127208a85615555955593705461))

- Give more tests
  ([`6919f7c`](https://github.com/arkitektio/kraph-server/commit/6919f7cbfeb99fc1c8ca4c0ce45a6fadb63f87ac))

- Materialized edges
  ([`6f33fd3`](https://github.com/arkitektio/kraph-server/commit/6f33fd36688a1898d43b9a95a59c5ca62f5c29ba))

- Metric kinds are unique per value kind
  ([`14084b9`](https://github.com/arkitektio/kraph-server/commit/14084b96f654778e283f25b81ff7265b2c2452e3))

`ensure_metric_kind` used to raise when an existing term was redeclared with a different
  `value_kind`. That refuses a measurement because someone else reached the key first — the same
  bookkeeping-technicality argument that made `ensure_structure_kind` always-allow. A float
  `confidence` and a category-label `confidence` are not one quantity disagreeing; they are two
  quantities sharing a name.

So identity becomes `(organization, structure_kind, key, value_kind)` and both declarations land.
  Cardinality stays bounded: `ValueKind` has eleven members, and in practice a key has one term.

Provenance stays out of identity. The argument for including `value_kind` does not extend to it —
  which tool measured something is not a claim about what the quantity is, `action_id` is
  per-deployment so cardinality would be unbounded rather than eleven, and folding it in would make
  MEAN over a key become one mean per tool with nothing to combine them.

The collision does not disappear, it relocates
  -------------------------------------------------------------------- `State`'s grain was
  `(entity_ref, source_kind, key)` — a *StructureKind*, with `MetricKind` absent entirely. Two terms
  sharing a key therefore fold into one row, and `_numeric()` returns None for a string, so the
  string bumps `n` without touching `sum`: MEAN over 40, 60 and "big" reads 33.3.

`recompute()` filtered the same way and reproduced the error exactly, so the incremental fold and
  its own correctness backstop agreed — and `test_state_vector`'s property test, written to catch
  fold errors, certified it. Two wrong answers agreeing is not evidence.

`value_kind` therefore joins the State grain, and the property test's generator now emits mixed
  value kinds with an assertion on the numeric row's `n` rather than only on a rebuild of itself.

Precondition: the declared value kind was being discarded
  --------------------------------------------------------------------
  `RecordMetricInput.value_kind` was a *required* field that nothing read. Both write paths inferred
  from the Python value instead. Verified live: on the old path, recording "high" as STRING under a
  key inference had called FLOAT did not mislabel it, it raised `could not convert string to float`.

Left unfixed it would also have decided term identity by `type(value)` — `45` minting INT and `45.2`
  FLOAT under one key, silently, on the first two measurements. `record_metric` no longer takes a
  `value_kind` argument at all; the row's kind is its term's, so the two cannot disagree.

Resolution rule, symmetric on both sides
  -------------------------------------------------------------------- Write: a declaration is exact
  and never refused; silence adopts the single existing term, or infers and mints when there is
  none. Two or more terms and no declaration is the one raise that survives — an ambiguous *lookup*,
  not a rejected declaration, and picking arbitrarily would file the same measurement in different
  columns depending on which write ran first.

Read: `DerivationRule.source_value_kind` is new, because `prop.value_kind` cannot answer this — it
  is the aggregation's *result* type, so `AGGREGATION_RESULT_TYPES` maps COUNT to INT over STRING
  sources. Declared is exact; silence resolves from the vocabulary; ambiguity warns naming the terms
  and skips.

INT and FLOAT are read as one quantity — both live in `value_num` and `_numeric` accepts both, so a
  rule naming FLOAT that read only the FLOAT term would silently drop half its evidence.
  `state.combine()` folds the rows, finally using the monoid the design rests on. Deliberately the
  only widening: routing identity through `VALUE_COLUMN_FOR_KIND` instead would merge STRING with
  CATEGORY and collapse all five vector arities.

Both load-bearing tests verified non-vacuous by reverting the change and confirming the intended
  failure.

BREAKING CHANGE: `MetricKind`'s unique constraint gains `value_kind`, as does `State`'s.
  `writer.record_metric` no longer accepts `value_kind`. `DerivationRule` gains an optional
  `source_value_kind`.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

- Minimal tests
  ([`2f35f15`](https://github.com/arkitektio/kraph-server/commit/2f35f15351d8cc907e10487f76a3e9aba7f2ec38))

- More
  ([`93c92e8`](https://github.com/arkitektio/kraph-server/commit/93c92e895c80c35aee52616f0f2eabdb13e20b33))

- More materialized edges
  ([`368d34d`](https://github.com/arkitektio/kraph-server/commit/368d34d4b58c2e50c3c1ad87f7e0c4dc8237ec66))

- More provenance features
  ([`a85bd2a`](https://github.com/arkitektio/kraph-server/commit/a85bd2a426d03afabb77ee601ddf4c4471ec5a94))

- More stuff
  ([`e169596`](https://github.com/arkitektio/kraph-server/commit/e169596074ef14c3ea644527ccdab791e223da30))

- More updates
  ([`ab94566`](https://github.com/arkitektio/kraph-server/commit/ab945665b3b68e5cad44fd907d2c97babd70adc6))

- Move properties to node
  ([`e823b61`](https://github.com/arkitektio/kraph-server/commit/e823b61cc4acf60312c56038e3da622ea82b8014))

- New before refactor
  ([`c39fb3e`](https://github.com/arkitektio/kraph-server/commit/c39fb3e0433438985bc7e60653b1cba8e31b4612))

- New properties feature
  ([`789aa3b`](https://github.com/arkitektio/kraph-server/commit/789aa3ba4f843cdc296747751a9263d92b0d9b35))

- New stuff
  ([`fe6a79e`](https://github.com/arkitektio/kraph-server/commit/fe6a79e16d94c5cfe6cb67dc9f80dd0a9fa83d4a))

- Now with edit events
  ([`017880f`](https://github.com/arkitektio/kraph-server/commit/017880f6b58dfb3ffc43143ddce73b467fc590a8))

- Only filterable properties are materialized
  ([`e8d6a5b`](https://github.com/arkitektio/kraph-server/commit/e8d6a5b61f09007f18b7dc877b19ef084f369af0))

`PropertyDefinitionInput.index` existed and did nothing. It is now load-bearing: `index: true`
  projects a derived property onto the Apache AGE node, everything else is computed on read from the
  state vector.

The indexability argument only ever held for properties you filter or sort on — Cypher compares
  against stored node properties, so `e.length > 40` needs `length` on the node. It does not hold
  for values read *after* a node has been selected, which is most of a schema. Adding a non-indexed
  property is now genuinely O(1): no backfill, no projection write, and nothing that can go stale
  because nothing was stored.

Callers cannot tell which is which. `Entity.properties` merges the two, and `RichProperty.value`
  falls back to the statistics when a key is not on the node. `richProperties` now enumerates the
  *schema* rather than the node's stored keys — iterating stored keys would have hidden every
  derived-on-read property, which is precisely the set that type exists to explain.

Filtering or sorting on a non-indexed property is an error naming the fix, not zero results. A
  Cypher predicate against an absent property matches nothing, and "no results" is indistinguishable
  from "nothing satisfies this".

Two bugs surfaced by the new tests:

- `list_entities_for_category` emitted `MATCH (e:X) AND ...` with no `WHERE`, a Cypher syntax error.
  Filtering by category has never worked; no test had passed a filter through it. - Sort directions
  were interpolated into Cypher after `.upper()`, which is not validation. The direction arrives
  from a GraphQL variable and lands in the query text, so anything but an exact ASC/DESC was an
  injection — the hole `_validate_property_key` closes for keys, left open in the clause beside it.
  Now whitelisted at all three sites.

Also: `derivation` defaults to LATEST, so the enum alone never distinguished a computed property
  from a plain one. What makes a property derived is having a rule that names a source — the same
  condition the projector already required before computing anything.

BREAKING CHANGE: derived properties without `index: true` are no longer stored on the node and
  cannot be filtered or sorted on.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

- Projector rebuilds the graph from evidence; derivation works again
  ([`2a3aea0`](https://github.com/arkitektio/kraph-server/commit/2a3aea0168e6f563d762f57fa43c4d12ee1eb2fc))

The AGE projection becomes provably derivable. `manage.py reproject --graph X` drops the namespace,
  replays every node and metric from Postgres, refolds the state vectors and re-derives the
  properties — and `test_reproject_idempotent` compares the result property-by-property against what
  was there before. If the graph could not be rebuilt from the evidence, the evidence would not be
  the source of truth whatever the docs claim.

Two things had to change for that to be possible at all:

**Entity refs key on the entity's uuid, not the AGE vertex id.** Vertex ids are assigned by AGE and
  are reassigned when a graph is dropped, so evidence keyed on them would leave every INFORMS link
  dangling after exactly the operation `reproject` performs.

**Node existence is evidence.** "There is a cell here" is a claim, so it gets an `evidence_node`
  row. Without it, an entity carrying no metrics yet would simply vanish on rebuild. The rebuild
  also discards and refolds the state vectors — replaying while keeping them would only prove the
  projection is rebuildable from *another* cache.

Derivation works end to end for the first time. Recording a metric against a structure now moves the
  derived value on every entity that structure informs, with no explicit recalculate — the headline
  claim of BIOLOGIST.md, previously unimplemented in three separate places. `_recalculate_entity`'s
  NotImplementedError from M1 is gone, replaced by `recalculate_entity(graph, ref)` taking a durable
  ref rather than a vertex id that cannot survive a rebuild.

Folding and projecting are deliberately separate. Each metric folds into its state vector in O(1)
  without reading history; the derived value is written once per dirty set. A hundred metrics
  against one structure produce one state row and one projection pass — the O(N x P) regression
  `test_dirty_fanout` guards.

Fixed along the way: supporting evidence was recorded *before* the INFORMS links it rolls up through
  existed, so nothing folded and every entity created with evidence derived nothing. Natural events
  had the same bug plus a vertex-id ref. `Category` is polymorphic and a plain foreign key hands
  back the base instance, which has no `defined_properties` — projection silently derived nothing
  until downcast.

`tests/evidence/test_derivation_gap.py` is deleted, as its own docstring instructed: it existed to
  fail once M3 landed.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

- Refactor sequence handling in create_age_entity and create_age_reagent functions
  ([`56d1205`](https://github.com/arkitektio/kraph-server/commit/56d120550cb28fa3de107d4b3f20b4053e653402))

- Relational evidence base, organization-scoped and bitemporal
  ([`d6d23a7`](https://github.com/arkitektio/kraph-server/commit/d6d23a72073f05b09817b3796990e9b69d9aa2db))

Structures, metrics and assertions move out of Apache AGE into Postgres as the new `evidence` app.
  They are the source of truth; AGE becomes a projection that holds only entities, events and
  relation edges.

Tenancy is the organization, never the graph. The same ROI referenced while building two graphs is
  now one `Structure` row under `unique(organization, identifier, object)`, so a metric recorded in
  one experiment is visible to a projection built for another without re-ingest. The namespace
  isolation this gives up is replaced by a manager whose default queryset raises:
  `Structure.objects.filter(...)` fails rather than quietly spanning tenants, and `all_objects` is
  the deliberately awkward escape hatch.

Time gets two axes. `measured_at` is when the world was observed, `asserted_at` when somebody
  claimed it; the old single ms-epoch `timestamp` collapsed both and made "what did we believe on
  March 3rd" unanswerable.

`ValueKind` is now the canonical type vocabulary (it is the enum GraphQL exposes, and strictly more
  expressive than the internal `PropertyType`, whose POINT_3D is THREE_D_VECTOR here). M4 deletes
  the loser and its three conversion tables.

Derived properties are deliberately dark until M3: metrics left AGE, so the rollup Cypher matches
  nothing. `_recalculate_entity` raises rather than writing nulls over every derived value, where a
  null is indistinguishable from "no evidence yet". `tests/evidence/test_derivation_gap.py` keeps
  that loud and is written to fail once M3 lands.

Also: - Evidence IDs are bare uuids, so they name no graph. Authorization resolves the row first,
  then checks the caller belongs to *its* organization. - `validate_graph_access` now enforces
  instead of returning unconditionally. The test identity never matched the org owning the graph,
  which is why the no-op went unnoticed; fixtures now build graphs under the identity the auth
  extension actually produces. - A structure's `object` is immutable — repointing it is a different
  datum, not a supersede, which the uniqueness constraint cannot express. - Event and relation
  archive paths wrote LifeCycleAssertion vertices hanging off an `(a:Assertion)` match that no
  longer resolves; they silently did nothing and now go to the evidence lifecycle log. -
  `Graph.selector` added (inert until M3).

BREAKING CHANGE: structure, metric and assertion IDs are now uuids rather than `{graph}:{node}`
  composites; `updateStructure` no longer repoints `object`; deleting a missing structure reports an
  error instead of succeeding.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

- Removal of stale migrations
  ([`90122e9`](https://github.com/arkitektio/kraph-server/commit/90122e97185c41370d720b9e6fa1c25af8c1d26b))

- Removal of stale migrations
  ([`afd2ee6`](https://github.com/arkitektio/kraph-server/commit/afd2ee6053d18ea8c4995f5d37461fb526ed4c75))

- Retrive messages
  ([`cdee5d3`](https://github.com/arkitektio/kraph-server/commit/cdee5d32df064fbf9f5b9f01470b1e9ac60a6d10))

- Schema versions per change, so a schema edit can be scoped
  ([`85f044a`](https://github.com/arkitektio/kraph-server/commit/85f044a81c5bb4cf83c01d2cab3e070e61abb4f8))

`GraphSchema` used to be written exactly once per graph — index=1 and is_active=True hardcoded,
  `activate()` never called — while every category mutation edited rows in place. With one version
  and no history there was nothing to diff, so nothing could be scoped, so every schema change
  looked like "recalculate everything". That appearance was the problem, not the cost.

Versioning is now driven by a `post_save`/`post_delete` signal on the category models, which makes
  "no code path mutates a category without emitting a version" true of every path — the eight
  mutation modules, the managers, the admin, and anything written later — rather than of the paths
  someone remembered to annotate. `materialize()` suspends it and emits once, so a schema expressed
  as dozens of categories is one version rather than a history of insertion order. A mutation that
  changes nothing emits nothing: the content hash decides.

`schema_diff` then answers what a change costs, and the answer that matters is **nothing**. Swapping
  MEAN for MAX produces a real version with an empty work set, because the state vector holds
  statistics rather than an answer. Changing a rule's source or key, or adding/removing a property,
  does imply re-deriving that category — and `manage.py backfill_schema` re-derives exactly those
  entities.

Also: - `GraphSchema.hash` is what a projected node stamps as `__schema_version`. Previously
  `_stamp_projection` wrote `NodeCategory.schema_hash` (a hash of one category's properties) while
  the projector wrote a different value, so the two disagreed about what the field means and
  whichever ran last won. - A partial unique constraint enforces one active schema per graph.
  `activate()` deactivating siblings is not enough alone — two concurrent activations would each see
  the other as inactive. - `unique_together ("graph", "version")` is dropped. `version` is the
  semantic version of the schema format and many revisions share one; the constraint was harmless
  only while there was one schema per graph, and blocked per-change versioning outright. - Three
  type-conversion tables collapse to one. Aggregation result types and the metric-kind mapping now
  speak `ValueKind` directly; the surviving table is the legacy-input adapter, not a parallel
  vocabulary. The old comparison went through PropertyType, which silently collapses CATEGORY into
  STRING and has no representation for any vector but 3D — so the check was weaker than it looked. -
  `setEntityProperty` is removed. It wrote straight onto the projection, bypassing evidence, which
  made it un-derivable state `reproject` cannot reconstruct and which the projector would silently
  overwrite on the next metric. - Archiving a metric twice no longer subtracts its contribution
  twice.

BREAKING CHANGE: `setEntityProperty` is gone; record a metric instead.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

- Structure and metric kinds become organization vocabulary
  ([`d239668`](https://github.com/arkitektio/kraph-server/commit/d2396687c600bc3ca659139f9bcc0faa3742d90c))

Recording a measurement no longer names a graph. `recordMetric`, `createStructure` and
  `ensureStructure` take an identifier and nothing else; scope comes from the request's
  organization.

Evidence rows were already graph-less. What forced a graph into every ingest call was the ontology:
  `StructureCategory` and `MetricCategory` inherited `graph` from the polymorphic `Category` base,
  so resolving "what kind of thing is `@mikro/roi`" needed a projection with no bearing on the
  measurement. Three things said they did not belong there at all — `materialize()` never created
  them, `GraphExtensionsInput` has no fields for them, and they had no Apache AGE presence
  (`get_age_vertex_name()` returned a hardcoded `"Structure"`). They are now
  `evidence.StructureKind` / `evidence.MetricKind`, in the app whose rows reference them.

**The real bug this fixes.** `informs_links_for` filters links by one graph's `{age_name}:` prefix,
  so `dirty()` only ever named entities in the graph the caller passed — and every write path passed
  exactly one. A second projection over the same shared evidence went stale the moment a metric was
  recorded through the first, and stayed stale until a manual reproject. That contradicted the point
  of sharing evidence. `dirty_across_organization` groups refs by graph, so one write reaches every
  projection that reads it; `test_org_wide_fanout` states the old behaviour as a strict subset so
  the regression is visible rather than implied.

Identity is `(organization, structure_kind, key)` for metric kinds. The old table enforced `(graph,
  key)` while the lookup used `(graph, key, structure_category)`, so two metrics named `area` on
  different structures already collided. A contradicting `value_kind` now raises naming both kinds,
  instead of storing the same measurement in different columns depending on who wrote it.

Provenance stays on the assertion and is not part of a kind's identity. Folding tool into the term
  would fragment the aggregation grain — MEAN over a key would become one mean per tool with nothing
  to combine them — and turn a read-time question that `ConflictPolicy` already answers into a
  write-time irreversible one. `Assertion.action_id` is restored; `ProvenanceContext` always carried
  it and the first version of the model dropped it.

Also: - Introducing a kind needs no permission. The per-graph AUTO_ADD_STRUCTURES gate is gone: an
  identifier is owned by the service that produced the datum, and its
  `_extract_request_roles`/`_extract_request_scopes` returned empty sets anyway. - The GraphQL types
  are renamed rather than quietly losing ten inherited fields, so an unmigrated client fails once
  instead of field by field. - `structureKinds`/`metricKinds` get explicit resolvers scoping to the
  request's organization. `CategoryFilter.graph` was the only fence those root fields had, and
  removing it without a resolver would have leaked every tenant's vocabulary. -
  `_infer_metric_value_kind` returned `PropertyType` ("float") where storage speaks `ValueKind`
  ("FLOAT"), producing terms no column mapping recognised. - `snapshot_definition` emitted
  `structures`/`metrics` sections nothing read. - `StructureDescriptorInput` now rejects
  `keys`/`tags`/`ontology_terms`: a kind has none of them, so accepting the filters would match
  nothing in silence. - `admin.site.register(StructureCategory)` removed — an import-time crash.

`test_shared_structure_schema.py` asserted the old invariant as its whole thesis and is rewritten to
  assert the inversion. Migrations are squashed rather than staged, per the blank-slate decision.

BREAKING CHANGE: ingest mutations no longer accept `graph`; `StructureCategory` and `MetricCategory`
  are replaced by `StructureKind` and `MetricKind`, which do not implement the Category interface;
  `createStructureCategory` and `createMetricCategory` are removed (kinds are created lazily).

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

- Stuff
  ([`edac9c4`](https://github.com/arkitektio/kraph-server/commit/edac9c41c9de327adaafc4ac7f5c89a4093b2fa6))

- Stuff
  ([`3fe4581`](https://github.com/arkitektio/kraph-server/commit/3fe4581405c9c1e9cc12b5db8d86d9ec0fbd2649))

- Sufficient-statistics state vector replaces write-time rollups
  ([`efbc816`](https://github.com/arkitektio/kraph-server/commit/efbc816f97c59026c16a36c6e5f9e607a0f94f4f))

Derived properties stop being materialized answers and become statistics read on demand.
  `evidence_state` keeps `{n, sum, min, max, first, last}` per (entity, source_category, key); all
  eight AggregationFunction members are monoids over it, so each is O(1) to maintain and O(1) to
  read.

The point is what this makes free: switching a property from MEAN to MAX now changes the value with
  zero writes to evidence or statistics — previously an O(entities x evidence) backfill triggered by
  a one-line schema edit. `test_aggregation_reinterpret` asserts exactly that, down to the state
  row's `updated_at` being untouched.

Grain decided, and it is a "no". A rule may only fold measurements reaching an entity through
  (Metric)-[DESCRIBES]->(Structure)-[INFORMS]->(Entity). Counting related entities or events — "this
  cell's mitosis events" — is a graph cardinality question, not a fold over measured values: no sum,
  no min, no max, and it would have to be maintained on entity creation rather than metric arrival.
  `materialize.validate_derivation_rules` now rejects such rules, and rules with no metric key,
  before writing anything. They previously rendered as `WHERE m.key = null`, which never matches, so
  the property silently stayed unset.

Retraction distinguishes the two kinds of statistic. SUM/COUNT/MEAN are group operations and
  subtract exactly. MIN/MAX/RANGE/LATEST/EUCLIDEAN_RANGE cannot be un-merged — the value removed may
  be the one that set the extremum — so the row is flagged and rebuilt from surviving evidence.
  `state_for` rebuilds on read, so a stale value can never leak to a caller.

`rollup.py` is deleted. Its EUCLIDEAN_RANGE used the `^` operator, which Apache AGE does not
  implement, so that aggregation could never have run; the replacement is `math.dist` and is
  dimension-agnostic rather than hardcoding x/y/z.

Also: - `graph_engine/__init__.py` advertised six names in `__all__` that had no definition, and
  `get_retrieved_types` imported two functions deleted in M0. Lazy accessors are invisible to a
  module-walk, so the import guard now calls them and checks every `__all__` entry resolves. -
  `backend_stack` removes stale `dokker-test-*` containers and volumes before starting. Each session
  names its own compose project, so `down()` never cleaned up an interrupted run — leaving ports
  bound and a database volume whose stale content_type rows surfaced as a duplicate-key error at
  setup.

BREAKING CHANGE: rollup rules sourced from entity or event kinds are rejected at materialization
  instead of silently never computing.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

- Test
  ([`8e4a18c`](https://github.com/arkitektio/kraph-server/commit/8e4a18c947c8457dba66d33c389ce26286772844))

- Test
  ([`78a73ab`](https://github.com/arkitektio/kraph-server/commit/78a73ab84efb1e585241fe8a8db9e2384d6000ca))

- There
  ([`984716c`](https://github.com/arkitektio/kraph-server/commit/984716c5e0760a31b598263dc7cd6cc1793aeecb))

- Update ALLOWED_HOSTS and format CSRF_TRUSTED_ORIGINS in settings
  ([`d245fe5`](https://github.com/arkitektio/kraph-server/commit/d245fe5baaa94c82468feb3cd7f4ffcc7288bbea))

- Update authentikate
  ([`08d1bb5`](https://github.com/arkitektio/kraph-server/commit/08d1bb51e3689490aaac794c98fbf43e64257603))

- Update authentikate
  ([`b62b2dc`](https://github.com/arkitektio/kraph-server/commit/b62b2dc4512b4476bcc94c260ccb766deb996c20))

- Update authentikate package version and adjust settings for issuers
  ([`4718c39`](https://github.com/arkitektio/kraph-server/commit/4718c391e12e2f4df056e6f13c5cfcc51727aefb))

- Update Docker workflows to include Go-Arkitekt live refresh step
  ([`20f4093`](https://github.com/arkitektio/kraph-server/commit/20f4093b63cb4610d4a668dde25f6e455e77c9ac))

- Update to major new stack
  ([`12923e2`](https://github.com/arkitektio/kraph-server/commit/12923e28b53c535f98c673f1e250e27adbd35776))

- With filters
  ([`3510851`](https://github.com/arkitektio/kraph-server/commit/3510851823e83b410b38f4324c9f938c5ccf7987))

- With filters
  ([`d02e574`](https://github.com/arkitektio/kraph-server/commit/d02e5749ca7e0ebff70347e6bab1ff6f0db4431d))

- With relation support
  ([`d3be53c`](https://github.com/arkitektio/kraph-server/commit/d3be53c980f5d39f62fdfbe9f6dcd74161f8f938))

- With release
  ([`fbb4c03`](https://github.com/arkitektio/kraph-server/commit/fbb4c03ea4fa79ec324b1f5095bc6d5bc879a955))

- With tests
  ([`7ae0854`](https://github.com/arkitektio/kraph-server/commit/7ae0854fd31bbf88705be6f74277537d9079ff51))

- With white noise and optimized Dockerfile
  ([`5736163`](https://github.com/arkitektio/kraph-server/commit/5736163b01a3fd2a952951562db3e041263c0b1c))

### Refactoring

- Remove unused database configuration for graph
  ([`75c9bad`](https://github.com/arkitektio/kraph-server/commit/75c9bad7925252d72ba3b24dbac396ef799e9e61))

### Breaking Changes

- `metrickind`'s unique constraint gains `value_kind`, as does `State`'s. `writer.record_metric` no
  longer accepts `value_kind`. `DerivationRule` gains an optional `source_value_kind`.
