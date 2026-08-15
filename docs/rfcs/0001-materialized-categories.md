# RFC 0001 — Can materialized categories go away?

- **Status:** Open question. **Proposes no code change.** Nothing in this file
  has been implemented; it exists to record the analysis and a recommendation.
- **Recommendation:** No, not as posed — but the row should get smaller, and one
  of the two things this repo calls "materialized" is a genuinely separable
  target.

## Which "materialized" this is about

The word is overloaded here, and the two senses have different answers:

1. **`Category` rows materialized from a schema definition** by
   `graph_engine/materialize.py`. `materialize()` turns a `GraphDefinitionInput`
   into `EntityCategory`, `RelationCategory`, `NaturalEventCategory`… rows plus a
   `GraphSchema`, and creates the AGE namespace.
2. **`MaterializedView` / `MaterializedEdge` and its three proxies**
   (`MaterializedRelationEdge`, `MaterializedMeasurementEdge`,
   `MaterializedStructureRelationEdge`) — precomputed cross-products of category
   pairs, written by `re_materialize_*_category`.

This RFC is primarily about **(1)**, which is what "contrast them with the
definition and the term" points at. §6 covers (2), which is the easier win.

## The question

A `Category` sits between two things that already carry meaning:

- **`evidence.Term`** — the organization's word, `(organization, kind, key)`.
  What a claim names. Shared by every view.
- **the definition** — either `GraphSchema.definition` (the whole ontology as
  JSON) or `Category.definition` (this view's predicate over claims).

If the word is in `Term` and the meaning is in a definition, what is the row for?

## 1. What a Category row actually holds

Taking the fields as they stand, grouped by whether anything else could supply
them:

| group | fields | supplied elsewhere? |
|---|---|---|
| the join | `term` | **no** — this *is* the mapping from word to view |
| the projection | `age_name`, `kind` | **no** — AGE needs a label, and `labels(e)[0]` is read everywhere |
| the rule | `definition`, `property_definitions`, `schema_hash` | in `GraphSchema.definition`, but see §3 |
| decoration | `label`, `description`, `purl`, `color`, `image` | **yes — duplicated on `Term`** |
| layout | `position_x/y`, `width`, `height`, `ports`, `pinned_by`, `sequence` | no |
| identity | `key`, `graph`, `pk` | `key` is on `Term`; `pk` is held by clients |

Two observations fall straight out. The join and the AGE label are irreducible.
The decoration is **duplicated against `Term`**, which already carries `label`,
`description`, `purl`, `color` and `image` for the same word.

## 2. The term cannot absorb it

`Term`'s own docstring settles this: the split is *"which half the log may
name"*. A `Category` holds `age_name`, `definition`, `property_definitions` and
layout, all of which are meaningless outside the graph that owns them. Folding
them into `Term` would re-bind a claim to one view, which is the exact failure
the evidence base was built to remove — one annotator's classification not being
visible to a second.

So the term is not a replacement. It is the *other half*, and it already has its
half.

## 3. The definition cannot absorb it either — and this is the load-bearing fact

The intuition is that `GraphSchema.definition` is the source and the categories
are a cache of it. **That is backwards.**

`graph_engine/versioning.py::snapshot_definition` reconstructs the definition
*from the categories*:

> "The inverse of `materialize()`: where that turns a definition into rows, this
> reads the rows back into a definition. Going through the categories rather than
> through the previous schema is deliberate — the categories are what the
> mutations edit, so they are what a new version has to reflect."

Every `create_*_category` / `update_*_category` mutation edits a row and then
emits a new `GraphSchema` from the resulting rows. The definition is **downstream
of the categories**, not upstream. Deleting the rows in favour of the definition
would mean either giving up per-category mutations, or teaching every mutation to
patch a JSON blob and rewrite the schema — trading a `UPDATE ... WHERE pk` for a
read-modify-write of the whole ontology on every colour change.

`snapshot_definition` also does not round-trip cleanly today: it emits `entities`,
`relations` and `events` only, so measurement, structure-relation and reagent
categories are absent from the snapshot. Making the definition authoritative
would first require closing that gap.

## 4. What would break if the rows were removed

Concretely, from the current code:

- **`projector.resolve_categories`** builds `{term_id -> category}` from
  `Category.objects.filter(graph=graph)`. Without rows, this becomes a JSON scan
  per projection, and it runs on every rebuild over every node.
- **`evidence.selector.term_ids_for`** reads `(term_id, definition)` pairs off the
  same table to decide a graph's whole visible vocabulary — one of the two
  functions CLAUDE.md names as deciding graph membership.
- **`controller._category_for_term`** answers "how does some view draw this
  word", ordered by pk so two identical writes agree. There is no pk to order by
  without rows.
- **GraphQL identity.** `Category` is an exposed type with a database id, and
  clients hold those ids. `MaterializedEdge`, `OntologyReference`, `GraphQuery`
  and `GraphSequence` all carry FKs to it.
- **AGE labels.** Every Cypher template interpolates `category.age_name`
  (`MATCH (e:{category.age_name})`). Something has to own the label→word mapping,
  and it has to be indexable.

None of these are unfixable. Together they say the row is not redundant
bookkeeping — it is the graph's index over its own vocabulary.

## 5. What *should* change

Two narrowings, neither of which needs the row to disappear:

**(a) Stop duplicating the term's decoration.** `label`, `description`, `purl`,
`color` and `image` exist on both `Category` and `Term`, with no rule saying which
wins. Today `from_row` reads `category.age_name` for a label while
`api/types.Category.label` reads the category's own — so the same node can print
two different names depending on which path produced it. Either the category's
copies become *overrides* (null means "use the term's") or they go. This is a
real bug surface, not tidiness.

**(b) Rename the concept.** The row is not a materialization of anything — it is
a **declaration**: this view declares this word, draws it under this label, means
this by it, and puts it here on the canvas. "Materialized" invites exactly the
"it's a cache, delete it" reading this RFC had to spend §3 refuting.

## 6. The other "materialized": the edge tables

`MaterializedRelationEdge` and friends *are* caches, and they fit the usual test
for one much better:

- they are a pure function of `source_definition` × `target_definition` over the
  graph's categories (`re_materialize_relation_category` deletes and re-creates
  the cross-product);
- `controller.create_relation`'s docstring already says they are "a schema-level
  expansion for the read surface, not a write-time guard" — nothing on the write
  path consults them;
- their input just got narrower: with category tags removed, the descriptors
  filter on `keys` and `ontotology_terms` only.

A follow-up RFC could ask whether these should be computed on read instead of
stored. That question is genuinely open in a way §1–§5's is not.

## Recommendation

1. **Keep the rows.** The definition is derived from them, not the reverse.
2. **Resolve the decoration duplication** between `Category` and `Term` — pick a
   direction and make null mean "inherit".
3. **Stop calling them materialized.** They are declarations.
4. **Open a separate RFC on the `Materialized*Edge` tables**, where the
   delete-the-cache argument actually holds.

## See also

- [RFC 0002](0002-term-structurekind-metrickind.md) — whether `Term`,
  `StructureKind` and `MetricKind` are one thing.
- [RFC 0003](0003-undrawn-nodes.md) — its rejected option E would require a
  category per term, which is the opposite of §5's direction.
