# RFC 0003 — What should a write return when no graph draws the node?

- **Status:** **Implemented** — option F shipped, and B with it. This file is kept
  as the record of why, not as an open question. The defect described in §2 is
  fixed: `RetrievedNode.from_row` borrows no category, and `node_result` /
  `projected_node`'s first-view-wins read are gone.
- **What shipped:** writes are named `assert<Thing>Exists` / `retract*` and return
  the assertion they recorded, the thing claimed, and `drawings` — every view that
  draws the claim afterwards, empty when none does. `lifecycle` went with it: a
  node in a graph is one the evidence says exists, so where a claim stands is
  `drawings` and nothing else. Option E was rejected as described below.
- **Where the code is:** `graph_engine/results.py` (the shape and the reasoning),
  `GraphController.drawings_for_node` / `drawings_for_edge` (the read-back),
  `api/types.py`'s `*Assertion` types, and `docs/LOG.md`'s operation table.

## The situation

Since the write API started naming terms, a claim can be recorded under a word no
view declares. That is the point of the word being the organization's rather than
a graph's — `evidence.writer.ensure_term`'s docstring says refusing a claim
because nobody had declared the word would be refusing a fact on a bookkeeping
technicality.

So `create_entity` has to hand back *something* for a node with no vertex.
Today `GraphController.node_result` does this:

```python
try:
    return self.projected_node(node)   # every graph declaring the term, in pk order
except ValueError:
    return retrieved.RetrievedNode.from_row(self, node)
```

`from_row` builds a `RetrievedNode` with `row_id` set, `id=0`, `graph_name=""`, a
`label`, and properties `{id, category_id, __lifecycle_state}`. The API layer
already knows how to be honest about the missing projection: `Node.graph_id`
returns null for a row-backed node, `Node.graph` returns null, and
`unique_id`/`global_id` fall through to the primary key, which is the real
identity anyway.

**This replaced raising, and that was right.** `create_entity` used to end with
`ValueError("... no category in {age_name} admits it")` and `create_event` with
an `IndexError` from indexing an empty Cypher result — both saying "your claim
was rejected" about a claim that had been durably recorded a moment earlier.
Nothing in this RFC proposes going back.

## 1. Is a `RetrievedNode` the right shape at all?

Arguments that it is:

- **The identity is real.** `Node.id` *is* the identity — a bare uuid, not an AGE
  vertex id — so a node with no vertex is fully addressable. Nothing about the
  return value is a placeholder except the projection-shaped fields.
- **One shape for the caller.** `RetrievedStructure.from_row` and
  `RetrievedEdge.from_link` already make the same move, and structures and
  metrics are *never* projected. `api/types.py` reads one shape whether there is
  a vertex behind it or not.
- **It is not a special case, it is the general one.** Evidence is the source of
  truth and AGE is a droppable projection. A node with no vertex is a node whose
  cache is empty, which is also every node's state immediately after
  `manage.py reproject` drops the namespace.

The argument that it isn't: the type is named for retrieval *from a graph*, and
carries `graph_name`, `id`, `label` — three fields that mean nothing here.
`id=0` in particular is a sentinel that only stays harmless because
`is_row_backed` is checked at the API boundary before it is read.

## 2. The concrete defect: the category is borrowed, and borrowed at random

*(Fixed. Kept because it is the argument for the shape that replaced it.)*

`from_row` picks the category like this:

```python
category = core_models.Category.objects.filter(term_id=row.term_id).first()
```

**No ordering.** Compare its two siblings, both of which were deliberately made
deterministic:

- `controller._category_for_term` — `queryset.order_by("pk").first()`, with the
  comment *"'Any view's' is the lowest-id one, not whichever the database
  happened to return. Writes no longer name a graph, so this decides what a
  mutation reports its result's category as, and two identical writes have to
  agree."*
- `projector.graphs_for_refs` — `.order_by("pk")`, with the comment *"Unordered,
  two identical writes in an organization whose graphs share a word could return
  different categories, and nothing about the claim would explain the
  difference."*

`from_row` is the third path answering the same question and it is the one that
was missed. Two identical writes under an undeclared word can therefore report
different `category_id`s and different `label`s.

Worse than the non-determinism: **any ordering is borrowing.** The node is in
*no* projection — that is why we are in this branch — so whichever category
`filter(term_id=...)` returns comes from a graph that either does not draw the
node or refused it by definition. The returned `label` is `category.age_name`
from a view the node is not in.

## 3. The options

### A. Status quo

Cheap. Keeps the two problems in §2.

### B. Stop borrowing: `category = null`, `label = term.key`

If no view draws the node, report no category and label it with the word that was
actually claimed. `RetrievedNode.category_id` already documents `None` as an
ordinary answer:

> *"`None` is an ordinary answer, and used to raise. A node names a word, and a
> category is one view's rule for that word — so a node claimed under a word no
> view declares has no category."*

This makes the returned object say exactly what happened: here is your node, here
is the word you claimed it under, no view draws it. It removes the ordering
question by removing the choice. `api/types.py` resolves `category_id` through
per-graph loaders that already tolerate null.

The cost: a client that renders `category.color` gets nothing to render. That is
accurate — the colour it was getting belonged to a graph the user may not even be
looking at.

### C. B, plus a distinct GraphQL shape

Give the undrawn case its own type (or an interface field like
`isDrawn: Boolean!`) so clients discriminate statically instead of null-checking
`category`. More API surface; better ergonomics. Worth doing only if clients
turn out to need the distinction — it is additive on top of B, not an
alternative.

### D. Refuse the write

Rejected, and already rejected once. See the top of this file.

### F. The mutation is misnamed, and the return should be a composite

Raised after the first draft, and it reframes the whole question — the others
argue about what to put in a node-shaped hole, this one says the hole is the
wrong shape.

**On the name.** `create_entity` describes a row being made. Nothing here creates
an entity: the mutation records that somebody claims one exists. Everything else
in this codebase already speaks that way — the retraction is
`Claim(stands=False)`, the correction is `attest*` writing `Claim(stands=True)`,
and CLAUDE.md states outright that *"existence is evidence, and two people may
disagree about it"*. `create*` is the last verb still implying that the writer
owns the fact. `assertExistence` — or `assert*` across the family, matching
`attest*` — says what happens. The tell is that the current name has no honest
answer for a second caller claiming the same thing: "create" implies a duplicate,
while what actually happens is a second assertion of one existence, which is the
whole point of counting agreement.

**On the return.** A `RetrievedNode` is a projection-shaped object, so returning
one forces every non-projection fact into a null: no vertex, no category, an
`id=0` sentinel, an empty `graph_name`. Options B and C above only make those
nulls more honest. The composite makes them unnecessary:

```
AssertionResult
  assertion   — who claimed it, with what tool, when       (evidence.Assertion)
  node        — the durable identity and its term          (evidence.Node)
  drawings    — [{ graph, category, vertex }]              (zero or more)
```

Three things fall out, and the third is the one that makes this more than
cosmetic:

1. **"No graph draws it" stops being an error case.** It is `drawings: []` — a
   count, not a null, and the same field a client reads either way. §2's question
   ("which category do we borrow?") disappears, because nothing is borrowed:
   every category reported is one that actually drew the node.
2. **The assertion becomes addressable.** It is the row that carries subject,
   `app_id`, `measured_at`/`asserted_at` and the log position `seq` — the things a
   client needs to say "the claim I just made" — and today the write returns no
   handle to it at all.
3. **It fixes the *drawn* case too, which nobody had flagged as broken.**
   `projected_node` iterates `graphs_for_refs` and **returns the first graph that
   succeeds**. A node drawn in three views is drawn in three views; the current
   return picks the lowest-pk one and silently discards the rest. The `.order_by("pk")`
   that makes this deterministic is doing damage control on a lossy shape — it
   guarantees the same view is picked every time, not that picking one is right.
   `drawings` is a list because the underlying fact is a list.

**Costs, stated plainly.** It is a breaking API change across the whole instance
write surface (`createEntity`, `createNaturalEvent`, `createProtocolEvent`,
`createRelation`, `createMeasurement`, and the `attest*` family), and every client
that reads `createEntity { id }` today would read
`assertEntity { node { id } }`. It also needs a decision on what `vertex` inside a
drawing carries — the derived properties are per-graph, so `RetrievedNode` does
not vanish, it moves inside `drawings[]` where its `graph_name` and `label` are
finally true.

**This is the most likely right answer, and it is not this RFC's to settle.** It
is an API redesign with a migration path, not a fix to a fallback branch. If it is
adopted, B is subsumed and C is unnecessary. If it is deferred, B remains the
cheap correct step and is compatible with F landing later — B removes a borrowed
category, and F removes the need to have one.

### E. Materialize the node in a non-graph "evidence view"

The proposal that motivated this RFC: give the organization a projection that
draws everything, so a node always has *something* to be read back through, and
the fallback disappears.

**Recommend against**, for four reasons:

1. **It needs a category per term.** AGE requires exactly one label per vertex,
   and `resolve_categories` gets that label from a `Category` row. A view drawing
   every word must therefore declare a category for every word — auto-minted on
   every `ensure_term`. That is the opposite direction from
   [RFC 0001](0001-materialized-categories.md), which argues the category row
   should get *smaller* and rarer, and it would make every ingest a schema write.
2. **It contradicts what a graph is.** CLAUDE.md: *"a view is only a view"*, and
   membership is a selection. A graph with no selector is not a view of the
   evidence, it is a second copy of it — and one that has to be kept in sync by
   the same projection machinery whose whole justification is that it is
   droppable.
3. **It makes the projection non-optional.** Right now a node's existence does
   not depend on AGE being reachable or current. Under E, "the node has a
   reference" becomes "the universal projection succeeded", so a projection
   failure becomes a write failure — reintroducing the coupling that
   `node_result` was written to remove.
4. **The reference already exists.** The thing E wants — a durable handle to a
   node no graph draws — is `Node.id`, and `from_row` already returns it. The
   gap is not the reference; it is the *label and category* draped over it, which
   is what B fixes directly and at no cost.

The one thing E gets right is the intuition that undrawn nodes should be
*findable*. That is a query-surface question — "list nodes in this organization
whose term no view declares" — and it does not need a projection to answer;
`evidence.selector` already knows which terms each graph declares.

## Recommendation

1. **Keep returning something.** The write succeeded and the identity is real;
   raising is not on the table.
2. **F is the right shape**, and the question it answers is bigger than the one
   this RFC opened with: the return is lossy for nodes drawn in several graphs,
   not only awkward for nodes drawn in none. Treat it as an API redesign with its
   own migration plan rather than folding it in here.
3. **Adopt B in the meantime.** Where there is no projection, return
   `category: null` and label the node with its term's key. It removes the
   unordered `first()` by removing the need to choose at all, and it is the
   subset of F that needs no schema change — so it is not throwaway work.
4. **Drop C.** It was an ergonomic patch over a nullable field; F removes the
   nullable field.
5. **Reject E.** Its cost is a category per term and a projection on the critical
   path of every write; its benefit is a reference that already exists.

If neither B nor F is adopted, then at minimum `from_row`'s
`filter(term_id=...)` should be ordered by pk, so it agrees with
`_category_for_term` and `graphs_for_refs`.

## See also

- [RFC 0001](0001-materialized-categories.md) §1 — why a category cannot be
  conjured per term cheaply.
- `docs/ARCHITECTURE.md` §4.1 — evidence is the source of truth, AGE is a
  projection.
