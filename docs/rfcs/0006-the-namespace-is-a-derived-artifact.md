# RFC 0006 — The namespace is a derived artifact: per-graph SQL/PGQ over the table projection

- **Status:** **Implemented.** A record, like 0004 and 0005: it exists so the
  next person knows what the per-graph namespace *is*, which two lines of RFC
  0005 it deliberately amends, and what would count as regressing it.
- **Question:** Apache AGE gave every graph a namespace — a Postgres schema of
  its own — and the schema-level answer to "what can end up in this graph?"
  left with it: after RFC 0005, membership was enforced entirely in Python
  (`resolve_categories`), the projection tables carried no constraint tying a
  vertex to its graph's declared categories, and there was no per-graph object
  anything could query. PostgreSQL 19's native SQL/PGQ (`CREATE PROPERTY
  GRAPH` / `GRAPH_TABLE`) can rebuild all of that over the same two tables.
  Should it, and as what?
- **Recommendation (taken):** Yes — as a **derived artifact**. One Postgres
  schema per graph, named by `Graph.age_name`, holding one view per node
  category, one view per (edge label × admitted endpoint pair), and one
  property graph (inner name `graph`), all generated wholesale from the
  graph's `Category` rows by `Projector.refresh_namespace`. Write-side, a
  composite FK makes the database itself refuse a vertex drawn under a
  category its graph does not declare. `render_table` compiles saved-query
  plans to `GRAPH_TABLE`, so the namespace is load-bearing and the suite
  exercises it on every render.

## What the namespace is

The namespace is to the schema what the drawing is to the evidence: **derived,
droppable, and rebuilt wholesale** — `refresh_namespace` is drop-and-recreate
from `core.Category` rows, a pure function computed by
`graph_engine/namespace.py::namespace_spec` and spelled as DDL by
`graph_engine/projection/table.py::compile_namespace_ddl`. That split is the
same what/how seam `projector.py`/`table.py` keep for the drawing. Because
Postgres DDL is transactional, the category-write signal
(`graph_engine/apps.py`) refreshes the namespace in the same transaction as the
category row — so there is **no second staleness ledger**: `Projection.schema_hash`
keeps meaning derived-*property* staleness and nothing else. Out-of-band repair
is `manage.py refresh_namespaces`, the same role `rebuild_asserted_terms` plays
for its cache; a GA change in SQL/PGQ syntax is a run of that command, never a
data migration.

Labels are per-category element tables over disjoint views, so `MATCH (a IS
"Cell")-[IS "PART_OF"]->(b IS "Cell")` dispatches on the view's own words —
what AGE's per-graph labels gave, now with the label set *visible in DDL*.
Every vertex element exposes one uniform property set (`__vid`, `__ref`,
`__label`, `__category_id`, `__kind`, `__props`) so an unlabelled variable
spans all labels.

Three deliberate shapes:

- **Endpoint pairs come from the schema.** Edge element tables are enumerated
  from the edge categories' `source_definition`/`target_definition` descriptors
  (an open descriptor expands over every entity-like category), and the four
  participation labels (`WENT_THROUGH`/`CAME_OUT_OF`,
  `SUBJECTED_IN`/`PRODUCED`) from the event categories' roles — encoded in the
  *drawn* direction, since the writer already flips outputs. Above
  `NAMESPACE_MAX_ELEMENT_TABLES` the spec refuses loudly, naming the open
  descriptors that exploded — never silent truncation.
- **Measurement and structure-relation categories appear nowhere.** Nothing
  draws them (a measurement's source is a structure, and structures stopped
  being vertices in M1), so a label for them would declare an element table
  empty by construction.
- **An edge drawn between endpoints outside the declared pairs is outside the
  property graph.** It still exists in the base tables — `list_drawn` and
  `drawn_edge` read everything drawn — but `GRAPH_TABLE` sees the schema's
  shape. That is the point: the namespace is an enforcement surface, not a
  mirror.

## The two amendments to RFC 0005

RFC 0005's regression list forbade "an FK from an evidence or core row into a
projection table, or the reverse beyond the existing `graph` key", and its
"Deliberately left" section said nothing may re-grow an *address* out of
`Graph.age_name`. Both lines are amended — knowingly, and narrowly:

1. **The composite FK.** `ProjectionVertex(graph_id, category_pk) →
   core_category(graph_id, id) ON DELETE CASCADE` (graph_engine migration
   `0005_vertex_category_fk`; Django cannot express a composite FK, so it is
   raw SQL behind a plain `BigIntegerField`). The forbidden direction was about
   two things, and this FK does neither: nothing holds **evidence** in place
   (`ref` stays a plain uuid; evidence is still referenced by nothing), and the
   projection stays **droppable** (the FK points outward; a deleted category
   cascades its drawings away, which is semantically right — the rule that drew
   them is gone, and `reproject` re-draws whatever a current category still
   admits). What it buys is the write-side guarantee Python alone could not
   give: the database refuses a vertex drawn under a category its graph does
   not declare, even from buggy code. The edge-endpoint FKs became DB-level
   `ON DELETE CASCADE` in the same migration, because a SQL-level vertex delete
   is below the ORM where only SQL can follow.
2. **`age_name` names the namespace.** Still random, still `editable=False`,
   still refused as a `graph:` argument — a name for *output* only. What
   changed is that the name now denotes something real again: the derived
   schema. The line that survives 0005 unamended is the one that matters:
   **nothing may accept it as input.**

## What would count as regressing this RFC

- Namespace DDL (`CREATE PROPERTY GRAPH`, `GRAPH_TABLE`, `CREATE SCHEMA`,
  `DROP SCHEMA`) outside `graph_engine/projection/table.py` — the fence test
  scans for exactly these.
- A second staleness ledger for the namespace, or a namespace refresh deferred
  out of the category write's transaction.
- `Graph.age_name` accepted as input anywhere.
- A `GRAPH_TABLE` read answering a *claim* question (membership, existence,
  standing) — the namespace draws the schema's shape of the drawing; the
  evidence stays the only truth.
- Labels reaching SQL as anything but the category row's own value, quoted
  whole (`_quote_ident`), after resolution against
  `namespace.declared_labels` — the one sanctioned non-parameter, because
  SQL/PGQ labels are identifiers and cannot be bound.
