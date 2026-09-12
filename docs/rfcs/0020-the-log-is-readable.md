# RFC 0020 — The log is readable

- **Status:** Implemented.
- **Question:** The evidence log is the source of truth, and nothing could read
  it *as a log*. `assertion(id:)` and `assertions` were deleted when they turned
  out to run Cypher for an AGE edge nothing had ever written; `standings` took a
  target id and nothing else; an `Assertion` exposed who and when but not what
  it recorded or the arguments it ran with; and a client that wanted to follow
  the log — a downstream index, an audit view, a UI that should update when a
  colleague retracts something — had no feed to follow and no subscription to
  open. `Assertion.seq` existed for replay and carried, in its own help text,
  a warning that a naive reader would skip rows. Should the log be readable
  by who, by act, forward from a cursor, and live?
- **What was done:** Three root fields over `evidence.Assertion` — `assertions`
  (by who, what tool, when; newest first), `assertion(id:)` (one act with every
  claim it recorded, in six typed lists, and `actionArgs`) and
  `changes(afterSeq:, limit:)` (ascending from a cursor, **cut at the committed
  horizon** so a late-committing act is never skipped). `standings` reads the
  organization's positions by who took them, on what kind of claim and when,
  each with its `target`. And `Subscription.assertionRecorded`, announced
  from the write's own transaction on commit, in the organization's room.

## Changes

### The `Assertion` type carries what the act recorded

`Assertion` was the provenance half of a claim — subject, app, action, times,
`seq` — and nothing else. It now has `actionArgs` (the JSON the app reported,
never written before by any API path but stored by `manage.py redact` and the
provenance token) and six lists, one per claim table: `instances`, `links`,
`metrics`, `structures`, `standings`, `comments`. They are typed lists rather
than a `Claim` union because the tables are served two ways — `Instance`,
`Link`, `Standing` and `Comment` as their rows, `Metric` and `Structure` as
readings of a row (`RetrievedMetric.from_row`) — and a union would only hide
that seam in a resolver. Each list is a grouped loader keyed on `assertion_id`
(`api/loaders.py`), so a page of assertions costs one query per table selected.
None is narrowed by standing: the question is "what did this act write", and a
claim somebody later retracted was still written.

`Structure` is listed under the act that **first introduced** it. A later act
that names the same datum records an `INFORMS` link, not a structure.

### `assertions` and `assertion(id:)`

`api/queries/log.py`. Organization-scoped the way `standings` is
(`get_active_organization` + `assert_can_access_organization`), `-seq` by
default, paged by `LogPaginationInput`. `AssertionFilter` has `ids`,
`subjects`, `appIds`, `actionIds`, `assertedSince`, `assertedBefore`,
`seqAfter` — every one an explicit `filter_field` method returning a `Q`,
because a plain annotated field on a strawberry-django filter compiles to
`Q(<name>=value)`, and `Q(ids=[…])` against a model with no `ids` column is
an error (or, on `TermFilter` today, a silently unanswerable argument — noted,
not fixed here). `assertion(id:)` of another organization raises; the id is a
uuid nobody could have guessed, so "not found" and "not yours" are one answer.

Indexes `(organization, seq)` and `(organization, app_id)` on `Assertion`
(`evidence/0015`): `seq` alone was unique but the feed always walks one
tenant's slice, and "what did this tool write" was a sequential scan.

### `changes(afterSeq:)` and the committed horizon

`seq` is drawn from a Postgres sequence at insert time, not at commit. Two
writers can take N and N+1 and commit in the other order; a reader that polls
`seq > cursor`, sees N+1 and stores it as its cursor has skipped N forever.
`Assertion.seq`'s help text prescribed the fix at the time the column was
added — gate the feed on the snapshot's xmin rather than serialize the write
path — and the projector's own catch-up (`reproject --incremental`) avoided
the problem differently, with the outbox. The client-facing feed cannot use an
outbox; it uses the gate.

`evidence/log.py::before_every_open_transaction(queryset)` is one raw
predicate over the row's `xmin` system column:

```sql
age("evidence_assertion"."xmin") > age(pg_snapshot_xmin(pg_current_snapshot())::xid)
```

A row counts only if the transaction that wrote it precedes every transaction
still open at the moment of the read. `age()` compares xids across the 32-bit
wraparound; the snapshot's `xid8` is cast down to match the row's `xmin`.
`changes` returns rows strictly after the cursor, ascending, through that gate,
and `nextSeq` is the last seq returned (the cursor itself when nothing was).
`horizon` is the highest seq the gate admits for the organization at all — so
a client can tell "caught up" (horizon at the newest seq it has seen) from
"withheld" (horizon below it).

Two properties of the gate, recorded so nobody rediscovers them:

- **A long-open writer stalls the feed for everyone.** Anything written after
  the oldest open transaction began is withheld until that transaction ends —
  including other writers' rows. A bulk ingest holding one transaction for ten
  minutes delays the feed by ten minutes. That is the trade the help text
  chose over throttling ingest, and `horizon` is how a client sees it
  happening. Ingest that wants a live feed should commit in batches.
- **One window stays open, and it is inside a single statement.** Postgres
  assigns a transaction its id lazily, on first write — for an assertion,
  inside the `INSERT` that also evaluates `nextval` for `seq`, and the seq is
  drawn before the id is assigned. Two inserts interleaving exactly there (T
  takes seq N; R takes N+1, gets its xid and commits; T then gets its xid) let
  R through the gate while T, with the lower seq, is still open. There is no
  round trip in that window. Forcing the xid first (`pg_current_xact_id()`
  before the insert) would widen the window to a statement boundary, and an
  advisory lock would be the serialization the design refused; so it is
  documented and not papered over.

The test (`test_changes_withholds_what_may_still_be_committing`) holds a raw
psycopg transaction open on an inserted assertion, commits a later one from
the main connection, and checks that `changes` returns nothing, that `horizon`
sits below the held seq, and that both rows appear once the held transaction
commits.

### `standings` across the log, and `Standing.target`

`standings(id: ID = null, filters: StandingFilter, pagination:)`. With `id`
it is what it was — every position on one claim, newest first. Without it,
`StandingFilter` narrows the organization's positions by `subjects`,
`appIds`, `targetType`, `since`/`until` (on `Standing.at`, world time) and
`stands`. `targetType` is an enum — `INSTANCE`, `LINK`, `STRUCTURE`,
`METRIC`, `COMMENT` — mapped onto the stored spelling, where an instance is
`'node'` (`filters.STANDING_TARGET_TYPES`).

`Standing.target` resolves the two columns the type deliberately does not
expose, dispatching on `target_type` through the per-table loaders. It is its
own union, `StandingTarget = Instance | Structure | Link | Metric | Comment`,
rather than `ClaimEndpoint`: that one is what a *link* can point at, which
includes `Term` (nobody takes a position on a word) and excludes `Comment`
(they do). `Comment` joins `create_schema(types=[…])` for it — reachable only
through the union and `Assertion.comments`, the runtime failure
`tests/test_print_schema.py` guards against.

### `Subscription.assertionRecorded`

The schema has a subscription root again (`api/subscriptions/`; the package
had sat empty since the one field it used to hold turned out to publish
nothing). `evidence/channel.py` is the kante `Channel`: a pydantic
`AssertionRecorded {id, seq, organization}` and `announce(assertion)`, which
`GraphController._create_assertion` calls beside `watermark.expect` — and
which is `broadcast_on_commit`, so a write that records its assertion and then
fails announces nothing (`test_a_rolled_back_write_is_not_announced`).

The room is `channel.room(organization)` on both sides. Not kante's own
`Channel.org_group`: that spells the room `assertion:org:<id>`, and the
channel layer refuses a colon in a group name, so every broadcast through it
raised inside the commit hook. The subscriber re-fetches the row under its
organization's scope and drops a message whose row is not there, so the room
name is not the only tenant fence. Transport was already wired
(`asgi.py` → `kante.router`, redis channel layer in `settings.py`);
`settings_test.py` gains an `InMemoryChannelLayer`, and the tests drive the
subscription through `api_schema.subscribe` with a stub consumer exposing the
three things `Channel.listen` reads (`channel_layer`, `channel_name`,
`listen_to_channel`). One task drives the generator from start to close,
because strawberry's extensions reset contextvars on exit and a token reset
from another task is an error.

## What this does not do

- **No `Claim` union, no `claims` field.** Six typed lists answer the question
  and keep the two backing kinds apart; a client wanting "everything" selects
  all six.
- **No filter on what was claimed.** `AssertionFilter` is provenance columns
  only. "Every act that touched instance X" is `instance(id:) { standings {
  assertion } }` plus the links' assertions — the log is navigable from the
  claim, and an assertion-side search over five tables would be five joins for
  a question the claim already answers.
- **`assertions` is not gated.** Only `changes` reads through the horizon: a
  newest-first listing is a view of what has committed, and a row appearing a
  moment late is the ordinary case there. The feed is the read where a missed
  row is permanent.
- **The subscription is not a feed.** It says "now"; a consumer that must miss
  nothing pairs it with `changes(afterSeq:)`, which says "everything since".

## Tests

`tests/api/test_log_reads.py` — order, filters, paging; one act's six lists
after `assertEntityExists` with supporting evidence (one instance, `CLASSIFIES`
and `INFORMS` links, one metric, one structure) and after `retractEntity` (one
standing, `target` an `Instance`); `actionArgs` round-trip; `changes` from a
cursor, `nextSeq`, the empty page; the held-transaction horizon test;
`standings` by subject, by `stands`, by `targetType`; tenancy of all three
root fields. `tests/api/test_assertion_recorded.py` — announced on commit,
silent on rollback, silent for another tenant.
`tests/api/test_loaders.py::test_every_declared_loader_is_constructible`
covers the six new grouped loaders.
