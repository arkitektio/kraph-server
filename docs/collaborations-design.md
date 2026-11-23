# Collaborations and workflow sharing in kraph

**Status: Proposal** (2026-11-23). This is a design. It changes no code. It is written against
kraph `ad73cbf`, arkitekt-service 10.0.0, authentikate 7.0.0 and koherent 4.3.0, with mikro's
adoption (`4e3eeb7`, `58e8539`) as the template.

## Recommendation in brief

1. **Use two units of sharing, one per surface (RFC 0025).** A **view** (`core.Graph`) is what a
   guest browses. Its categories, queries, plots, runs and drawing come along as live parts
   through the CASCADE keys they already have. An **act** (`evidence.Assertion`) is what a
   workflow made. The claims it recorded (instances, links, metrics, standings, comments) come
   along as its parts. No claim is ever put into a collaboration on its own, and **no claim gets
   a `graph` FK**: `evidence/models.py:9-13` forbids one, and it would bring back the
   one-view-per-claim bug described at l.34-41.
2. **Hold reads at about 15 fences, not 200.** About 86 of the ~135 `for_organization` calls are
   folds (projector, identity, selector, state, writer). They must stay organization-wide.
   Only the reads that hand objects to a client get held.
3. **Teach the gate kraph's dataclass types.** `Node`, `Entity`, `Structure`, `Metric`,
   `Relation` and the rest wrap `graph_engine.retrieved` dataclasses. The gate passes them
   through untouched today, so it fails open below a model-backed field. arkitekt-service needs
   an adapter registry (type → the model row it stands for) and a `part_of` declaration
   (§2.4).
4. **Ship workflow filtering first, without guests.** Add an indexed
   `Assertion.root_action_id`, fill it from `action_args.root_task`, fix the feed ingest that
   drops it, and add `createdUnder` on `assertions` and on the node/edge lists. This is useful
   on its own and is a prerequisite for `shareWorkflow`.
5. **Guests write nothing.** A guest's claim would enter the organization's log and be drawn in
   views the guest cannot see. Comments are the only later candidate.

---

## 0. Where kraph stands today

- **Guests are shut out, and safely.** kraph never calls `Service.share()` and has no
  `CollaborationGate`. authentikate's default (`SCOPED_TOKENS: auto`) therefore rejects every
  guest token at authentication (`authentikate/scoped.py:17-20`). Nothing leaks today.
- **Hosted structures:** five (`kraph_server/service.py`): `@kraph/todoitem`,
  `@kraph/todoitemstructure`, `@kraph/pairsquery`, `@kraph/pairsrun` and `@kraph/model`.
  There is no `@kraph/graph` and no evidence structure. The comment at `api/schema.py:1035`
  ("kraph serves no hosted structures") is stale.
- **Dependencies are a major behind:** `arkitekt-service>=9.6.0`, `authentikate>=6.1` and
  `koherent>4` (`pyproject.toml:17-34`). Collaborations need ≥10.0.0, ≥7.0.0 and ≥4.3.0.
- **Provenance:** only `Graph` has a koherent `ProvenanceField` (`core/models.py:155`). For
  claims, the `Assertion` *is* the provenance (`evidence/models.py:44-48`). The root task
  appears only inside `Assertion.action_args["root_task"]` (`graph_engine/controller.py:57-111`,
  l.103). `action_id` (the task, `tsk`) is indexed (`evidence/models.py:135-140`).

## 1. What a guest of a kraph collaboration sees

### 1.1 Candidate units

| Unit | How claims get in | Verdict |
|---|---|---|
| **A. Graph as whole, claims as parts via a new `graph` FK** | FK + CASCADE | **Rejected.** `evidence/models.py:9-13`: "Nothing in this module may grow a `graph` foreign key". A claim is drawn by every view whose rules admit it (`selector.instances_for` l.604, `graph_ids_for_instance_ids` l.715). An FK would bind each claim to one view, which is exactly the bug the module docstring records. |
| **B. Graph as whole, claims seen *through* the view** | derived: a claim is visible when a held view draws it | **Right for browsing, wrong for workflows.** It matches RFC 0025: a `Node` is one view's drawing (`api/types.py:1618`) and carries `Node.graph`. It needs a derived-visibility hook, because no FK path exists. A workflow creates claims, not views, so `shareWorkflow` finds almost nothing to put in. |
| **C. Act (`Assertion`) as whole, its claims as parts** | each claim's required `assertion` FK, declared as part-of | **Right for workflows.** A workflow is a set of acts (`root_action_id = W`). One item per act covers up to 5000 metrics (`assertMetricValues`). All `assertion` FKs are `PROTECT` (`evidence/models.py:509, 634, 807, 897, 998, 1312`), so `guests.wholes()` does not follow them (`_cascades` is false). arkitekt-service needs `part_of()` (§2.4). |
| **D. Each claim row as its own whole** | one item per Instance/Structure/Metric | **Rejected.** A pipeline would write one `CollaborationItem` per metric. `Guest.rows()` would then load every one of those pks per operation. |

### 1.2 Recommendation: views and acts

**A shared view** (`@kraph/graph`, new structure) brings these parts along by the existing rule
(required CASCADE FK, ≤3 hops). Nothing has to be declared for them:

| Part | Path | Source |
|---|---|---|
| `Category` (all 9 kinds), `GraphSchema`, `GraphOntology`, `CategoryAssertedTerm` | `graph` | `core/models.py:303, 424, 469, 723` |
| `GraphQuery` / table / pairs queries | `graph` | `core/models.py:1242` |
| `ScatterPlot` | `graph_query__graph` (2 hops) | `core/models.py:1357` |
| `PairsQueryRun`, `PairsQueryRunEntry` | `graph`, `run__graph` | `datasets/models.py:19, 99` |
| `ProjectionVertex/Label/Member/Edge` | `graph` | `graph_engine/models.py:97-290` |

`depends=`: `Graph.image` and category images (`MediaStore`), plus the vocabulary rows the
categories name (`Term`, `StructureKind`; but see A4 below). `@kraph/pairsquery` already has
`Graph` as its CASCADE whole, so once `@kraph/graph` exists it is a part. `@kraph/pairsrun` is a
part too. `@kraph/model` (`TrainedModel`) stays a whole of its own: `trained_on` is `RESTRICT`,
nullable (`datasets/models.py:137+`), and it gets `depends=[store]`.

What a guest of a view sees, field by field:

- **Yes:** `graph(id:)`, its categories, queries, plots and runs; `nodes(graph:)` and
  `node(id:, graph:)`, plus edges/relations read in that view, with their **derived
  properties**; `renderGraphTable/Pairs/TablePlan` for that graph.
- **Folded properties leak by design.** A drawn property folds over every metric the category's
  rule admits, organization-wide (`State` is organization grain). Sharing a view shares what it
  draws, just as sharing a mikro scene shares what its layers draw. Say this in the UI.
- **No in phase 2** (claim grain, organization-wide or other views): `Node.claim` (l.1699),
  `members` (1705), the panel fields `component/labels/sameAs/differentFrom/conflicts/
  connections` (1736-1812), and `drawnIn` (1821), which names other views. `Structure.metrics`
  and `informs` (2186, 2219) are also no. The gate makes these null for a guest. Where the field
  is non-null it errors at its path, which is acceptable. Phase 4 can open them through
  derived visibility if anyone asks.

**A shared act** (`@kraph/assertion`, new structure, `created_under=Q(root_action_id=root)`):

- Parts via `part_of(model, "assertion")`: `Instance`, `Link`, `Metric`, `Standing`, `Comment`.
- **Metric trap:** `Metric.structure` is a required CASCADE (`evidence/models.py:571-575`), so
  today a metric is a live part of its `Structure`. A structure is minted once, by the first act
  that names it, and later workflows only add metrics to it. Two problems follow. If the
  structure is shared, every metric about it from every workflow is shared too. And
  `shareWorkflow` would report a later workflow's metrics as `skipped`. Declare
  `not_part_of(Metric, "structure")`, the same move mikro made for tables in `58e8539`. A metric
  then belongs to its act, and the structure comes with it via `depends`.
- `depends`: the `Structure`s its metrics and links name, the `Instance`s its links point at
  (`Link.source_ref/target_ref` are values, not FKs), and its vocabulary (`Term`, `MetricKind`,
  `StructureKind`, all required `PROTECT`, so without them non-null fields error at their path).
- `Assertion.action_args` carries `caller`, `agent`, `issuer` and `token_id`
  (`controller.py:92-110`). See Q3.

**Out of scope for now:** `Project`, `TodoList/Item/ItemStructure`. They are product state (C7),
they name objects across services, and nobody has asked to share a board. See Q7.

## 2. Holding reads to it

### 2.1 Two facts that set the shape

1. **Guests get a `Membership` row.** `aexpand_token_context` →
   `aexpand_membership` (`authentikate/expand.py:137-155, 268-285`) has no `is_scoped` branch.
   So kraph's own fences, `assert_can_access_organization` (`api/context.py:57`) and
   `Graph.validate_accessible` (`core/models.py:295-300`, organization equality only), **pass a
   guest**. Every hand-scoped read hands a guest the whole organization unless something else
   holds it.
2. **The gate understands only Django models.** `_hands_out_objects` / `_held`
   (`arkitekt_service/graphql.py:290-311`) look at `Model` and `QuerySet` and pass everything
   else through. At a root field, `_relates` closes types that are not model-backed (l.181-193).
   That is safe, but it means `nodes`, `structures` and `metrics` are simply refused. **Below** a
   model-backed root (`graph`, `assertion`, `instance`, `link`), a resolver returning a
   dataclass-backed type is never checked. This is the real leak.

### 2.2 Inventory

| Kind of read | Where | Count | Treatment |
|---|---|---|---|
| Fold reads, `for_organization` | `graph_engine/projector.py` 28, `controller.py` 16, `evidence/identity.py` 13, `writer.py` 10, `selector.py` 8, `state.py` 5, `traversal.py` 2, `watermark.py`, `metric_batch.py`, `datasets/logic.py`, `core/models.py` 1 each | **86** | **Untouched.** They compute what a view draws. Narrowing them would change the drawing per reader. |
| Management commands, managers | `redact.py` 9, `rebuild_identity.py` 1, `evidence/managers.py` 3 | 13 | Untouched. |
| Hand-out reads, `for_organization` | `api/queries/kinds.py` 6, `api/types.py` 5, `_edges.py` 5, `comment.py` 3, `_nodes.py` 3, `structure.py`, `log.py`, `claim.py`, `filters.py`, `subscriptions/log.py` 1 each; `evidence/panel.py` 4, `claims.py` 5 | **36** | Held, through the fences below. |
| `get_queryset` fences | `api/types.py:117` (`org_scoped`), `:144` (`_kind_dispatch`), `:193` (`kind_interface`), `:1328` (`_scatter_plot_scoped`), `datasets/types.py:32`, `todos/types.py:40`, `projects/types.py:30` | **7** | Add `object_scope(qs, info=info)`, as mikro did in `core/scoping.py`. This covers Graph, 9 category types, queries, plots, runs and models, at the root and on pk lookups. |
| View entry | `api/context.py:144` `get_accessible_graph`, 10 call sites | **1** | For a guest: refuse unless `guest.sees(graph)`. One edit covers every `graph:`-scoped read. |
| Claim-grain roots | `assertion(s)`, `instance`, `link`, `standings`, `comments`, `metricsForAssertion`, `structures`, `metrics`, `changes` | ~9 resolvers | Phase 2: closed (plain types close themselves; model ones are held by the gate). Phase 3: `object_scope` in each resolver. |
| `get_active_organization` / `assert_can_access_organization` | 61 / 27 sites | — | Not fences against guests (fact 1). No change. Mutations stay closed to guests. |

The root query has **90 fields** and the mutation root **114** (`api/schema.py:77, 447`). Under
`closed_roots`, a guest reaches only fields that return a model-backed type, an adapted type
(A1), or opt in with `allow_scoped`. Phase 2 opts in `nodes`, `node`, `entities`,
`relations`, the typed event lists and the three `render*` fields. All of them go through
`get_accessible_graph`.

### 2.3 Dataclass types through the gate

One adapter per wrapper type, registered with arkitekt-service (A1). Each maps an object to the
row it stands for:

| GraphQL type (`api/types.py`) | Backed by | Held as |
|---|---|---|
| `Node`, `Entity`, `NaturalEvent`, `ProtocolEvent` (1618, 1986) | `RetrievedNode` with `graph_id` | `(Graph, graph_id)`: the view decides |
| same, row-backed (`graph_id is None`) | `RetrievedNode.row_id` | `(Instance, row_id)` |
| `Structure` (2128), drawn where a view mounts it (RFC 0027) or not | `RetrievedStructure` | `(Graph, graph_id)` or `(evidence.Structure, row_id)` |
| `Metric` (2353) | `RetrievedMetric.row_id` | `(evidence.Metric, row_id)` |
| `Relation`, `StructureRelation`, `Description`, `Measurement` (2661, 2759, 2793) | `RetrievedEdge` | `(Graph, …)` in a view, else `(Link, row_id)` |
| `NodeDrawing` / `EdgeDrawing` | `graph_engine/results.py` | `(Graph, graph_id)` |
| `Asserted*`, stats, `GraphTableRender`, pagination | value objects | declared plain: passed through |

The rule: **a value read in a view is held by the view. A value read at claim grain is held by
its row.** `sees()` stays a set lookup against `Guest.rows(model)`.

### 2.4 What arkitekt-service needs (minor release, 10.1.0)

- **A1. Adapters.** `register_held(cls, to_row: Callable[[obj], tuple[type[Model], pk] | Model | None])`.
  `_held`, `_known`, `_hands_out_objects` and `_relates` consult the registry (`_relates` so that
  roots returning adapted interfaces are not closed). About 60 lines.
- **A2. Strict mode.** `CollaborationGate(strict=True)`: for a guest, an object whose GraphQL type
  is not model-backed, not adapted and not declared plain is an error rather than a pass. This
  turns kraph's open-by-default nested fields into closed-by-default. Recommended for kraph,
  optional for others.
- **A3. `part_of(model, *fields)`.** The inverse of `not_part_of`: count a required
  non-cascading FK as a whole path in `wholes()`. Needed for `Instance.assertion` and the other
  `assertion` FKs, which are `PROTECT` on purpose (an act is never deleted; `redact` relies on
  it).
- **A4. Nested-only references.** Something like `IDENTITIES` for vocabulary
  (`Term`, `StructureKind`, `MetricKind`): handed out below an object a guest sees, never at a
  root. Without it, every act and every view has to carry its words as `depends` items.
- **A5. Batch membership.** `Guest.rows()` loads every held pk of a model into memory
  (`guests.py:310-346`). That is fine for scenes, but not for metrics. Add
  `Guest.sees_many(objs)` → `model.filter(pk__in=batch) & q` for models declared large. Mikro
  benefits as well.

## 3. Workflow coverage

### 3.1 `Assertion.root_action_id`

- **Column:** `root_action_id = CharField(max_length=1000, null=True)` plus
  `Index(fields=["organization", "root_action_id"])`. It goes beside `action_id`
  (`evidence/models.py:135`) and follows the same nullable semantics: a human at a keyboard has
  no workflow.
- **Write path:** `ProvenanceContext` (`graph_engine/input_models.py:845-850`) gains
  `root_action_id`. `_provenance_claims` sets it from `provenance.rtk` (`controller.py:103`).
  `writer.create_assertion` (`evidence/writer.py:228-247`) is the single insert, so the new
  column lives there. `assertMetricValues` already goes through `_provenance_from_info`
  (`controller.py:1263`), so the metric pipeline is covered.
- **Fed acts drop the root today.** mikro's feed sends `task.root_task_id`
  (mikro `metric/logic.py:336-345`), but `ingest.parse` reads only `task.task_id`
  (`evidence/ingest.py:166-168`, `Producer` at l.50-60), and `_provenance_of_fed`
  (`controller.py:1330-1364`) stores no root. Fix both. **Historical fed acts cannot be
  backfilled from `action_args`**, because the root was never stored. See Q9.
- **Data migration** (evidence `0004`, `RunSQL`, reverse no-op), batched by `seq` if the table
  is large:
  `UPDATE evidence_assertion SET root_action_id = action_args->>'root_task' WHERE root_action_id IS NULL AND action_args ? 'root_task' AND action_args->>'root_task' IS NOT NULL;`
  It is safe to re-run. Under the migrations-and-jobs rules (no upgrade system), it belongs in the
  migration itself, not in a setup job.

### 3.2 `createdUnder` on kraph's surfaces

arkitekt-service's `SharingFilterMixin` cannot be used here as-is. `created_under_q` asks
`Service.hosting()`, which only searches `Service.sharing` (`service/service.py:348`). Until kraph
shares, it falls through to koherent and returns `Q(pk__in=[])`, so the filter is **silently
empty**. kraph's claim filters are also `pydantic_input`s (`api/filters.py:52-175`), not
`filter_type`s. Filter on the column directly:

| Surface | Filter | Where |
|---|---|---|
| `assertions(filters:)` | `root_action_id = W` | `AssertionFilter` (`api/filters.py:465`, next to `action_ids` at l.488) |
| `standings(filters:)` | `assertion__root_action_id = W` | `StandingFilter` (l.531) |
| `nodes/entities/…(graph:, filters:)` | an individual matches when **any member** was asserted under W: `ProjectionMember(graph=G, ref__in=Instance(assertion__root_action_id=W)).values(vertex__ref)` | `_nodes.narrow` (`api/queries/_nodes.py:108`), one place for every node list |
| edge lists (read `Link`) | `assertion__root_action_id = W` | `api/queries/_edges.py` |
| `structures` | minted under W, **or** measured under W (`metrics__assertion__root_action_id`). Recommend *measured*: that is what a pipeline did. | `StructureFilter` |
| `metricsForAssertion` / metric lists | `assertion__root_action_id = W` | `api/queries/metric.py` |
| `graphs` | koherent history (`ProvenanceField`, `core/models.py:155`): `recorded_under` already works | `GraphFilter` (mixin, once sharing) |
| pairs runs, models | nothing records a task. Add koherent `created_through` FKs (the cheap path in `koherent.lookups`), or report them as `unknown` | `datasets/models.py` |

### 3.3 `shareWorkflow` in kraph

Once `@kraph/graph` and `@kraph/assertion` are hosted, arkitekt-service's `share_workflow`
(`collaborations/items.py:243-294`) works unchanged:

- acts (`made_in = Q(root_action_id=W)`) go in by hand, and their claims are covered;
- graphs it created go in by hand (koherent history);
- runs and models count as `unknown` until they record a task.

The orkestrator calls it on every service with the same key, so one workflow lands in mikro
(images, tables) and kraph (its metrics and entities) under one collaboration.

## 4. Writes

**Recommendation: none.** Every kraph write records an act in the organization's log. Views whose
rules trust everyone (no SUBJECT clause) would then draw a guest's claim to full members, and in
views the guest cannot see. Retractions and attestations are positions on other people's
claims. `kraph_curator` changes vocabulary. None of these is a guest's to make. Mutations stay
closed (authentikate refuses scoped mutations unless they opt in), and subscriptions are already
refused.

**Possible later exception:** `commentOnStructure` / replies. Comments are never projected (only
`controller.py` reads `Comment`), so a guest's comment changes no drawing. It would mirror
mikro's `createAnnotation`: `allow_scoped=True` plus
`require_in_collaboration(structure, any_role_of=["commenter"])`.

## 5. Phases

| Phase | Content | Effort | Ships alone? |
|---|---|---|---|
| **P0. Workflow filter** | `root_action_id` + index + migration; write path; ingest fix; `createdUnder` on `assertions`, `standings`, node and edge lists, structures, metrics; tests in `tests/log/` and `tests/surface/` | **1.5–2 d** | **Yes. Ship first.** "What did this pipeline assert?" becomes one query, and nothing about guests changes. |
| **P1. arkitekt-service 10.1** | A1–A5, tests in arkitekt-service, release | 2–3 d | Yes (no behaviour change for mikro unless it opts in). |
| **P2. Views shared** | bump deps; `INSTALLED_APPS += arkitekt_service.collaborations`; `@kraph/graph` Structure + Signal in `contract.py` (declare-in-hub-contract rule); `CollaborationGate(strict=True)` after `AuthentikateExtension` (`api/schema.py:1023`) + `annotate_schema`; the 7 fences + `get_accessible_graph`; adapters; collaboration queries/mutations (`addToCollaboration`, `addManyToCollaboration`, `removeFromCollaboration`, `collaboration(key:)`); `SharingFilterMixin` on Graph/GraphQuery/run/model filters; `tests/product/test_sharing.py` with a second static token (rekuest harness pattern) | **4–5 d** | Yes |
| **P3. Acts shared** | `@kraph/assertion` structure, `part_of`, `not_part_of(Metric, "structure")`, depends; `shareWorkflow`; open the claim-grain roots with `object_scope`; strip `actionArgs` for guests (Q3) | 3–4 d | Yes |
| **P4. Claims through views** (optional) | derived visibility: `Instance` visible when a held graph's `ProjectionMember` has it; `Link` when both ends are visible; `Structure`/`Metric` through INFORMS/MEASUREMENT links to visible members. Opens `Node.claim`/`members`/`Structure.metrics` to guests | 3–5 d | Only if asked |

Total to a usable feature (P0–P3): **about 11–14 days.**

## 6. Risks

- **Fail-open nested fields (highest).** Without A1/A2, any dataclass-backed field below a
  model-backed root reaches a guest unchecked, and guests pass every organization check
  (§2.1). **Do not merge P2 without strict mode**, and add a test that walks the SDL from every
  guest-open root and asserts that each object type it reaches is model-backed, adapted or
  declared plain. That test checks the schema's behaviour, not its source.
- **Folded properties.** A shared view draws folds over claims that are not shared (§1.2). This
  is intended, but it must be explicit in the share dialog.
- **Projection lag.** Holding by graph is exact. P3/P4 membership through `ProjectionMember` is
  cheap and indexed (`(graph, ref)` unique), but it trails the log while the draw is `pending`.
  Membership through the rule (`instances_for`) is exact but costs a rule evaluation per held
  graph per operation. Recommend `ProjectionMember`; `lag` is 0 in steady state.
- **Scale.** `CollaborationItem.object_id` is a string cast in a subquery (`guests.py:_ids`).
  With one item per act it stays small. `Guest.rows(Metric)` does not stay small without A5.
- **`Service.share()` changes `Service.hosting()` globally.** After P2, the existing five
  structures take part in `whole_of`. `@kraph/todoitemstructure` already declares
  `whole=item`. `@kraph/pairsquery` becomes a part of its graph and can no longer be put in
  alone (`SharedWithItsWhole`). That is correct, but the orkestrator has to know.
- **Two fold readers disagree.** The panel is trust-everyone (organization grain); a view is its
  category's rule. Guests must never be handed the panel (closed in P2 and P3, by adapter in P4).

## 7. Open questions (each with a recommended answer)

1. **Two units (views + acts), or only one?** *Recommend both.* Views without acts make
   `shareWorkflow` empty. Acts without views give a guest raw claims with nothing to browse.
2. **May a guest of a view read the claims beneath it (`Node.claim`, `members`, standings), or
   only the drawing?** *Recommend the drawing only* (P2). P4 is there if a collaborator needs to
   audit a node.
3. **Should a shared act expose `actionArgs` (caller, agent, issuer, `token_id`, args hash)?**
   *Recommend stripping it to `{task, root_task, args_hash}` for guests.* The hash keeps
   reproducibility. Identities stay with `subject`/`app_id`.
4. **Should a metric belong to its act rather than its structure (`not_part_of(Metric, "structure")`)?**
   *Recommend yes.* Otherwise sharing one workflow's metrics shares every workflow's metrics on
   the same data, and `shareWorkflow` skips most of a pipeline.
5. **Should sharing a mikro image share kraph's claims about it automatically?** *Recommend no.*
   Claims are shared per act (workflow) or per view, explicitly. A later
   `shareClaimsAbout(collaboration, identifier, objects)` could put in the acts that measured
   those structures, if users ask.
6. **Guest writes?** *Recommend none*; comments behind a `commenter` collaboration role later.
7. **Projects and todos in scope?** *Recommend not now.* A todo item names objects in other
   services, and sharing the board would need those shared too.
8. **What is the root of an act whose token has no `rtk`?** *Recommend `rtk` if present,
   else `action_id` when `parent_task` is null* (a task without a parent is its own root),
   *else null.* Check this against rekuest's token minting before P0.
9. **Backfill historical fed acts?** *Recommend no.* Their root was never stored, and
   re-reading mikro's feed is a no-op by `Metric.source_uuid`. Document that `createdUnder`
   covers fed metrics from P0 onwards.
10. **Vocabulary for guests: `depends` items or nested-only references (A4)?** *Recommend A4.*
    Words are not data anyone shares, but a claim cannot be read without its word.

## Appendix: adjacent findings (not fixed here)

- `evidence/selector.py:118` compiles the `ACTION` rule field to `assertion__action_name`, which
  is never written (`controller.py:69-74` says to filter on `action_id`). An `ACTION IS …`
  clause therefore matches only human claims under `NOT_IN`, and nothing under `IS`. This is
  worth an RFC before anyone builds "a view of a workflow" on a `ROOT_ACTION` rule field.
- The comment at `api/schema.py:1035` says kraph serves no hosted structures. It serves five.
