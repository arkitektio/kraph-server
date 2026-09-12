# RFC 0018 — A view draws one vertex per individual

- **Status:** Implemented.
- **Question:** Every observation mints its own `Instance`, and "this is the
  same one" is a `SAME_AS` claim folded by `evidence/identity.py`. The panel
  read the fold — `Entity.sameAs`, `component`, `labels` and `connections` all
  unioned over the component — but the projector still drew **one vertex per
  `Instance`**, so two observations claimed to be one cell appeared twice in
  every view and once in the panel, with the derived properties split between
  the two vertices and every edge landing on whichever member the caller
  happened to name. `docs/LOG.md` recorded it as the last open gap. Should a
  view draw the individual, and if so, which id is the vertex's?
- **What was done:** A view draws one vertex per **view-scoped component** —
  the closure of the standing `SAME_AS` claims the members' category trusts —
  and lists the members on it. The vertex's ref is the lowest member uuid, the
  rule the organization-grain cache already used, so it does not depend on
  arrival order. `Node.id` is that representative; `node(id: <any member>,
  graph:)` answers with the individual; `Node.members` lists what it stands
  for. Derived properties fold over every member, edges to any member land on
  the one vertex with `__assertion_count` summed, and a relation between two
  members of one individual is drawn as a self-edge, because that is what the
  claims say.

## Changes

### The drawing has a member table

`graph_engine.models.ProjectionMember(graph, vertex, ref)` holds one row per
instance a drawn vertex stands for, unique on `(graph, ref)` — *one vertex per
member per view*. `ProjectionVertex.ref` stays unique per graph and is itself a
member, so a vertex nobody merged has exactly one row: itself. Migration
`graph_engine/0007` creates the table and backfills that single row for every
existing vertex, so the drawing stays addressable until `manage.py reproject`
redraws the components from the claims; `0008` rewrites the `vertex` FK to
cascade in the database, for the reason migration 0005 gives for the edge FKs —
a category delete removes vertices at the SQL level, where Django's Python-side
cascade never runs, and without it the member rows block the delete.

The protocol changes shape accordingly. `draw_node(graph, ref, label,
category_id, kind, members)` upserts the vertex and replaces its member rows;
`erase_nodes(graph, refs)` erases every vertex holding *any* of the refs;
`drawn_nodes(graph, refs)` answers a **dict keyed by the ref asked for**,
several refs mapping to one record, and the record carries `members`.
`draw_edge`, `erase_edge` and `drawn_edge` resolve their endpoints through the
member table, so a caller may name any member. `table.py` stays the only module
that names `ProjectionMember`; `tests/projector/test_projector_protocol.py`
scans for it.

### Which sameness counts is the category's rule

Sameness was already view-scoped (RFC 0011): a `SAME_AS` claim counts in a view
when the rule of the category the endpoints resolve to covers `SAMENESS` and
admits the claim, and no component crosses a category. `identity.view_components
(graph, resolved)` is the batch form — one query for the standing `SAME_AS`
links among the resolved refs, the per-category trust fold, union-find under the
lower root, singletons included — and `project_all`/`rebuild` call it once over
everything they resolved rather than walking per hop. A member `resolve_categories`
skipped (an ambiguity, a category it does not satisfy) is reported as before and
**excluded** from its component: it is not drawn, so it cannot be a member, and
the closure does not pass through it.

The organization-grain cache (`InstanceIdentity`) is untouched. It answers the
no-view question and the panel; the drawing answers the view's.

### The individual is what properties and edges are about

`project` groups by the *drawn vertex* — `drawn_nodes` over the batch, one
write per representative — and folds each derived property over the member
list: `_structure_ids_informing` filters `target_ref__in=members`, the cached
path reads every member's `State` rows through `state.state_for_many` and
`combine`s them (the monoid finally composing across instances, not only across
value kinds), and `_scoped_state`, `_property_statistics` and
`_observation_window` widen the same way. A length measured on a ROI informing
either observation counts once, on the one vertex.

`project_edges` and `project_participation` canonicalise both endpoints through
`representatives_for` before grouping, so two relation claims to two members of
one individual are one drawn edge with `__assertion_count: 2`. A relation
between two members of the same individual becomes a self-edge. That was the
one open question — draw it, drop it, or refuse it — and the answer is draw:
the claim exists, the view holds both ends to be one thing, and a self-edge is
the honest picture. A reader who wants "connected to something else" filters on
`source != target`, which the evidence graph offers and a dropped edge could not.

### Redraw widens to the individual

`converge(controller, graph, refs)` is the one redraw implementation, and its
touched set widens per view before anything is erased: the members of every
vertex currently holding a touched ref (the drawing's account of what is about
to change), unioned with `component_refs_for_view(graph, touched)` (the claims'
account of what it should become). It erases that set, resolves it, draws its
components and projects them. `reproject_node(controller, graph, node)` is
`reproject_refs(controller, graph, refs)` now, and `_reproject_instances` calls
it once per graph with the whole ref set rather than once per node. The
invariant the old docstring stated — "reads nothing from a neighbour" — is
restated as *nothing outside the touched individuals moved*, which is what it
always meant.

Edge correction on retraction widens the same way: `_reproject_proposition` and
`_reproject_participation` look for surviving claims between the **members** of
both endpoints (`_members_drawn_as`), so retracting one of two claims that share
a drawn edge lowers its count instead of erasing it.

### Reads

- `Node.id` is the representative. Documented on the field: "the lowest of
  `members`, which may differ from the member id you asked for".
- `Node.members: [ID!]!`, from `RetrievedNode.members`; a row-backed reading
  (admitted, not yet drawn) reports itself as its one member.
- `nodes(graph:)` and `entities(category:)` list **one row per individual**:
  `projector.representatives_in_graph` / `representatives_admitted_by` reduce
  the instance-grain membership through `view_components`.
  `refs_in_graph`/`refs_admitted_by` keep answering at instance grain, because
  membership is a claim-grain question.
- `node(id:, graph:)` and the typed singular forms accept any member: `one_in_graph`
  checks the asked instance is admitted, then resolves it to the representative
  through `representative_in_graph` and answers with that row.
- `GraphController.drawn_instances` keys by the ref asked for, so two members
  map to one `RetrievedNode`; `RichProperty.supportingEvidence` explains a
  folded value over every member.
- `assert*` payloads report the individual's drawing: `assertEntityExists(sameAs:
  [a]) { drawings { node { id members } } }` returns the vertex the new
  observation joined, whose `id` is `a`'s when `a` is lower.

The panel's `component` (organization grain, RFC 0009's rollback) and the
view's `members` may disagree, deliberately: one is what the organization
folded, the other what this view trusts.

## Tests

`tests/projector/test_one_vertex_per_individual.py`: two observations merged
draw one vertex whose ref is the lower uuid and both members read back with the
same `Node.id`; `nodes(graph:)` lists one; relation claims to either member are
one drawn edge with `__assertion_count == 2`; a relation between the members is
a self-edge; measurements informing either member fold onto the one vertex,
on the cached path and under a rule-bound property; retracting the sameness
splits into two vertices with their own folds; a sameness the category does not
trust draws two; retracting a member's existence leaves the individual with the
other; `reproject_refs` twice converges; `reproject --incremental` folds a
merge the write path could not draw; the write payload reports the individual's
vertex and its members; a sameness claim a view ignores survives in the log.
`tests/drawing.py` gains `representative_of`, `members_of` and
`edge_properties_between`; `tests/claims.py` gains `same` and `retract_link`.
`tests/projector/test_category_fk.py` pins the member cascade;
`test_projector_protocol.py` the one-module fence.
