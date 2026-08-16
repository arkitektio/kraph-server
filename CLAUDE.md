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

The load-bearing facts:

- **Two layers.** Django rows in `core/models.py` ending in `*Category` are the *schema/ontology*
  (what node and edge kinds a `Graph` allows). Instance data is **also** Django rows now — the
  `evidence` app is the source of truth, and Apache AGE holds a droppable projection of it. (This
  used to say instance data is never a Django row; that inverted when the evidence base landed.)
- **The log names a word, not a category.** `Category` is graph-native — created from the schema
  definition, holding `age_name`, `definition`, derivation rules and layout — and stays so. But
  `Node.term` and `Link.term` point at organization-scoped `evidence.Term`, so a `CLASSIFIES` claim
  can be read by every view declaring the same word. `Category.term` is the join. Deleting a
  category or a graph is therefore free and takes no evidence with it; the `PROTECT` is on `Term`.
- **So does the write API.** Instance mutations take `term: "AIS"` — a `Term.key`, resolved against
  the request's organization — and no graph, no category id. Authorization is
  `context.assert_can_access_organization`. `graph` remains on *reads* (`nodes(graph:)`) and on
  schema mutations (`createEntityCategory(graph:)`), because a read is view-scoped and a category
  belongs to one view. `createGraph` and the category-creation mutations take `backfill` to project
  the history a newly declared word already admits.
- **A write is named for the act and returns where the claim landed.** `assertEntityExists`, not
  `createEntity`; `retract*`, not `archive*`. Each returns the `Assertion` it recorded, the thing
  claimed, and **`drawings`** — every view that draws that claim afterwards, empty when none does.
  So "no view declares this word" is a count rather than a null, and a claim several views draw
  reports all of them instead of the lowest-id one. The payload itself carries **no category**: a
  category is one view's rule for a word, so the only honest place for one is inside a drawing.
  There is no `lifecycle` field anywhere — a node in a graph is one the evidence says exists, so a
  flag beside it could only agree with its own presence. See `graph_engine/results.py`.
- **All graph writes go through `GraphController`** (`graph_engine/controller.py`), which records
  an `Assertion` — a Postgres row, not an AGE vertex — and projects into Cypher. Corrections are
  additive: there is no `updateEntity` and no hard delete for instance data. Evidence is written
  **before** the projection, always; the reverse ordering left vertices the log had never heard of.
- **The graph carries no lifecycle state**, and neither does the API. If the claims do not say a
  node exists, it has no vertex — not a vertex with a flag, and not a `lifecycle` field either. Retracting is a `Claim(stands=False)` and removes the drawing
  (`projector.unproject`, `DETACH`); `attest*` writes `Claim(stands=True)` and redraws it. There is
  no "unarchive": existence is evidence, and two people may disagree about it, with each graph's
  selector deciding whose word it counts.
- **Identity is a bare uuid.** `Node.id` *is* the identity — no `{age_name}:` prefix, and never the
  Apache AGE vertex id, which is reassigned by every reproject. GraphQL node ids are that uuid.
  Graph membership is decided in exactly two functions, `evidence.selector.nodes_for` and
  `graph_ids_for_node_ids` — and the two agree: both count the words a graph's categories declare
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
  *fresh* `Node`; "this is AIS 6" additionally writes `Link.Kind.SAME_AS`, under the **same**
  assertion, because it is one act. `evidence/identity.py` folds those claims into components
  (`NodeIdentity`, organization grain, lowest uuid as representative, only merged nodes get a row).
  Retraction cannot un-union, so it flags and `recompute` rebuilds; `manage.py rebuild_identity
  --check` is the backstop. Everything the panel reports — `evidence/panel.py`, surfaced as
  `Entity.labels/sameAs/connections/component` and `Structure.metrics/informs` — is unioned over the
  **component**, never over one node. The projection still draws one vertex per `Node`; see
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
- `test.graphql` at the repo root is a hand-dumped SDL snapshot, **not** asserted by any test
  (`tests/test_print_schema.py` only checks the schema builds). Treat it as documentation that may
  be stale.
- Releases are `python-semantic-release` off conventional commits: `main` → stable, `next` →
  `-rc.N` prereleases, `N.x` → maintenance. Commit messages drive version bumps, so use
  `feat:`/`fix:`/`chore:` deliberately.
