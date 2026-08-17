# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Kraph is the knowledge-graph service of the Arkitekt framework: a Django + Strawberry GraphQL
server on top of PostgreSQL with the **Apache AGE** (Cypher) extension.

## Commands

Dependency management is `uv` (see `uv.lock`); everything runs through `uv run`.

```bash
uv sync --all-extras --dev          # install (what CI does)

uv run pytest                       # full suite
uv run pytest tests/test_materialize.py::test_name   # single test
uv run pytest --cov --cov-branch    # coverage (CI: coverage.yaml)

uv run ruff check .                 # lint      (CI: advisory, continue-on-error)
uv run ruff format --check .        # format    (CI: advisory)
uv run basedpyright                 # typecheck (CI: advisory)

python manage.py validate_settings  # load+validate config, print it with secrets redacted
```

Notes:
- Ruff is not declared in `[dependency-groups] dev` — it resolves transitively today. If it ever
  disappears, use `uvx ruff`.
- **basedpyright is the only type checker.** `[tool.mypy]` used to sit in `pyproject.toml` set to
  `strict = true` with no CI job running it — a standard nothing checked — and is gone along with
  the `mypy` dev dependency. basedpyright runs unscoped over the whole repo, advisory.
- Serving: `run.sh` (daphne on :80, production) / `run-debug.sh` (`runserver` on :80). Both
  `wait_for_database` → `migrate` first, under `set -euo pipefail`. They used to call `ensureadmin`
  too — a command that is not installed — and without `set -e` that errored on every boot and
  carried on serving.

### Tests need Docker — always

`tests/conftest.py::backend_stack` is session-scoped and uses `dokker` to `down()` then `up()`
`tests/integration/docker-compose.yaml` (Postgres+AGE on **5555**, redis on **6666**, seaweedfs on
**18888**). Those ports must be free. `kraph_server/settings_test.py` hardcodes
`localhost:5555 / test / test`, so that compose file is the only supported test database — even a
single test pays the full stack bring-up. Settings module is wired in `pyproject.toml`, so plain
`uv run pytest` is correct.

**AGE graphs are deliberately not dropped between tests** (see the `age_engine` fixture comment:
dropping invalidates the AGE type cache). Graph state leaks across a session — a test that passes
alone but fails in the suite is usually this, not your change.

### Local `manage.py` gotcha

The checked-in `config.yaml` targets container hostnames (`db`, `redis`, `minio`,
`seaweed-filer`) because this checkout is a deployment mount. To run `manage.py` from the host,
point `ARKITEKT_CONFIG_FILE` at a config with host-reachable values. Config precedence and every
key are documented in [`CONFIG.md`](CONFIG.md); the schema itself is
`kraph_server/configuration.py` (pydantic-settings, `__` env-var nesting, missing secrets fail
startup hard).

## Architecture

Full write-up: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — note its header still says
"design proposal"; most of it has since been built. What the append-only log actually records,
and which operation writes which claim: [`docs/LOG.md`](docs/LOG.md). Domain rationale for the
evidence/provenance model: [`docs/BIOLOGIST.md`](docs/BIOLOGIST.md). When a category's
properties change and every vertex it draws goes stale — what redraws them, in-request versus
`manage.py rematerialize`: [`docs/REMATERIALIZATION.md`](docs/REMATERIALIZATION.md).

Design questions live in [`docs/rfcs/`](docs/rfcs/README.md). Check the **status line** before
acting on one. While it is open, the RFC proposes no code change and a defect it names is
deliberately left in the code, because it is the subject being decided — don't "fix" one as
drive-by work. A status of **Implemented** means the opposite: it shipped, its findings are
fixed, and the text is the record of why. RFC 0003 is implemented.

### The vocabulary

One word per concept. Each of the first three used to carry two or more meanings, and the renames
that fixed that are in `evidence/migrations/0008_instance_and_standing.py`.

| Word | Means | Lives in |
|---|---|---|
| `Assertion` | the **act** — who claimed it, with what tool, when. Carries `seq`, the log's total order | `evidence.Assertion` |
| *claim* | any **recorded statement**: an `Instance`, a `Link`, a `Metric`, a `Structure`. A prose word, not a table | — |
| `Instance` | a claimed **individual** — `entity`, `natural_event` or `protocol_event`. Every observation mints its own | `evidence.Instance` |
| `Standing` | somebody's **position** on whether a claim still holds (`stands=True/False`) | `evidence.Standing` |
| `CurrentStanding` | the folded answer, a cache. No row for instances — their standing is per view | `evidence.CurrentStanding` |
| `Term` | a **word** the organization uses. What a claim names | `evidence.Term` |
| `Category` | one **view's rule** for a word: `age_name`, `definition`, layout | `core.Category` |
| `Graph` | a **view** over the organization's claims, with a selector saying which ones count | `core.Graph` |
| `Node` / `Edge` | what a **graph** has — the API-facing drawing shape. `Node` = `Entity`, `NaturalEvent`, `ProtocolEvent` — exactly `Instance.Kind`. GraphQL `Structure` and `Metric` are claim shapes and implement neither interface: no view ever draws one | GraphQL only |
| `Entity` | an instance that is **not an event** | `Instance.Kind.ENTITY`, GraphQL `Entity` |
| drawing | how one view **draws** a claim: a vertex or an edge, and the category it drew it under | `graph_engine.results.NodeDrawing` / `EdgeDrawing` |
| `Asserted*` | what a **write returns**: the assertion it made, the claim, and the drawings | GraphQL `AssertedEntity`, `AssertedNodes`, … |
| `Standing` (GraphQL) | one position on a claim: `stands`, when, and whose | `api/types.py::Standing` |

Three consequences worth stating, because each was a bug before the words were separated:

- **`Node` is graph-facing only.** `evidence.Instance` is narrower (no structures, no metrics) and
  an AGE vertex is narrower still. A `RetrievedNode` spans all of it, so its vertex-only fields are
  named for what they are: `vertex_id` (reassigned by every reproject — `unique_id` is the identity)
  and, on edges, `edge_id`.
- **"Entity" never means "any node".** It used to, in ~108 identifiers — `project(entity_refs=…)`,
  `RetrievedEntity`, `selector.entity_refs_informed_by`. Those are `instance_refs`, `RetrievedNode`
  and `instance_refs_informed_by` now.
- **A `Standing` is not a claim, and `retractLinks` takes `Link` ids.** It was `retractClaims`,
  which named neither the table it reads nor the one a retraction writes.

The load-bearing facts:

- **Two layers.** Django rows in `core/models.py` ending in `*Category` are the *schema/ontology*
  (what node and edge kinds a `Graph` allows). Instance data is **also** Django rows now — the
  `evidence` app is the source of truth, and Apache AGE holds a droppable projection of it. (This
  used to say instance data is never a Django row; that inverted when the evidence base landed.)
- **The log names a word, not a category.** `Category` is graph-native — created from the schema
  definition, holding `age_name`, `definition`, derivation rules and layout — and stays so. But
  `Instance.term` and `Link.term` point at organization-scoped `evidence.Term`, so a `CLASSIFIES` claim
  can be read by every view declaring the same word. `Category.term` is the join. Deleting a
  category or a graph is therefore free and takes no evidence with it; the `PROTECT` is on `Term`.
- **So does the write API.** Instance mutations take `term: "AIS"` — a `Term.key`, resolved against
  the request's organization — and no graph, no category id. Authorization is
  `context.assert_can_access_organization`. `graph` remains on *reads* (`nodes(graph:)`) and on
  schema mutations (`createEntityCategory(graph:)`), because a read is view-scoped and a category
  belongs to one view. `createGraph` and the category-creation mutations take `backfill` to project
  the history a newly declared word already admits.
- **And so does the read API, now.** Every id in the schema is a **bare uuid** — `Node.id` and
  `Edge.id` and nothing else. `graphId`, `globalId`, `localId`, `Node.graph`, `Node.pinned` and the
  `GlobalID`/`LocalID`/`StructureGlobalID` scalars are gone: each named an Apache AGE vertex that a
  reproject reassigns, a graph a node may not belong to singly, or (for `globalId`) a vertex
  property nothing has ever written, so it *raised*. The composite `{graph}:{vertex_id}` parsers
  went with them. **Edge list queries read `evidence.Link`**, not Cypher
  (`api/queries/_edges.py`) — five of the six matched labels the projector never writes and could
  only return empty, and all six handed out ids their own singular fetchers could not accept.
  **Node list queries read `evidence.Instance`** the same way (`api/queries/_nodes.py`), and membership
  comes from `projector.refs_admitted_by` / `refs_in_graph`, which route through
  `resolve_categories` — the view's *rule*, not the state of its cache, so a node a category admits
  is listed whether or not the projection has caught up. The drawing supplies the derived properties
  where there is one, and `has_property`/`search`/`matches` and property ordering are **refused**
  rather than silently narrowing a claim list by what happens to be cached; the drawing-scoped
  query with the indexed-key guard is `GraphController.list_entities_for_category`, which no
  GraphQL field is built on. **The singular node fetchers name their view too**:
  `node(id:, graph:)` and the typed forms go through `api/queries/_nodes.py::one_in_graph`, the
  same membership-then-drawing path as `nodes(graph:)`, so the singular and plural reads are
  answer-equivalent — admitted-but-undrawn returns `RetrievedNode.from_row` (the shape a write
  returns before anything is drawn, `schemaVersion` null), and a node the view does not admit is
  refused, with `instance(id:)` as the claim-grain reader. They used to take no graph and answer
  from `drawings[0]`, an arbitrary view (`projected_instance`, deleted with its caller
  `get_node`). Anything that reads a vertex pattern should be checked against
  `projector.create_vertex`, which writes exactly `{id, category_id, type}` and labels with
  `category.age_name`.
- **What a node *is* comes from the claim, never from the label.** `Instance.kind` is the fact;
  `create_vertex` writes it onto the vertex as `type`, and `RetrievedNode.node_type` reads that and
  nothing else. There is no label-to-kind map any more — a vertex is labelled `category.age_name`
  ("Cell", "Mitosis"), which is one view's rename of a word, so `VocabNodeTypeMap` matched none of
  its five fixed words and defaulted every drawn node to `"ENTITY"`: `node(id:)` and every write's
  `drawings { node }` reported a protocol event as an `Entity`. A vertex with no `type` is one an
  older projector drew — `manage.py reproject`, not a fallback guess.
- **A write is named for the act and returns where the claim landed.** `assertEntityExists`, not
  `createEntity`; `retract*`, not `archive*`. Each returns the `Assertion` it recorded, the claim,
  and **`drawings`** — every view that draws that claim afterwards, empty when none does. So "no
  view declares this word" is a count rather than a null, and a claim several views draw reports all
  of them instead of the lowest-id one. There is no `lifecycle` field anywhere — a node in a graph
  is one the evidence says exists, so a flag beside it could only agree with its own presence. See
  `graph_engine/results.py`.
- **The claim a write returns is an `Instance` or a `Link`, never an `Entity` or a `Relation`.**
  Those are *drawing* types — label, category, derived properties, schema version — and a write's
  result may be drawn nowhere, which is the ordinary outcome of naming a word no view declares. Two
  of `Entity`'s fields could not answer for that case: `schemaVersion` was `String!` over a value
  only a projection supplies, and `richProperties` opened with `assert category_id is not None`.
  Both are fixed (nullable, and `[]`) because `entity(id:)` can now reach them too. So the payload
  carries no category and no label: a claim names a **word** (`term`), and what a view makes of that
  word lives in its drawing. **There is no folded `stands` on either**: whether an instance exists
  has no organization-wide answer — `CurrentStanding` deliberately holds no row for one, because a
  graph's selector decides whose claims it counts — so the positions are reported as
  `standings` (newest first, empty meaning nobody disputed it) and the per-view answer is
  `drawings`. `Instance` and `Link` are also
  readable by id (`instance(id:)`, `link(id:)`), and `Link.source`/`target` resolve through the
  `ClaimEndpoint` union by dispatching on `kind` — never by inspecting a ref, since every ref is a
  bare uuid addressing one of four tables (`api/types.py::_ENDPOINT_TABLES`).
- **All graph writes go through `GraphController`** (`graph_engine/controller.py`), which records
  an `Assertion` — a Postgres row, not an AGE vertex — and projects into Cypher. Corrections are
  additive: there is no `updateEntity` and no hard delete for instance data. Evidence is written
  **before** the projection, always; the reverse ordering left vertices the log had never heard of.
- **The graph carries no lifecycle state**, and neither does the API. If the claims do not say a
  node exists, it has no vertex — not a vertex with a flag, and not a `lifecycle` field either. Retracting is a `Standing(stands=False)` and removes the drawing
  (`projector.unproject`, `DETACH`); `attest*` writes `Standing(stands=True)` and redraws it. There is
  no "unarchive": existence is evidence, and two people may disagree about it, with each graph's
  selector deciding whose word it counts.
- **Identity is a bare uuid.** `Node.id` *is* the identity — no `{age_name}:` prefix, and never the
  Apache AGE vertex id, which is reassigned by every reproject. GraphQL node ids are that uuid.
  Graph membership is decided in exactly two functions, `evidence.selector.instances_for` and
  `graph_ids_for_instance_ids` — and the two agree: both count the words a graph's categories declare
  **and** the words their definitions derive from. Since writes name terms, the second one is the
  only thing deciding where a write lands, so a write path that fans out over graphs goes through
  `projector.graphs_for_refs` and never `_graph_for_ref`, which returns an arbitrary declarer.
  The derived half of that rule — the words a `definition.asserted_as` names, which is a string
  inside JSON and so un-joinable — is normalized into `core.CategoryAssertedTerm`, maintained by a
  signal in `versioning.connect()` that deliberately does **not** share `is_suspended()`
  (`materialize` runs suspended, and that is when the index matters most). It stores the **key**,
  not a `Term` FK: a definition routinely names a word nobody has minted yet. Rebuild and verify
  with `manage.py rebuild_asserted_terms [--check]`.
- **Every observation mints its own instance, and sameness is a claim.** "This is an AIS" writes a
  *fresh* `Instance`; "this is AIS 6" additionally writes `Link.Kind.SAME_AS`, under the **same**
  assertion, because it is one act. `evidence/identity.py` folds those claims into components
  (`InstanceIdentity`, organization grain, lowest uuid as representative, only merged nodes get a row).
  Retraction cannot un-union, so it flags and `recompute` rebuilds; `manage.py rebuild_identity
  --check` is the backstop. Everything the panel reports — `evidence/panel.py`, surfaced as
  `Entity.labels/sameAs/connections/component` and `Structure.metrics/informs` — is unioned over the
  **component**, never over one instance. The projection still draws one vertex per `Instance`; see
  `docs/LOG.md`.
- **`State` is organization grain**, and nothing folds under a selector — `merge`, `recompute` and
  `refold_state` all count every live metric. Which of them a *view* counts is applied on read in
  `projector._scoped_state`. The three used to disagree, so ingest and replay produced different
  numbers from the same evidence.
- **The engine seam** is `graph_engine/engine/protocol.py::CypherEngine`; `age_engine.py` is the
  real driver, `engine/testing/mock_cypher_engine.py` the double. New graph code should depend on
  the protocol, not on `AgeEngine`.
- `graph_engine/materialize.py` is the bridge schema → Django categories + AGE graph (hashed for
  versioning); `rollup.py` generates the Cypher for derived/aggregated entity properties;
  `insights/` renders saved queries as Jinja-templated Cypher.
- **GraphQL** (`api/`) is Strawberry wrapped by in-house **kante**. Auth is a *Strawberry schema
  extension* (`authentikate.strawberry.extension`), not Django middleware, and
  `api/extensions/cypher.py::CypherEngineExtension` binds the engine per-operation through a
  `ContextVar`. Serving is the kante router in `asgi.py` (`/graphql` + SDL at `/schema`);
  `urls.py` only carries `admin/` and the `/ht` health check.
- `datalayer/` is the S3/object-store abstraction (presigned upload grants). `rekuest_core/` — a
  vendored Arkitekt port/widget type system — is gone: nothing imported it and it was in no
  `INSTALLED_APPS`, so the only thing keeping it alive was a test that smoke-imported every package.

### Repo hygiene

- **Exclude `core-backup-do-not-delete/` from every search** — it is a legacy snapshot of `core/`
  and will double every grep hit.
- `test.graphql` at the repo root is a hand-dumped SDL snapshot, **not** asserted by any test.
  `tests/test_print_schema.py` checks the schema builds *and* that every member of `NodeSubtype` /
  `EdgeSubtype` is registered — a type the cast can produce but `create_schema(types=[...])` does
  not list fails at **runtime** ("Abstract type 'Edge' was resolved to a type that does not exist
  inside the schema"), never at build. Regenerate the snapshot after a schema change and read the
  diff; it is the only artifact that shows a breaking change whole.
- Releases are `python-semantic-release` off conventional commits: `main` → stable, `next` →
  `-rc.N` prereleases, `N.x` → maintenance. Commit messages drive version bumps, so use
  `feat:`/`fix:`/`chore:` deliberately.
