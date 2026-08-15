# RFC 0002 — Are `Term`, `StructureKind` and `MetricKind` the same thing?

- **Status:** Open question. **Proposes no code change.** Nothing here has been
  implemented.
- **Recommendation:** They are the same *pattern*, not the same *thing*. Don't
  merge the tables; do extract the shared half, and fix one inconsistency found
  along the way.

## Why the question is fair

Put the three side by side and they are hard to tell apart. All of them:

- are **organization-scoped** — `organization` FK, `CASCADE`, and nothing else;
- have a **uuid primary key**, `created_at`, and no provenance fields;
- carry the **same decoration**: `label`, `description`, `purl`, `color`, and
  (except `MetricKind`) `image`, all nullable;
- use the **same manager pair** — `objects = OrganizationScopedManager()`,
  `all_objects = models.Manager()`, with `base_manager_name` and
  `default_manager_name` both set to `all_objects`;
- are **minted lazily** by `evidence.writer.ensure_*`, with the same stated
  reason in all three docstrings: refusing to record a fact because nobody had
  declared the word would be refusing it on a bookkeeping technicality;
- are **`PROTECT`ed** from the evidence rows that name them — a word that has
  been used cannot be deleted, only retired.

`Term` even says so out loud: *"Everything else is decoration and nullable,
exactly as on `StructureKind` — which is the same idea for external data."*

That is a lot of identical surface. The question is whether the differences are
incidental.

## What actually separates them

### Identity arity — and dependence

| | identity | dependent? |
|---|---|---|
| `Term` | `(organization, kind, key)` | no |
| `StructureKind` | `(organization, identifier)` | no |
| `MetricKind` | `(organization, structure_kind, key, value_kind)` | **yes** — FK to `StructureKind` |

`MetricKind` is not a sibling of the other two. It is a word **scoped to another
word**: `vector_length` means nothing until you say *of what*, and its own
docstring is explicit that `vector_length` on an ROI and on a Mask are separate
quantities. A single table would have to make that parent FK nullable and then
enforce "non-null exactly when kind = METRIC" out of band.

`value_kind` compounds it. It is in `MetricKind`'s identity because a
disagreement about *what type a thing is* is a disagreement about what is being
measured — one tool recording `confidence` as a float and another as a label are
measuring two different quantities. Nothing analogous exists for the other two.

### Who owns the word

`StructureKind.identifier` is **`@mikro/roi` — owned by another service**. Its
docstring makes the point that N per-graph copies of it was duplication with no
meaning, and `ensure_structure_kind` adds that "there is nothing here for us to
approve".

`Term.key` is the organization's own word. It has a `kind` in identity precisely
because *we* decide that "AIS" as an entity and "AIS" as a relation are two
words, and that `kind` mirrors `core.enums.CategoryKindChoices` — a local
enumeration. One namespace is foreign and opaque; the other is ours and
structured.

### The structural answer: they are the vocabularies of different claim targets

`evidence/models.py` declares `CLAIM_TARGETS = ("structure", "metric", "link",
"node")`. Line them up:

| claim target | its vocabulary |
|---|---|
| `node` | `Term` |
| `link` | `Term` |
| `structure` | `StructureKind` |
| `metric` | `MetricKind` |

The three tables are not three arbitrary spellings of one idea. They are **one
vocabulary table per shape of thing a claim can be about**, and the shapes differ
in exactly the ways the identities differ: a node or a link is named by a word; a
structure is named by a foreign identifier; a metric is named by a word, its
subject, and its type.

## The merge case, taken seriously

The strongest argument for merging is that **this repo has already made the
move**. `core.Category` used to be a multi-table-inheritance chain
(`Category → NodeCategory → EntityCategory`); it is now one concrete table with a
`kind` discriminator and proxies preserving the old class names. A
`Vocabulary(kind, key, parent, qualifier, …)` table would be the same shape.

Two reasons it buys much less here:

1. **There is no JOIN to remove.** Category's collapse eliminated a real cost —
   MTI meant a JOIN per level on every read. `Term`, `StructureKind` and
   `MetricKind` are three independent concrete tables today. Merging them removes
   nothing and adds a discriminator column plus a filter on every query.
2. **One table cannot express the three identities.** `UniqueConstraint` per kind
   would become three partial unique indexes over a shared column set, with
   `parent_id` and `value_kind` null for two of the three kinds and required for
   the third — enforced by a `CheckConstraint` if at all. The current schema says
   the same thing in a way the database can actually check.

There is also a migration cost paid by every `PROTECT`ed reference from
`Structure`, `Metric`, `Link` and `Node`, plus `core.Category.term` — for a
refactor with no read-path win.

## The inconsistency worth fixing regardless

`evidence/models.py`'s module docstring states:

> *"Every reference out of this app goes to the organization's own vocabulary —
> `Term`, `StructureKind`, `MetricKind` — and every one of those is `PROTECT`,
> never `CASCADE`. A word that has been used cannot be deleted; retire it
> instead."*

But `MetricKind.structure_kind` is **`on_delete=models.CASCADE`**. Deleting a
structure kind therefore silently deletes every metric kind under it — and those
metric kinds are `PROTECT`ed from their `Metric` rows, so the delete either fails
deep in a cascade or, if no metrics exist yet, quietly removes declared
vocabulary.

The docstring's rule is about references *into* vocabulary from evidence rows, so
this is arguably outside its letter. It is not outside its spirit: a metric kind
is a used word too. `PROTECT` here would say what the rest of the app says.

**This RFC proposes no change, including this one** — it is recorded so it can be
decided deliberately rather than discovered by a cascade.

## Recommendation

1. **Do not merge the tables.** They are the vocabularies of three different
   claim targets, with three genuinely different identities, and one of them is
   dependent on another.
2. **Extract the shared half** into an abstract base — organization, uuid pk,
   `label` / `description` / `purl` / `color` / `image`, `created_at`, the manager
   pair, `Meta.base_manager_name` / `default_manager_name`. Abstract models
   generate no table and no migration beyond a no-op state change, so this is
   nearly free and removes the three-way copy-paste that made the question look
   like a yes.
3. **Decide the `MetricKind.structure_kind` `CASCADE`** on its own merits.
4. If a fourth claim target ever appears, revisit (1) — the argument against
   merging is about the cost/benefit at three, not a principle.

## See also

- [RFC 0001](0001-materialized-categories.md) — `Category` carries a duplicate of
  `Term`'s decoration too; §5(a) there and item 2 here are the same cleanup seen
  from two directions.
