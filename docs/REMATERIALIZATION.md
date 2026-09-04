# Rematerialization — when a vertex gets redrawn, and by whom

*Canonical. `api/mutations/schema/_rematerialize.py` and
`core/management/commands/rematerialize.py` point here; where their docstrings
and this file disagree, this file is the one to fix.*

## Why anything has to be redrawn at all

A node's *properties* are a graph query and nothing else. Whatever a client can
ask about a drawn node's derived values is a property **on the vertex** before
the query runs — the projection folds nothing at read time. (Which nodes a view
*holds* is a different question, answered from the claims by the view's rule —
`api/queries/_nodes.py` — whether or not the drawing has caught up; the drawing
supplies the properties where there is one.)

That was not always true. While the projection held only the `index=True`
properties and `api/types` derived the rest per read, a category's properties
could be edited for free: the read applied whatever the definition said *at that
moment*, so a vertex could not be stale. `projector.derive_properties`' docstring
names this as the trade it made. Rematerialization is the bill.

So: **change what a category means, and every vertex it draws is now wrong.**
Something has to rewrite them.

## The two halves

| | in-request | out of band |
|---|---|---|
| where | `api/mutations/schema/_rematerialize.py` | `manage.py rematerialize` |
| trigger | the properties hash moved | you ran it |
| scope | the one category just written | `--graph` / `--all`, optionally `--category`, optionally `--stale` |
| can retire orphaned keys | **yes** | no (see [Retired keys](#retired-keys-the-one-thing-only-the-mutation-can-do)) |

They call the same function — `projector.rematerialize_category` — and differ
only in what they know and what they select.

## The trigger: a hash, not a mutation

`fingerprint(category)` is taken **before** the write and compared after:

```python
@dataclass(frozen=True)
class Fingerprint:
    properties_hash: str          # compute_properties_hash(property_definitions)
    derived_keys: frozenset[str]  # projector.derived_property_keys(category)
```

`rematerialize_if_moved` redraws only if `properties_hash` changed. Two
consequences:

- **A mutation that changes nothing costs nothing.** Most `update_*_category`
  calls are relabelling — a new colour, a description, a pin — and an equal hash
  returns without touching the drawing. This is the common case, and it is the reason the
  synchronous redraw is tolerable at all.
- **The hash answers a question `created` cannot.** `create_*_category` is an
  `update_or_create` and the manager swallows the `created` flag, so a "create"
  landing on an existing category is indistinguishable from an insert at the
  resolver. Comparing fingerprints asks the question that actually matters: did
  the properties *move*.

The snapshot has to be taken before the write because **nothing versions
`Category.property_definitions`**. One line after `save()`, what the old
definition owned is gone, and with it the knowledge of which vertex keys are now
orphaned.

### The case the hash cannot see

`EntityCategoryManager` keeps the previous definitions when the incoming list is
empty (`property_defs or category.property_definitions`), so **clearing the last
property is unreachable through the API** and the hash does not move. Partial
removal — dropping one of several — works, and is what the tests exercise.

## Retired keys: the one thing only the mutation can do

`write_properties` only adds and overwrites. Anything a previous pass wrote that
this one does not would sit on the vertex forever, answering queries with a value no
rule still derives — and nothing would correct it, because the code that would
have is exactly the code that stopped running.

So `rematerialize_category` **clears, then redraws**: it `REMOVE`s every key the
category can own and lets `project` immediately re-`SET` whatever still derives.
Three ways a key goes stale, and only the first is a difference between before
and after:

1. the property was dropped from the definition — this is `retired_keys`;
2. the property stayed but stopped deriving: `derive_properties` writes a key
   only `if value is not None`, so re-pointing a rule at a structure kind with no
   evidence leaves the old value in place;
3. the statistics are conditional: `_property_statistics` omits `spread`, `from`
   and `to` when the state has no bounds, so a value can outlive its own evidence
   window.

Cases 2 and 3 are covered by sweeping the currently-owned set, which either half
can compute. Case 1 needs `before.derived_keys - after.derived_keys`, and only
the mutation holds `before`. **The command deliberately passes no
`retired_keys`** — out of band there is no record of what a *former* property
owned. It repairs a stale value; it cannot reach an orphan from a property that
is already gone. `manage.py reproject` can, by dropping the namespace entirely.

## Why the in-request half is synchronous, and what that costs

It runs inside the request and is **unbounded in the size of the graph**:
`refs_drawn_as` resolves every node the graph contains, and `project` issues one
projection write per drawn vertex — per *individual* since RFC 0018, with the
derived properties folded over its members. A category drawing a hundred thousand
entities is not a mutation any client should wait on.

The in-request redraw a *write* triggers is the other shape: `projector.converge`
over the refs the write touched. It widens that set to whole individuals before
erasing anything — the members of every vertex holding a touched ref, and the
view-scoped sameness closure of the touched refs — so a merge or a split redraws
both individuals concerned and nothing outside them moves.

This service has no job queue to hand it to. `channels-redis` is present, but for
subscriptions; introducing a worker is a deployment change, not a code change. So
the limit is **accepted and stated** rather than hidden, on three grounds:

- it is no worse than what already ships — `backfill_category` runs `rebuild`
  over an entire graph inside `create_*_category`;
- an unfinished redraw is **detectable, not silent** (next section);
- `manage.py rematerialize` finishes the job out of band, the same escape hatch
  `manage.py reproject` already is for a projection behind its log.

## Detecting an unfinished redraw

`graph_engine.models.Projection.schema_hash` records, per graph, the
`GraphSchema.hash` the drawing was last **fully** derived under. A graph whose
recorded hash is not the active schema's has not been redrawn under the rules
currently in force, and `manage.py rematerialize --stale` selects on exactly
that — `graph_engine.watermark.schema_stale(graph)`, a Postgres comparison.

It used to be a count over the drawing of vertices whose `__schema_version` stamp differed
from the active hash. The stamp is still written (it is honest projection-internal
bookkeeping), but the *ledger* of "which schema is this drawing at" cannot live
only inside the cache it audits: the `reproject` that fixes a stale drawing
destroys the stamps, and an operator could not ask Postgres whether a graph was
behind.

Who writes the hash, and when:

- `rebuild` (a full `reproject`) and `materialize(backfill=True)` — the active hash,
  since everything was just derived under it;
- `manage.py rematerialize` — at the end of its per-graph loop, after **every**
  node category of the graph has been redrawn. Not inside `rematerialize_category`:
  one category redrawn out of several is not a graph that is current, and
  `--category` deliberately leaves the ledger alone for that reason;
- the in-request `rematerialize_if_moved` — only if the graph was current *before*
  the mutation (the fingerprint records that); otherwise an older debt would be
  hidden behind a fresher stamp. When the properties did **not** move it still
  records the new hash, because a relabel changes no derived value and the graph is
  as current under the new version as it was under the old.

A graph with **no active schema is never stale** by this test — there is no
version to be behind — because `--stale` exists precisely to make the sweep cost
nothing when nothing is owed. It is the usual invocation for that reason.
`Graph.projection { schemaStale }` reports the same answer to a client.

## Ordering: backfill first, then rematerialize

`create_*_category` runs both when asked to, and in that order. A backfill goes
through `project_all` / `rebuild` and does re-derive every property — but it
derives with `SET`. It widens **membership** and has no reason to know that a key
on an existing vertex is now an orphan. Sweeping those is
`rematerialize_if_moved`'s job alone, so it runs *after* the backfill, not
instead of it.

## Node categories only

`projector.project_edges` writes `category_id` and `__assertion_count` onto an
edge and nothing else. No derivation rule has ever run for a `RelationCategory`,
so **there is nothing on an edge that can go stale**, and both halves select only
`EntityCategory`, `NaturalEventCategory` and `ProtocolEventCategory`.

The `# TODO: Rematerialize` comments that used to sit in the edge mutations were
describing work that does not exist. That `create_relation_category` accepts
`properties` at all is a separate gap, recorded in `docs/ARCHITECTURE.md`.

## Choosing between this and `reproject`

Both exist; they are not interchangeable.

- **`rematerialize`** rewrites properties on vertices that stay where they are.
  Reach for it when only the *values* are wrong.
- **`reproject`** drops the namespace and replays it from evidence. Reach for it
  when *membership* is wrong — a `definition` changed, or a node belongs under a
  different label. It is also the only thing that can clear an orphaned key
  nobody snapshotted.

**Narrower is not cheaper at every scale.** `rematerialize_category` resolves
graph membership once per category, so `--all` over G graphs with C node
categories each pays G×C full membership resolutions, where `reproject`'s
per-graph `rebuild` pays G. Naming a `--graph` and a `--category` is where
`rematerialize` wins; a whole-estate sweep is not, and `reproject --all` is the
better tool for that.

## Not versioning

`graph_engine/versioning.py` emits a new `GraphSchema` when the *ontology*
changes, driven by a `post_save`/`post_delete` signal on the category models. It
is a different question with a different trigger: versioning asks "did the schema
change", rematerialization asks "are the drawings still right". They meet in one
place only — the schema hash a version carries is what `--stale` compares vertex
stamps against.
