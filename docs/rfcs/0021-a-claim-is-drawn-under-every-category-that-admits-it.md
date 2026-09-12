# RFC 0021 — A claim is drawn under every category that admits it, edges included

**Status: Implemented** (2026-09-09).

## Question

RFC 0019 made a *node* carry the label of every category that admits it. An
*edge* was still resolved through `projector.categories_by_term`, a
`{term_id: category}` map built last-writer-wins over the view's categories.
Which category does a view have for a word — and what happens when it has two?

## What the code did

A view's categories are unique on `(graph, key)`, and a category's term is
minted from its key, so a *declared* word had exactly one category. Several
categories for one word arose only by **derivation**: two defined relation
categories whose clauses both name the word `touches`. For those the map picked
one candidate when there was one and, when there were two, logged a warning
and mapped the word to **nothing** — so a claim both categories admitted was
drawn under neither. `project_edges`, `project_participation`, the two
correction paths (`_reproject_proposition`, `_reproject_participation`),
`drawings_for_edge`, `drawn_edge` and the API's `links_in_graph` all read that
map; the correction paths additionally erased under a single category's label
while their own survivor loops iterated several.

Nodes had the same map at `resolve_categories` (`by_term`), but there it only
served primitive categories, and a primitive category is one per word by the
uniqueness above — so the node side was correct by accident of the constraint.

## Decision

**Admission, not a map.** Whether a category draws a claim is that category's
rule applied to the claim (RFC 0009): `projector._admitted_by(categories, base)`
is the one implementation, and `admitting_categories` answers
`link → every category admitting it`. Everything that used to consult the map
reads through it: `active_relation_links`, `active_participation_links`,
`project_edges`, `project_participation`, the correction paths, `drawn_edge`,
`drawings_for_edge`, and `api/queries/_edges.py::links_in_graph`.

- A relation claim is drawn **once per admitting relation category**, under
  that category's label — the edge-side twin of RFC 0019. `ProjectionEdge` is
  keyed `(source, target, label)`, so two categories mean two edges between
  the same vertices, each with its own `__assertion_count`.
- A participation claim's label is a constant of the event *kind*, so every
  admitting event category draws the same edge; the claims are grouped once
  per drawn edge and the first admitting category names it.
- A correction recomputes admission for **every** relation (or event) category
  of the view between the two individuals, erases the label of each category
  no claim holds up any more, and redraws the rest. It used to fold survivors
  by the retracted claim's word only, so a category deriving from two words
  lost its edge when the last claim in one word went while claims in the other
  still stood.
- `Category` gains `UniqueConstraint(graph, term)` (where `term` is not null):
  one category per *declared* word per view is the invariant the map silently
  assumed, and the database now states it. Several categories for one word
  arise only by derivation, which is exactly what admission resolves.

`categories_by_term` is deleted.

## What this does not decide

An edge still carries no label table of its own (`ProjectionLabel` is for
vertices). Two labels are two `ProjectionEdge` rows; a query matching either
label finds the edge, and `renderGraphTable` compiles per label as before.
