# The append-only log: what is recorded

Every claim the system holds lives in the `evidence` app. The projection tables
(`graph_engine.models.ProjectionVertex` / `ProjectionEdge`) hold each view's
*drawing* of it — droppable, rebuildable, never authoritative. This document is
the vocabulary: what a claim can say, who writes it, who reads it, and what is
deliberately not a claim at all.

> Vocabulary note: where this document says "AGE vertex", "AGE edge" or "AGE
> namespace", read "drawn vertex/edge — a projection-table row" and "the view's
> rows". Apache AGE was retired by
> [RFC 0005](./rfcs/0005-retire-the-cypher-projection.md); the drawing's
> semantics described here are unchanged, only its storage moved.

The governing rule, from [`BIOLOGIST.md`](BIOLOGIST.md):

> You cannot change the biological reality (the Entity) directly; you can only
> provide new evidence.

Everything below is a consequence of taking that literally.

---

## The three axioms

**Nothing is edited in place**, and the database enforces it. There is no update
and no delete on `Assertion`, `Standing`, `Structure`, `Metric`, `Link`, `Instance`
or `Comment`: a trigger refuses both (`evidence/migrations/0005_log_is_append_only.py`,
extended to comments in `0010`).
Correcting a claim means writing a new one; withdrawing a claim means writing a
`Standing` that says it no longer stands. The API has no mutation that destroys
instance data — erasure exists only as `manage.py redact`, which is operator-only,
records what it reached in `Assertion.action_args`, and is the one caller that
sets `kraph.allow_log_rewrite` to say so.

Triggers rather than `REVOKE`, because a superuser ignores table privileges and
the application frequently connects as one — a grant-based guard would be absent
exactly where it mattered and untestable besides.

This axiom was aspirational until recently. `writer.claim()` wrote the claim and
then flipped a cached `stands` boolean on the target — an `UPDATE` on a log table,
four lines below a docstring promising there were none — and three of the four
evidence kinds were read from that cache rather than folded. The cache now lives
in `CurrentStanding`, a projection; `evidence.claims.standing` is how a queryset
narrows by it; and `rebuild` folds it from the log before drawing anything.

One consequence worth stating on its own: **concurring claims are no longer
dropped.** Restating a position already held used to write no row at all, so a
second annotator retracting the same metric left no trace and agreement was not
countable on the existence axis. The suppression existed because `State` folds
deltas and must not subtract twice; that guard now sits on the transition
(`StandingResult.moved`) instead of on the log.

**Tenancy is the organization, never the graph.** A `Graph` is a view over its
organization's evidence, so the same ROI measured in two experiments is one row
both projections can see. Nothing in `evidence/` may grow a `graph` foreign key.

**The graph carries no lifecycle state.** If the evidence does not say a node
exists, the node is not in the projection — no vertex, and no flag beside one. A
vertex that is there is one that stands, so a property saying otherwise could only
ever contradict its own presence.

---

## What a claim can say

Every row below carries an `Assertion`, and the assertion is the provenance:
*who* claimed it, with *which app*, and *when they believed it*.

### `Assertion` — who claimed something

| Field | Meaning |
|---|---|
| `subject` | A user id, or the identity of an automated agent |
| `app_id` | Which application made the claim |
| `asserted_at` | **Belief time.** The axis `as_of` filters on |
| `recorded_at` | When we durably stored it. Debugging only |
| `action_id` | The Rekuest assignation that produced this, from the request's provenance token. Null for a human at a keyboard |
| `action_args` | The args hash (`ahs`) and its algorithm, plus the causal chain — parent and root assignation, assigner, agent, issuer. Never the raw token |
| `action_name` | **Nothing supplies one.** A provenance token attests causation, not naming, and `koherent.Task` is built from the same claims |

Time has two axes and they move independently: a re-analysis run today can assert
a fact about an image taken last year. Collapsing them makes *"what did we believe
on March 3rd"* unanswerable.

### `Structure` — a pointer to an external datum

"There is an ROI with this object id." Immutable: repointing at a different object
is refused, not superseded. Idempotent per `(organization, identifier, object)`,
so two experiments referencing the same ROI converge on one row.

### `Metric` — a measured value about a structure

"This ROI has a `vector_length` of 45.2." Carries `observed_at` (world time — it
was `measured_at` until RFC 0015 gave every claim the column) as well as
`asserted_at` (belief time), plus optional `unit`, `confidence` (every claim
has that one since RFC 0016) and `confidence_type` (metric-only: what sort of
number the method's confidence is). Typed value columns rather than a JSON blob,
so numeric aggregation stays a database operation.

### `Term` — a word the organization uses

"AIS", "Mitosis", "IS_CONNECTED_TO". Identity is `(organization, kind, key)`, so
"AIS" as an entity and "AIS" as a relation are two terms. Minted lazily by
`writer.ensure_term`, like `StructureKind` and `MetricKind`.

**This is what the log names.** A claim says "this node is an AIS" — not "this
node is *that graph's* AIS row", which is what it said while `Instance.category` and
`Link.category` pointed at `core.Category`. That bound each claim to one view, so
a second projection could not read it however much vocabulary the two shared.

A `core.Category` is still graph-native and stays that way: it is created from the
graph's schema definition and holds `age_name`, `definition`,
`property_definitions` and layout, none of which mean anything outside the graph
that owns them. It gains a foreign key to the term it declares, and that is the
join — a claim names the word, and each view's category says what the word means
*there*. Two graphs declaring "AIS" reach the same term and both hold the node.

**The write API names the term directly**, which closes the last place a claim was
stated through a view — see *Which operation writes which claim* below. A category
is therefore read-side and schema-side only: it says what a word means here, and it
is never how a word is said.

Because a view can be declared after the fact, declaring one can also *ask for the
history*: `createGraph` and the category-creation mutations take `backfill`, which
projects the claims the new word already admits. Without it a new view over old
evidence comes up empty until someone runs `manage.py reproject` — the mechanism
existed, but nothing offered it at the moment the declaration was made.

Consequently a category, or a whole graph, can be deleted freely: it is a view,
and removing it takes nothing with it. The `PROTECT` lives on `Term`, which cannot
be removed while anything has been claimed under it. There is no longer any
foreign key from `Graph` to `Instance`, so the cascade that once destroyed
organization-scoped evidence is unreachable rather than merely guarded.

### `Instance` — asserted existence

"There is a cell here." One of `ENTITY`, `NATURAL_EVENT`, `PROTOCOL_EVENT`.
Exists because an entity carrying no measurements yet would otherwise vanish on
rebuild — existence is a claim like any other.

Carries `observed_at`: when the world was as the claim says — for an event, when
it happened; for an entity, when it was seen. Defaults to the assertion's
`asserted_at` when the writer says nothing, so the column is never null and a
time rule is total (RFC 0015). A duration is a metric; an event is a point in
time.

Carries `confidence`, optionally: how sure the claimant was, 0 to 1. Every claim
row has this column (RFC 0016); a null is silence, not a score, and a
`CONFIDENCE` rule admits only claims that carry a number. The database refuses
one outside the unit interval.

**Its `id` is the identity, and it is a bare uuid.** There is no `ref` column and
no `{age_name}:` prefix. The prefix made identity a property of a projection, so
one node could never be seen by two views, and it asserted a one-to-one
correspondence with an Apache AGE vertex that the merge case breaks. It is
emphatically not the AGE vertex id either — those are reassigned by exactly the
drop-and-replay `reproject` performs.

`Instance` never had a cached `stands` column, and now nothing does — the three that
did were moved to `CurrentStanding`. But the reason `Instance` is absent from that
projection too is different and still holds: whether a node stands can differ per
view, because a graph's selector decides whose claims it counts, so one
organization-wide boolean would be wrong the same way the prefix was. The other
three are organization-grain — a retracted metric is retracted everywhere.

### `Link` — a claim relating two things

One table, ten kinds. `source_ref` and `target_ref` are opaque bare uuids.
Every row carries `observed_at` like an `Instance` does: when the relation held,
when the classification was seen to apply, when the participation took place.
Same default, same meaning. And an optional `confidence`, like every claim.

| Kind | Says | Projected as |
|---|---|---|
| `INFORMS` | this structure is evidence for that node | nothing — it drives derivation |
| `CLASSIFIES` | this node is of that term | one of the node's **labels**, per view — a node is drawn under every category that admits it (RFC 0019) |
| `SAME_AS` | these two instances are one individual | nothing — it folds the **component** (`evidence/identity.py`) |
| `DIFFERENT_FROM` | these two instances are **not** one individual (RFC 0019) | nothing — it vetoes the direct `SAME_AS` between its ends in every fold; a disagreement through a third instance is reported as `conflicts` |
| `RELATION` | these two entities are connected | an edge |
| `PARTICIPATES_AS_INPUT` | this entity went into that event, in this role | an edge, entity → event |
| `PARTICIPATES_AS_OUTPUT` | that event produced this entity, in this role | an edge, event → entity |
| `MEASUREMENT` | this structure measures that entity, under this term | nothing — the typed form of INFORMS |
| `STRUCTURE_RELATION` | these two structures are related | nothing — structures are not vertices |
| `DERIVED_FROM` | this claim came from that claim (RFC 0017) | nothing — lineage between claims, read as `derivedFrom`/`derivations` |

Three of these are drawn. The rest are not, and it is not a gap. A structure
relation has both endpoints organization-scoped, so an edge in one graph's
projection would be the wrong place to keep it; `INFORMS`/`MEASUREMENT` move
derived values instead; `CLASSIFIES`, `SAME_AS` and `DIFFERENT_FROM` decide what a
vertex *is* rather than adding one; and `DERIVED_FROM` relates claims, not the things the
claims are about — its ends may be a metric, a structure or another link, none
of which is a vertex. It is written under the **same assertion** as the claim
that cites, because "this, because of that" is one act; every claim-making input
takes `derivedFrom`, and `supersedeMetricValue` cites the value it replaces on
its own.

### `Comment` — a remark about a structure

"This ROI looks mis-segmented." The port of lok's komment app, restated as
evidence: lok addresses a comment by `(identifier, object)`, which is exactly a
`Structure`'s identity, so here the comment points at the structure row and the
structure carries the thread — the same ROI discussed from two experiments is
one conversation. The rich body is lok's descendant tree
(LEAF/MENTION/PARAGRAPH), stored verbatim in one JSON column on the one row —
**never** as rows or vertices of its own — with `text` and `mentions` folded
from it at write time, because an append-only row has no after-the-fact to
derive them in. A mention names a **subject** (`Assertion.subject`'s
vocabulary), never a user row: the evidence layer holds no user foreign keys.
Threading is a `parent` FK to the same table, `PROTECT` where lok cascades.

What lok kept as mutable columns is evidence here: the author and time are the
`Assertion`; `resolved`/`resolved_by` are a `Standing` — see below — so
resolving, withdrawing and reopening are appended positions with provenance,
not state transitions. Comments take no part in any projection: a structure has
no AGE presence, so neither does its discussion.

### `Standing` — whether a claim still holds

"That still stands", or "that no longer does". `stands=True` attests,
`stands=False` retracts, and both are evidence of the same kind. `at` is the
position's world time — when it took effect, settable by the caller through
`retract*`/`attest*` inputs — and it is the column an `OBSERVED_AT` rule reads
over standings, so the name stays even though every other claim says
`observed_at`. A position may carry a `confidence` too — "I am fairly sure this
is gone" is a weaker retraction than a flat one, and an `EXISTENCE` rule may
say how sure a retraction has to be before it counts.

This replaced a `LifecycleEvent` whose `status` was an enum, and the change is not
cosmetic. A lifecycle event modelled retraction as a *state transition on a row*,
which made un-archiving something you do to the data. It is not: reinstating is
**new evidence, backed by somebody, that the thing exists** — and two people must
be able to disagree about that, exactly as they disagree about a category. That
is the same mistake `Link.Kind.CLASSIFIES` was introduced to undo, when
classification was a column written once and never updated.

So there is no "reinstate" operation and no state machine. There is only more
evidence, and the current answer is a fold over it (`evidence/claims.py`) —
**scoped by the reading graph's selector**, which is what lets one view hold that
a cell exists while the view next door does not.

Latest wins, by `(at, assertion.seq)`. `at` is when the claim took effect;
`Assertion.seq` breaks ties between claims written in one request. It is a real
total order over the organization's log — a Postgres sequence, allocated once per
assertion — not the `recorded_at` timestamp tiebreak this used to name, which
could collide within a transaction and left the fold order-dependent.

The folded answer lives in `CurrentStanding`, one row per claimed structure,
metric, link or comment. For a comment the fold doubles as **resolution**:
`stands=False` says the remark no longer stands — resolved by a reviewer or
withdrawn by its author, the standing's own assertion recording whose position
it was — and `stands=True` reopens it. One conflation, deliberate: both are
somebody's position that the remark no longer stands, and a separate resolution
axis would be a state machine wearing a new name. `Structure`, `Metric` and `Link` used to each cache it in a `stands`
boolean of their own; those columns are gone. They were mutable columns on log
tables that nothing may rewrite, which is a contradiction the append-only trigger
would now refuse outright.

---

## What is deliberately *not* in the log

**`State`** — the sufficient statistics each metric folds into. It is a cache of
the log, not part of it: `merge` / `retract` / `recompute` take no assertion, and
`refold_state` rebuilds the rows wholesale from the metrics. Its whole point is
that it stores *statistics, not answers*, which is why swapping `MEAN` for `MAX`
costs zero writes.

It is **organization grain**: one row per entity, no selector anywhere in the
fold. Which of those metrics a view counts is answered by
`projector._scoped_state` — at *materialization*, not on read, since each graph
has its own AGE namespace to materialize the scoped number into. Keeping a row per
view would mean naming a graph inside `evidence/`, which the second axiom forbids.

**`CurrentStanding`** — the folded "does this stand" answer, one row per claimed
structure, metric, link or comment. A cache of the log, not part of it: it carries no
assertion, `refold_current` rebuilds it wholesale, and it is deliberately mutable
where the log is not. Instances are absent on purpose — whether an instance stands is a
per-view question, since a graph's selector decides whose claims it counts, so one
organization-wide answer would be wrong for at least one projection.

**`StructureKind` / `MetricKind`** — organization vocabulary, minted lazily on
first write. The term is implied by the first `Structure` or `Metric` that uses
it, and each of those carries an assertion, so recording the minting separately
would add a claim nobody made.

**The ontology** (`core.Category`, `GraphSchema`) — a graph's rules, not evidence.
Versioned separately, and its provenance is `koherent`'s `ProvenanceField` rather
than an `Assertion`. Two provenance systems over the same rows would eventually
disagree. Note the *word* a category declares is evidence-side — that is `Term`
above — but what the word means in a given view is not.

---

## Which operation writes which claim

**Every one of these names a word, not a view.** An instance write takes
`term: "AIS"` — the `key` of an organization-scoped `Term` — and the request's
organization; it takes no graph and no `*Category` id. The word is minted on first
use, exactly as `StructureKind` and `MetricKind` are, so a fact can be recorded
before any view has been built to hold it.

They used to name a `*Category`, which belongs to one graph. That was the last
place a claim was stated through a projection, and it made the axiom above true of
the storage but not of the API: you could not say "there is an AIS here" until some
graph had declared "AIS", and the graph you happened to name leaked into a claim
that says nothing about graphs. The controller reduced the category to
`category.term` and `category.graph.organization` before writing anything, so
nothing was lost by asking for those directly.

**Every one is also named for the act it performs.** `assertEntityExists`, not
`createEntity`: nothing is created, somebody claims a thing is there, and a second
annotator may claim it is not. Retraction is `retract*`, not `archive*` — nothing
is put away, a `Standing(stands=False)` is written. The verbs match `attest*` and
`assertParticipation`, which were already right.

**And every one returns the same shape**: the `Assertion` it recorded, the thing
claimed, and `drawings` — every view that draws that claim afterwards.

- **A write under a word no view declares succeeds**, and comes back with
  `drawings: []`. A count, not a null. It used to return the node with a category
  borrowed from *some* graph — one that had not drawn it, picked by an unordered
  `.first()` — so two identical writes could report different categories with
  nothing about the claim to explain the difference.
- **A write under a word several views declare reports all of them.** It used to
  read itself back through the lowest-id view that drew it and discard the rest;
  the ordering that made that reproducible was damage control on a lossy shape.
- **A retraction's `drawings` is read back, not assumed empty.** Existence is
  folded under each view's own selector, so a view that does not count the
  retracting subject still draws the node — and the result says so.

There is no `lifecycle` field on any node. A node read out of a graph is one the
evidence says exists, so a flag beside it could only agree with its own presence;
where a claim stands is `drawings`, which says *where* rather than pretending
there is one global answer.

| Mutation | Writes |
|---|---|
| `assertEntityExists` | `Assertion`, `Instance(ENTITY)`, `Link(CLASSIFIES)`, plus `Structure`/`Metric`/`Link(INFORMS)` per supporting evidence |
| `assertStructureExists` / `ensureStructure` | `Assertion`, `Structure`, `Metric` |
| `assertMetricValue` / `assertMetricValueForStructure` | `Assertion`, `Metric`. The first mints the structure if it is new, as one act |
| `supersedeMetricValue` | `Standing(stands=False)` on the old metric, then a new `Metric` and a `Link(DERIVED_FROM)` from the new to the old, under **one** assertion — both stay on the record. Named for what it does: there is no in-place update |
| `linkStructureToEntity` | `Assertion`, `Link(INFORMS)` — how evidence is attached to a *live* entity |
| `assertNaturalEventExists` / `assertProtocolEventExists` | `Assertion`, `Instance`, `Link(CLASSIFIES)`, `Link(PARTICIPATES_AS_*)` per role |
| `assertParticipation` | `Assertion`, `Link(PARTICIPATES_AS_*)` |
| `assertParticipations` / `classifyNodes` / `retractLinks` | one `Assertion` over many subjects — a batch is one act, so the result carries one assertion and a list |
| `assertRelationExists` | `Assertion`, `Link(RELATION)` |
| `assertMeasurementExists` | `Assertion`, `Link(MEASUREMENT)` **and** `Link(INFORMS)` — the plain link is what `dirty()` matches, so without it nothing rolls up |
| `assertStructureRelationExists` | `Assertion`, `Link(STRUCTURE_RELATION)` |
| `commentOnStructure` | `Assertion`, `Comment`, and the `Structure` if the datum is new — one act. A reply names `parent` and must stay on its thread |
| `retractComment` / `attestComment` | `Assertion`, `Standing` on the comment — resolve/withdraw and reopen. `Comment.resolved` is the fold |
| every `retract*` | `Assertion`, `Standing(stands=False)`, the `CurrentStanding` row, and — for nodes — removal of the vertex |
| every `attest*` | `Assertion`, `Standing(stands=True)`, and the node redrawn into every view whose rules admit it |
| `createTerm` | a `Term`, or fills in the description of one an ingest minted bare — idempotent on `(kind, key)` |
| `updateTerm` | nothing in the log: descriptive fields only. `kind` and `key` are identity and cannot change, because every claim points at them |
| `deleteTerm` | nothing — refused while any claim or category names the word |

The vocabulary is readable and curatable through `terms` / `term` and the three
mutations above, alongside `structureKinds` and `metricKinds`. `Category.term`
and `Term.categories` navigate the join in both directions: a client showing a
graph wants the word behind a category, and one curating vocabulary wants every
view that speaks a word.

Corrections are additive throughout. There is no `updateEntity`, no
`updateNaturalEvent` and no `updateProtocolEvent`: they archived the node and
created a new uuid, so a correction forked identity and every metric and relation
keyed on the old ref stopped describing it. Their jobs are now done by
`linkStructureToEntity` (evidence), `assertParticipation` (who took part),
`Link(CLASSIFIES)` (what it is) and `attest*` (that it is there) — none of which
touch identity.

Write ordering is load-bearing: the **evidence is always written first**, and the
projection follows. Under Apache AGE the two stores could not share a transaction,
so a crash between them left evidence with no projection (which `reproject`
fixes) — and the other ordering left a vertex the log had never heard of, still
queryable, so links could be written naming a node that did not exist. With the
table projection the drawing commits in the *same transaction* as the assertion,
so the gap is gone in steady state — but the ordering rule stays, because it is
what keeps a backfill, a rebuild, and any future asynchronous projection kind
recoverable rather than authoritative.

---

## Reading it back

**Two grains, and the shape says which.** A *claim* read answers from these tables:
`instance(id:)`, `link(id:)`, `standings(id:)`, and every write payload
(`assertion` + `instance`/`link` + `drawings`). A *view* read answers from a
projection: `node(id:, graph:)`, `nodes(graph:)`, `entities(entityCategoryId:)` and
the rest, whose types carry a label, a category and derived properties because a view
is what supplies those — **so every view read names its view**, the singular
fetchers included. They used to take no graph and answer from `drawings[0]`,
whichever view `graphs_for_refs` yielded first, with nothing on the result saying
which; they now go through the same membership-then-drawing path as `nodes(graph:)`
(`api/queries/_nodes.py::one_in_graph`), so `node(id, g)` succeeds exactly when
`nodes(graph: g)` could list the node. Admitted but not yet drawn answers as the
bare row shape (no derived properties, categories from the rule, `graph` and `asOfSeq` named — RFC 0025); a node the view does not admit is refused,
and the claim-grain reader for it is `instance(id:)`. Nothing answers both grains at
once any more — the payloads used to, handing back an `Entity` for a claim that
might be drawn nowhere, and two of its fields (`schemaVersion` — since removed, RFC 0025 — and
`richProperties`) could not answer at all in that case. `Structure` and `Metric` are claim shapes
outright: neither implements the GraphQL `Node` interface, because neither has any
AGE presence for the interface's `label`/`externalId` to describe. And every `Edge`
the API builds is row-backed, so `Edge.assertion` is non-null and the
always-empty drawing fields (`properties`, `richProperties`,
`measuredFrom`/`measuredTo`) are gone from the edge types.

Whether a claim still holds is `standings`: every position anyone recorded, newest
first, with whose assertion — and an empty list meaning nobody has disputed it, since
silence is not dissent. **No folded boolean sits beside it.** For an instance there is
nothing honest to fold to: `CurrentStanding` holds no instance rows, because a graph's
selector decides whose claims it counts, so the only unscoped answer would be one no
view is obliged to agree with. The per-view answer is `drawings` — a view draws the
claim exactly when its own fold says it stands and its rules admit it.

**The log itself is readable as a log** (RFC 0020). `assertions(filters:)` lists
the acts by who made them, with what tool and when, newest first;
`assertion(id:)` is one act with `actionArgs` and every claim it recorded, in six
typed lists (`instances`, `links`, `metrics`, `structures`, `standings`,
`comments` — none narrowed by standing: a retracted claim was still written);
`standings(filters:)` is the organization's positions by who took them, on what
kind of claim and when, each with its `target`. `changes(afterSeq:, limit:)` is
the feed: ascending from a cursor and **cut at the committed horizon** —
`evidence/log.py` admits a row only when the transaction that wrote it precedes
every transaction still open, so a `seq` handed to a transaction that commits
late is withheld rather than skipped. `nextSeq` is the cursor for the next page
and `horizon` the highest seq the gate admits at all, which is how a client tells
"caught up" from "withheld" while a long-open writer stalls the feed. And
`Subscription.assertionRecorded` announces each act as its transaction commits,
in the organization's room, never one that rolled back.

**A graph is rules plus the log, materialized by an event. A read is a graph query
and nothing else.**

The projection is a fold over the log, and it runs at *materialization* —
`projector.project`, reached from every write, from `manage.py reproject`, and
from `manage.py rematerialize`. Everything a client can ask for is physically on
the vertex before the query runs: the derived value, and the statistics about it
(`n_evidence`, `spread`, `measured_from`, `measured_to`, written under a
`__stat__` prefix). A read touches AGE and nothing else.

This was not always so. The projection used to hold only the properties marked
`index=True` and `api/types` folded the rest per node at query time — which made
adding a property free and made a read `N × (1 + 3P)` Postgres round-trips for N
entities and P properties, unbounded in result-set size and unable to filter or
sort on anything lazy. `docs/ARCHITECTURE.md` §2.1 carries the full reasoning for
the reversal.

The trade, stated so nobody rediscovers it: **adding a property is no longer
free.** A category edit that moves its property hash redraws every vertex the
category draws (`api/mutations/schema/_rematerialize.py`), including an explicit
`REMOVE` for the keys a dropped property left behind — Cypher `SET` only adds, so
a value no rule still derives would otherwise answer queries forever. That redraw
is unbounded in graph size and there is no job queue here, so `manage.py
rematerialize` does the same work out of band; its `--stale` flag finds work by
comparing each vertex's `__schema_version` stamp against the graph's active
schema. Two exceptions remain deliberate: **edges derive nothing** (an edge
carries `category_id` and `__assertion_count`), and **provenance drill-down stays
a Postgres lookup** — `contributing_assertions` and `supporting_evidence` return
rows for one already-selected node, and nothing filters or sorts on them.

`manage.py reproject` is the stronger tool, and the one to reach for when
*membership* is wrong rather than the values: it drops a graph's AGE namespace and
rebuilds it from Postgres alone, which is also the honesty test. `tests/projector/`
holds the guards that this reproduces what was there.

Three things scope a read — or more precisely, scope the materialization a read
then traverses. They are deliberately the same shape, "which claims count", asked
of three tables:

- **`Graph.selector`** — `selector.metric_filter` over `Metric` (which
  measurements a derived property counts), and `selector.claim_filter` over
  `Standing` (whose word decides a node exists). Shape: structure kinds,
  `assertion_filter` (subjects, app_ids, action_names), `as_of`,
  `observed_window`. **Changing a selector requires a reproject** — the projection
  caches the answer the previous one produced.
- **`Category.definition`** — `selector.classification_filter` over
  `Link(CLASSIFIES)`. What a term *means in this graph*. Empty means primitive:
  membership is whatever was asserted. Non-empty makes it a defined category, so
  "AIS" can mean "asserted AIS by Johannes before August" here and something else
  next door, with no evidence rewritten.

  `asserted_as` names **one word or several**, and several means *any of* — a
  view's "Neuron" may be "anything claimed Pyramidal or Interneuron". Note the
  asymmetry with `Category.term`: a category *derives from* many words and
  *asserts as* one, because creating an entity of it claims exactly one word.
  The words it derives from need not be words this graph declares a category
  for; `term_ids_for` widens membership to cover them, which is what makes a
  definition a definition rather than a rename.
- **Graph membership** — `selector.nodes_for` and its inverse
  `graph_ids_for_node_ids`, the only two places it is decided, over the term set
  `selector.term_ids_for` computes. A graph contains a node when it declares a
  category for the word the node was claimed under, **or** one of its definitions
  derives from that word. It used to be decided in five places by testing a
  substring of the node's name, and a node could belong to exactly one view; it
  can now belong to several.

---

## Known gaps

Recorded so nobody has to rediscover them.

- ~~**No total order.**~~ **Closed.** `Assertion.seq` is a monotonic `bigserial`
  assigned by the database. It sits on the assertion and nowhere else, because an
  assertion is already the unit of authorship — a set of claims made together by one
  actor in one act is one assertion — so one column orders the whole log while the
  rows written under one assertion stay simultaneous, which is what they are.
  Identity stays the `uuid4`: clients hold it, and a sequence would leak insertion
  order into an external handle.

  The existence fold ties on `(at, assertion.seq)` where it used to tie on
  `(at, recorded_at)`, and `refold_state` replays in `seq` order where it used to
  replay in `observed_at` order — world time, which is backfillable, freely settable
  by the caller and has no tiebreak. Most of `state.merge` is a monoid and did not
  care; `last_ts` (which compares with `>=`) and `high_water_assertion` (assigned
  unconditionally) did, and were nondeterministic across a rebuild.

  ~~**Still open, one level down:** `seq` is assigned at insert, not at commit, so a
  reader polling `seq > cursor` can permanently skip a row that committed late.~~
  **Closed, differently than proposed.** A catch-up projector exists now
  (`manage.py reproject --incremental`) and it does not poll `seq > cursor` at
  all. `GraphController._create_assertion` writes a `PendingProjection` row — an
  outbox — in the same transaction as the assertion, and the write deletes it *by
  id* once its synchronous projection finished. The cursor a view reports
  (`Graph.projection { projectedThroughSeq }`) is **derived**:
  `min(min_pending_seq − 1, max_seq)` for a consistent graph. An uncommitted lower
  seq either rolls back or commits together with its outbox row, which pulls the
  cursor under it; a commit-then-crash leaves the row. So neither hazard can put
  a claim above the cursor that the drawing has not seen, without any snapshot
  gating and without serializing appends. `graph_engine/watermark.py` states the
  invariant; `graph_engine/models.py` explains why nothing stores a per-graph
  "applied through" (the first design did, and it stored a lie). The *client*
  feed, `changes(afterSeq:)`, has no outbox to read and uses the snapshot gate
  the help text proposed after all — `evidence/log.py`, RFC 0020, which also
  records the one residual window (inside a single `INSERT`) and the stall a
  long-open writer causes.
- **`Assertion.action_name` has no source.** `action_id` and `action_args` are
  populated from the Rekuest provenance token that `AuthentikateExtension` puts on
  the kante context, and `manage.py redact` writes all three. But no provenance
  token carries a human-readable name for the action, and neither does
  `koherent.Task`, which is built from the same claims — so the `action_names`
  branch of every selector filter is still dead. Filter on `action_id`, which is
  real. Giving `action_name` a value would mean inventing one.
- ~~**One label per node.**~~ **Closed** (RFC 0019). Apache AGE permitted one
  label per vertex, and the refusal of a node two defined categories admitted
  outlived AGE by a year. Labels are rows on `ProjectionLabel` now, one per
  (vertex, category): a node is drawn under **every** category of the view that
  admits it, existence folds per category, and properties are the union. The
  one refusal left is a key two of the node's categories define *differently*
  — one vertex has one value per key.
- ~~**No merge.**~~ **Closed.** `Link.Kind.SAME_AS` is the claim and
  `evidence/identity.py` is the fold. The shape worth keeping in mind: **every
  observation mints its own instance.** Saying "this is an AIS" writes a *fresh*
  `Instance` — nothing reuses an id, because an observation cannot be asked to know
  about a prior one — so identity *between* observations is a claim in its own
  right, contestable and retractable like any other. Saying "this is AIS **6**"
  records four things under **one** assertion: the term if it is new, the
  instance, the `INFORMS` claim, and the `SAME_AS` claim. One act, one assertion,
  because `Assertion.action_id` — the field that would tie two calls back together
  — is never populated.

  `InstanceIdentity` is the persisted union-find, at organization grain like `State`,
  with the **lowest uuid** as representative so identity does not depend on
  arrival order. Only merged nodes get a row; a component of one is the absence of
  one. Union is incremental, retraction cannot un-union so it flags the component
  and `recompute` rebuilds it, and `manage.py rebuild_identity --check` is the
  backstop that says whether the two agree.

  Sameness has a negative (RFC 0019): `Link.Kind.DIFFERENT_FROM`, written by
  `assertDifferentInstance` one claim per pair, read under the same `SAMENESS`
  rule. Every fold applies one rule through `identity.admitted_sameness`: a
  standing, trusted difference removes the *direct* `SAME_AS` between its two
  ends and nothing else. Two instances still joined through a third stay one
  component, and the panel reports the difference as a **conflict** for a
  person to settle — the fold does not guess whose other claim to drop.

  Still true, and now literally so: **do not assume a vertex's `id` property is
  the identity of one observation.** A vertex stands for every member of an
  individual, and its `id` is the representative — the lowest of them.
- ~~**A merged component is not drawn as one vertex.**~~ **Closed** (RFC 0018).
  The fold answered "what is known about this thing" — `evidence/panel.py`
  unions labels, sameness and connections over the component — but `projector`
  drew one vertex per `Instance`, so two instances claimed the same appeared
  twice in every view and once in the panel. A view now draws one vertex per
  **view-scoped** component (`identity.view_components`: the `SAME_AS` claims
  the members' category trusts), lists the members on `ProjectionMember`, folds
  derived properties over all of them, and lands every edge to any member on
  the one vertex. Merge and un-merge are redraws of the touched individuals
  (`projector.converge` widens the touched set to whole components) rather than
  edge re-pointing. The organization-grain cache stays what the panel reads; a
  view's `members` and the panel's `component` may disagree, and that is each
  answering its own question.
