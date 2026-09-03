# RFCs

Design questions written down before anything is built. **An RFC proposes no code
change while its status is open** — it states a recommendation and the evidence
behind it, so the decision can be made deliberately rather than discovered
halfway through an implementation. A finding recorded in an open RFC is
deliberately left unfixed in the code; fixing it is a separate, explicit act.

An RFC whose recommendation has since been built says **Implemented** in its
status line, and is kept as the record of why rather than as an open question.
Its findings *are* fixed, and its text describes what it replaced.

| # | Question | Recommendation |
|---|---|---|
| [0001](0001-materialized-categories.md) | Can "materialized categories" go away, given the definition and the term? | No — the definition is derived *from* the categories, not the reverse. Shrink the row instead, and rename the concept. **§6 implemented:** the separate `Materialized*Edge` tables are removed — that cache had no invalidation at all. |
| [0002](0002-term-structurekind-metrickind.md) | Are `Term`, `StructureKind` and `MetricKind` the same thing? | Same pattern, not the same thing — one vocabulary per claim target. Extract the shared half; don't merge the tables. |
| [0003](0003-undrawn-nodes.md) | Should a write return a `RetrievedNode` when no graph draws it? | **Implemented.** No — a write asserts existence and returns the assertion plus every view that draws the claim. |
| [0004](0004-the-graph-is-a-projection.md) | Where was the graph still not a projection, and what would a second projection kind need? | **Implemented.** Name the seam (`Projector`), keep the projection's standing in Postgres (outbox + derived cursor), make the saved-query contract a plan, make the view's handle random and internal. |
| [0005](0005-retire-the-cypher-projection.md) | What was Apache AGE still buying, given that every query the repo emits is a fixed-hop join? | **Implemented.** Nothing worth its costs. The table projection (`TableProjector` over `ProjectionVertex`/`ProjectionEdge`) is the projection; Cypher, the engine seam and agtype are deleted; the protocol, outbox and watermark stay exactly as 0004 built them. |
| [0006](0006-the-namespace-is-a-derived-artifact.md) | Can AGE's per-graph namespace — the schema-level answer to "what ends up in this graph?" — come back on PostgreSQL 19's native SQL/PGQ? | **Implemented.** Yes, as a derived artifact: one schema + property graph per graph, generated wholesale from the `Category` rows by `refresh_namespace`; a composite FK makes the database refuse a vertex drawn under an undeclared category; `render_table` compiles plans to `GRAPH_TABLE`. Amends two lines of 0005, knowingly. |
| [0007](0007-a-definition-is-a-union-of-clauses.md) | Can a view say "'Cell' means what Peter called Cell, and what Karl called StemCell after Dec 5"? | **Implemented.** A definition is a union of clauses (`any_of`), each binding its own words, annotators and time bounds; `since` joins `as_of` in all three claim filters; both predicates gained a structured GraphQL surface; retraction became symmetric with attestation (folded per view at write time). Link standing stayed organization-wide — until 0008. |
| [0008](0008-trust-is-view-scoped.md) | Should "whose claims count" mean the same thing for every contestable claim kind — relations, participations, evidence links, sameness? | **Implemented.** Yes: `claims.standing` takes the view's predicate, both the claim and its standing fold under the selector everywhere a view is in scope, sameness gets a read-time trusted-claims walk (`component_refs_for_view` — the org-grain cache stays), and three metric-path selector leaks are closed. Structures, comments, and the identity *cache* stay organization grain, deliberately. |
| [0009](0009-trust-is-the-categorys-rule.md) | Why have a graph-level selector at all, if what counts as evidence is a property of each category's definition? | **Implemented.** No selector: a category's clauses are the complete rule for its word (classification, existence, its edges, default metric scope); `rule.evidence` is each property's own metric rule; panel and sameness return to organization grain; `conflict_policy` and rule role/scope filters removed as dead. |
| [0010](0010-definitions-are-rule-lists.md) | What replaces the clause shape the user rejected ("more clear, with operators — like a rule system")? | **Implemented.** Explicit (field, operator, value) rules: `rules` = any, `when` = all, `unless` groups subtract; one condition vocabulary shared with `rule.evidence`; NOT_IN adds "everyone except…"; completely breaking, clause shape cleared by migration 0017. |
| [0011](0011-kind-what-a-claim-says.md) | Can rules distinguish existence from sameness (and the rest)? | **Implemented.** `KIND` as a condition field over CLASSIFICATION/EXISTENCE/SAMENESS/EVIDENCE/MEASUREMENT; a rule covers every kind its KIND conditions do not exclude; sameness returns view-scoped — rule-driven and **within a category, across words** (no cross-category merges); strict grants: an uncovered kind counts nothing. |
| [0012](0012-rules-on-every-claim-family.md) | Can structure relation, measurement and protocol event categories carry rules too? | **Implemented.** All five families take the same `definition`; the category-scoped claim lists apply it; protocol event rules govern their drawn participations. Structure relations and measurements stay undrawn — their rules govern the lists only. |
| [0013](0013-schema-changes-are-rbac.md) | Do the per-action graph rules earn their keep? | **Implemented.** No — removed. Changing a graph's definition is RBAC: owner, organization admin (`Membership.roles` contains "admin"), or superuser, enforced by `validate_definition_editable` through `schema_graph`/`schema_scoped` in every category mutation. Reads and instance writes stay organization-scoped. |

**These files keep the old vocabulary on purpose.** `Node` (the row) is `Instance`,
`Claim` is `Standing`, and the `*Assertion` write payloads are `Asserted*` — see the
vocabulary table in `CLAUDE.md` and `evidence/migrations/0008_instance_and_standing.py`.
An RFC is a record of a decision taken at a point in time, so rewriting its nouns
would make it a worse record; read it against the table.
