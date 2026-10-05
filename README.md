# kraph-server

The evidence graph of an [Arkitekt](https://arkitekt.live) hub: the graph that ties samples,
images and measurements together. It does not store answers ("this cell is an AIS"). It
stores who claimed what, when, through which app and on what evidence, and lets each graph
decide which of those claims it shows. It is registered as `live.arkitekt.kraph` and has a
python client, [`kraph`](https://github.com/jhnnsrs/kraph).

## How it works

Three layers, in the order data moves through them:

| Layer | What it is | Code |
| --- | --- | --- |
| **The log** | Every claim anyone records: this exists, these two are the same, this measured 45.2, this no longer exists. Claims are appended, never edited or deleted. The log is the source of truth. | `evidence/` |
| **The view** | A `Graph` and its categories. Each category has a rule that says which claims it admits. Nobody writes "into" a graph: a claim names a word, and a view can be declared over history it did not witness. | `core/` |
| **The projection** | Each view's drawing of the log, in ordinary Postgres tables with a SQL/PGQ property graph per view. It is a cache: it can be dropped and rebuilt from the log. | `graph_engine/` |

`api/` holds the GraphQL layer over all three.

## API

GraphQL is served at `/graphql` (HTTP and WebSocket), with the SDL at `/schema`. The SDL is
also committed as [`test.graphql`](test.graphql), and a test holds the two equal.

| Operations | What they do |
| --- | --- |
| `assert…Exists`, `assertSameInstance`, `assertDifferentInstance`, `assertParticipation`, `recordMetrics` | Record a claim. A write returns the act it recorded. |
| `retract…`, `supersede…`, `attest…` | Claims about claims: withdraw one, replace one, vouch for one. |
| `createGraph`, `create…Category`, `createTerm` | Declare a view and its rules. |
| `nodes`, `node`, `entities`, `structures`, `relations`, `metrics` | Read a view. |
| `assertions`, `changes`, `standings`, `instance`, `link` | Read the log. |
| `createGraphTableQuery`, `renderGraphTable`, `createScatterPlot` | Saved table queries over a view, and plots of them. |
| `assertionRecorded` (subscription) | Each claim as it is recorded. |

## Hub integration

Declared in [`kraph_server/contract.py`](kraph_server/contract.py):

- **Scopes**: `kraph_read`, `kraph_write`, `kraph_query`, `read`, `write`.
- **Roles**: `admin`, `user`, `editor`, `viewer`.
- **Needs**: tokens issued by lok, and the storage kinds `media`, `zarr` and `bigfile`.

It has no peers. Other services' objects are named in claims by their structure identifier
(`@mikro/roi`), not reached over the network.

## Running

The image is `jhnnsrs/kraph`. A deployment runs it as two processes:

```sh
python -m arkitekt_service migrate   # once per release: wait for the database, apply migrations
bash run.sh                          # web: serve on :80 (daphne); the image's default command
bash run-worker.sh                   # the convergence runner
```

Every write draws inside its own request. The runner is the backstop: it finishes any
drawing a request could not, every `KRAPH_REPROJECT_INTERVAL` seconds (default 30).
`run-debug.sh` migrates and serves with Django's autoreloading server, for development.

It needs **PostgreSQL 19** (for SQL/PGQ), Redis and an S3 object store.

## Configuration

The service reads `config.yaml`, or the file named by `ARKITEKT_CONFIG_FILE`; any value can
be overridden by an environment variable (`POSTGRES__HOST`). `python manage.py
validate_settings` prints the configuration as the service reads it, with secrets redacted.

See [CONFIG.md](CONFIG.md) for every value.

## Development

```sh
uv sync
uv run pytest                # everything, about 2½ minutes
uv run pytest tests/guards   # no database, seconds
```

The suite runs against a real stack, brought up by [dokker](https://github.com/jhnnsrs/dokker)
from `tests/integration/docker-compose.yaml`: Postgres 19, Redis and seaweedfs, on ports
Docker picks. It needs a running Docker daemon. The suite is laid out by the property of the
model each test holds; [tests/README.md](tests/README.md) is the map.

## Further reading

- [docs/BIOLOGIST.md](docs/BIOLOGIST.md): why an evidence graph, for the people who use one.
- [docs/EXAMPLE.md](docs/EXAMPLE.md): one lab's schema, and what it makes of the log.
- [docs/VOCABULARY.md](docs/VOCABULARY.md): one word per concept, sorted by layer.
- [docs/LOG.md](docs/LOG.md): what a claim can say. The current-state document.
- [docs/RULES.md](docs/RULES.md): how a category decides which evidence it shows.
- [docs/REMATERIALIZATION.md](docs/REMATERIALIZATION.md): when a vertex is redrawn, and by whom.
- [docs/rfcs/](docs/rfcs/README.md): the design decisions, each with its status.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): historical; the reasoning that led here.

## Releases

Releases are tags: a push to `main` cuts a stable version, a push to `next` a release
candidate. Each one publishes `jhnnsrs/kraph` under its version (`X.Y.Z`, `X.Y`, `X`), plus
`latest` from `main` and `next` from `next`. The `version` in `pyproject.toml` is a
placeholder. Release notes are on
[GitHub Releases](https://github.com/arkitektio/kraph-server/releases); `CHANGELOG.md` is
frozen.
