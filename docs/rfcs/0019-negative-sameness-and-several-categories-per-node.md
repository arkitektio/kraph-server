# RFC 0019 — Negative sameness, and several categories per node

- **Status:** Implemented.
- **Question:** Two limits on what a view could say about an individual. First,
  sameness had no negative: `SAME_AS` was the only identity claim, so "these
  two are *not* one cell" — the ordinary correction when a merge was wrong —
  could only be said by retracting somebody else's claim, and nothing recorded
  that the question had been settled. Second, a vertex carried **one label**:
  `resolve_categories` refused any node two defined categories admitted
  (`projector.py`, the "matches more than one" branch), a limitation of Apache
  AGE's label model that the table projection never shared. "Pyramidal" and
  "Excitatory" are not a disagreement. Should a view be able to say that two
  instances are different, and draw one node under every category that admits
  it?
- **What was done:** `Link.Kind.DIFFERENT_FROM`, the mirror of `SAME_AS`, read
  under the same `SAMENESS` rule, with one deterministic fold rule: a standing,
  trusted difference vetoes every *direct* sameness between its two ends, and a
  disagreement through a third instance is reported as a **conflict** rather
  than resolved by guessing. And a vertex is drawn under **every** category
  that admits it — labels live on `ProjectionLabel`, one row per (vertex,
  category); `resolve_categories` answers a list; existence folds per category;
  properties are the union, and a key two of a node's categories define
  *differently* is the one refusal left.

## Changes

### DIFFERENT_FROM

`evidence.Link.Kind.DIFFERENT_FROM` (`core.enums.LinkKind` too; migration
`evidence/0014`). Endpoints are two instances, refs bare uuids as everywhere
(`api/types.py::_ENDPOINT_TABLES`). `assertDifferentInstance(instances: [a, b,
c])` writes every pair among them under **one assertion**, because difference
is not transitive: "a, b and c are all different" is three claims.
`retractDifferentInstance(id:)` withdraws one. The claim carries `observedAt`,
`confidence` and `derivedFrom` like any other, and a `Difference implements
Edge` subtype is registered (`tests/test_print_schema.py` would fail at runtime
otherwise).

**The fold rule**, applied through one function, `identity.admitted_sameness`,
by every fold there is — `view_components` / `component_refs_for_view` (the
view), `recompute` / `refold` (the organization cache), `merge` at write time
(a direct veto means no union; the write still records the claim) and
`rebuild_identity --check`:

> A standing `DIFFERENT_FROM(a, b)`, trusted under the same `SAMENESS` rule as
> the claim it contradicts, removes every `SAME_AS` between exactly a and b,
> in either orientation, from the fold. It does nothing else.

So a component held together through a third instance (a~b, b~c, a≠c) stays
whole. The fold does not pick which of the other claims to drop — any choice
would be a guess about somebody's evidence — and the panel reports the
difference as a **conflict**: `Known.conflicts`, the standing differences whose
two ends are still members of one component, surfaced as `Node.conflicts` (view
grain, `Difference` edges) and `Instance.conflicts` (organization grain,
`Link`s). Settling it is a person retracting one of the claims that disagree.
`Node.differentFrom` / `Instance.differentFrom` list the standing differences
touching the node, beside `sameAs`.

Union-find has no split, so a difference written into a component is handled
the way a `SAME_AS` retraction already was: `identity.separate` flags the
component `needs_recompute` and rebuilds it on the spot, and the controller's
`_reproject_claim` redraws the touched individuals in every view. A view whose
category does not trust the claimant ignores the difference exactly as it
ignores an untrusted sameness — the rule is the category's (RFC 0009), and a
rule covering `SAMENESS` covers both kinds.

### Several categories per node

**The drawing.** `ProjectionVertex.label` and `category_pk` moved to
`graph_engine.models.ProjectionLabel(graph, vertex, label, category_pk)`,
unique on `(vertex, category_pk)` — migration `graph_engine/0009`, which gives
every existing vertex its one label row so the drawing stays addressable until
`manage.py reproject` redraws the unions. The composite foreign key
`(graph_id, category_pk) REFERENCES core_category (graph_id, id) ON DELETE
CASCADE` (RFC 0006) is re-declared on the label table, so the database still
refuses a vertex drawn under a category its graph does not declare. A category
delete now cascades **its label rows** and nothing else; a vertex whose last
label went is a node the view no longer admits, and the
`projectionlabel_last_label_deletes_vertex` trigger deletes it (edges and
members go by the existing SQL-level cascades). `0010` rewrites the label
table's `vertex` FK to cascade in the database, for the reason `0005`/`0008`
give, and rebuilds every namespace: the per-category vertex views join the label
table, so a node in two categories appears in two element tables of the
property graph — which SQL/PGQ allows, and which is what `MATCH (a IS
"Excitatory")` should find.

**The protocol.** `draw_node(graph, ref, categories: [(label, category_id),
…], kind, members)` — non-empty, and the label set is *replaced* on a redraw
(new labels are inserted before stale ones are deleted, so a redraw never
passes through an empty set and trips the trigger). `write_properties(graph,
ref, values)` lost its label argument — the values are the vertex's, not one
label's. A drawn record is `{id, label, labels, properties, members}`: `labels`
sorted, `label` the first of them for a reader that shows one; the identity
trio on the vertex is `{id, category_ids, type}` (`_VIRTUAL_KEYS`), and a
`category_ids EQUALS/IN` predicate in `list_drawn` asks whether the value is
*among* them. Saved-query plans are unchanged: `__label`/`__category_id` stay
singular per element table, because each element table is one category's view.

**The rule.** `resolve_categories(graph, nodes)` returns `dict[ref,
list[Category]]`, sorted by pk. A node's categories are the **union** of every
defined category whose definition admits it and every primitive category
declaring a word a standing classification of it names — a graph with no
definitions behaves exactly as before. The word the node was minted under
(`Instance.term`) is what it falls back on only when *nothing* classifies it
(a legacy row, or a node created before classification was a claim): a node
whose every classification is retracted is not thereby back under the word
nobody claims. Existence then folds **per category**, each under its own
`trust_filter(kind="EXISTENCE")`: a category whose rule counts the retraction
is removed from the node's list, a category that does not trust the retractor
keeps it, and a node with no category left is not drawn. Two refusals remain,
both reported through the existing skip mechanism with a reason: no category
admits it, and — new — *the node's categories disagree about a property*.

**Properties.** The vertex's values are the union over its categories
(`derive_properties` + `_property_statistics` per category, `valid_from` /
`valid_to` widened to the outermost window). One vertex has one value per key,
so a key two of a node's categories both define is a **conflict** unless the
two definitions are identical — same `PropertyDefinitionInput` and same
category `definition`, because a rule-bound property's meaning includes the
clauses it folds under. `projector.property_conflicts(categories)` names the
pair; the node is skipped with `drawn under categories that disagree: property
'avg_length' is defined by both AIS and Excitatory and would not mean one thing
on one vertex`. This is the honest form of the old one-label refusal: it fires
for the one case where the drawing really could not carry both answers, and
for nothing else.

**Individuals (RFC 0018).** Two nodes may union when their category sets
intersect — `identity._trusted_in_view` folds a `SAME_AS` under every category
its endpoints share, and one trusting category is enough — and the vertex is
drawn under the union of its members' categories. `representatives_admitted_by
(category)` walks `component_refs_for_view` rather than `view_components` over
one category's refs, because a member may hold another category whose sameness
trust joins it to an individual this category alone never admitted.

**Reads and writes.** `Node.drawnLabels: [String!]!` (sorted); `Node.label` is
the first of them. `Entity`/`NaturalEvent`/`ProtocolEvent` lose `categoryId` and
`category` for `categoryIds` and `categories` (ordered as the ids), and
`richProperties` is the union, each key explained by the first category
declaring it. A write's `drawings` lists a node **once per category** it is
drawn under — `NodeDrawing` stays one per (view, category), which is what the
field always promised — and `drawings_for_instance` checks the vertex's
`category_ids` against the rule's answer, logging when the projection is
behind. `refs_admitted_by(category)` counts a node in every category it holds.
Edges are still drawn under one label: a relation or participation claim names
one word, and `categories_by_term` resolves that word to the one category
declaring it.

### A rebuild refolds `State` before the replay

Found by the property-union test. `rebuild` refolded the organization's
`State` vectors *after* `project_all`, so a rebuild derived every unconstrained
property from the cache it was about to rebuild — a metric whose `merge` never
ran was missing from the drawing until the *next* rebuild. The refold now sits
with the other three caches (`CategoryAssertedTerm`, `InstanceIdentity`,
`CurrentStanding`), before the drop, which is what the docstring already
claimed.

## Tests

`tests/api/test_different_from.py`: a difference vetoes the direct sameness in
the view fold and the organization cache, and asserted first prevents the
merge; a conflict through a third instance stays merged and is reported under
`conflicts`; retracting the difference restores the union; a difference the
category does not trust is ignored; two distinct instances are required;
`rebuild_identity --check` agrees under the veto.

`tests/projector/test_several_categories.py`: a node two categories admit is
drawn once under both, listed under each category and in each namespace view,
and its write reports one drawing per category with `drawnLabels`,
`categoryIds` and `categories`; properties are the union; a key defined
differently by two categories is refused with a reason naming both, and
identically-defined is not; existence folds per category (retracted by one
trusted claimant, the node keeps the other category's label, then none);
deleting one of a vertex's categories keeps the vertex under the other.
`tests/projector/test_category_fk.py` pins the relocated composite FK and the
last-label trigger; `test_defined_categories.py`'s "matching two definitions"
case asserts the union where it asserted a refusal; `test_projector_protocol.py`
fences `ProjectionLabel` into `table.py`. `tests/drawing.py` gains `labels_of`.
