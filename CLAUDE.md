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
- Both `[tool.mypy]` (strict, django plugin) and basedpyright are configured, but **only
  basedpyright runs in CI**, and unscoped (the `typecheck.yaml` comment claiming a
  `[tool.basedpyright]` scope in `pyproject.toml` is stale — no such section exists).
- Serving: `run.sh` (daphne on :80, production) / `run-debug.sh` (`runserver` on :80). Both
  `wait_for_database` → `migrate` → `ensureadmin` first. **`ensureadmin` is not installed** in the
  current dependency set; the scripts have no `set -e`, so that step just errors and continues.

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

Full write-up: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (currently **untracked** — worth
committing). Domain rationale for the evidence/provenance model:
[`docs/BIOLOGIST.md`](docs/BIOLOGIST.md).

The load-bearing facts:

- **Two layers.** Django rows in `core/models.py` ending in `*Category` are the *schema/ontology*
  (what node and edge kinds a `Graph` allows). The actual vertices and edges — a specific cell, a
  specific measurement — live in **Apache AGE** and are only reachable via generated Cypher.
  Instance data is never a Django row; don't reach for the ORM to find it.
- **All graph writes go through `GraphController`** (`graph_engine/controller.py`, 2.5k lines),
  which turns domain operations into Cypher and weaves in `Assertion` provenance nodes.
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
- `datalayer/` is the S3/object-store abstraction (presigned upload grants); `rekuest_core/` is a
  vendored Arkitekt port/widget type system for interop, not a live RPC engine.

### Repo hygiene

- **Exclude `core-backup-do-not-delete/` from every search** — it is a legacy snapshot of `core/`
  and will double every grep hit.
- `test.graphql` at the repo root is a hand-dumped SDL snapshot, **not** asserted by any test
  (`tests/test_print_schema.py` only checks the schema builds). Treat it as documentation that may
  be stale.
- Releases are `python-semantic-release` off conventional commits: `main` → stable, `next` →
  `-rc.N` prereleases, `N.x` → maintenance. Commit messages drive version bumps, so use
  `feat:`/`fix:`/`chore:` deliberately.
