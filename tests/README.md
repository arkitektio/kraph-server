# The test suite, laid out by the model

The suite is organized by *which property of the model a test holds*, not by
Django app and not by the bug that prompted it. One directory per layer of the
model, one module per property, named as a sentence you can read as the claim
being made. The model is the one the RFCs 0021–0025 implement:

| Axiom | Statement |
|---|---|
| **A1** | An act is immutable and one transaction |
| **A2 / C1** | One claim shape; every claim names its kind, its time, its confidence |
| **A3** | Claims about claims are claims (standing, citation, comment) |
| **A4** | A word's identity is what claims reference |
| **A5 / C3** | Identity is the view's fold under its trust |
| **A6 / C2** | A view is a pure function of the log; every fold is under some view |
| **A7** | A projection is a cache as of a position |
| **C4** | Two surfaces, log and view, never mixed silently |
| **C5** | A write returns the act |
| **C6** | A datum is an individual with an external identity |
| **C7** | Product state is inert |

```
tests/
  conftest.py     the one conftest: docker stack, identity, `api_context`, `api_schema`,
                  the graph fixtures, the evidence fixtures
  support/        the helpers every module uses — nothing else is imported across tests
  guards/         no database: the shape of the code and the schema
  log/            A1–A4
  identity/       A5 / C3
  view/           A6
  projection/     A7 / C2
  datum/          C6
  surface/        C4 / C5
  product/        C7
  integration/    the compose file the stack runs on
```

## Running

Every test that touches the database needs the docker stack (`tests/integration/docker-compose.yaml`,
Postgres on 5555, redis on 6666, seaweedfs on 18888); `conftest.py::backend_stack` brings it down
and up once per session, so **only one pytest session may run at a time**. Remove stale
`integration-*` containers before a run.

```bash
uv run pytest                                  # everything, ~2½ minutes
uv run pytest tests/log                        # one layer
uv run pytest tests/guards                     # no database, seconds
uv run pytest tests/projection/test_rebuild_equals_the_write_path.py   # the matrix
```

## The layers

### guards — no database

| Module | Holds |
|---|---|
| `test_every_module_imports` | every module in the project imports |
| `test_the_schema_renders_and_splits_its_grain` | the SDL builds and **is** `test.graphql`; claim types stay off the view interfaces (C4) |
| `test_migrations_are_committed` | every model change has its migration (A1) |
| `test_the_draw_follows_the_act` | every write draws after its transaction, under `_draw_after`, never inside it (A1, A7) |
| `test_the_projection_signals_survive_garbage_collection` | the namespace and graph-delete receivers are held strongly (A7) |
| `test_the_projector_is_a_protocol` | the projection seam is a named protocol; no other module names the drawing's tables (A7) |
| `test_internal_keys_never_leak` | `__`-prefixed bookkeeping never reaches `properties` (C4) |
| `test_config_validates` | `config.yaml` validates |
| `test_the_surface_offers_no_erasure` | no mutation destroys or edits a claim in place (A1) |
| `test_vocabulary` | the suite speaks the model's vocabulary and none of the retired words |

### log — A1–A4

| Module | Holds |
|---|---|
| `test_an_act_is_one_transaction` | one act, one assertion, all or nothing — entity, batch and event paths |
| `test_the_log_is_append_only` | the database refuses `UPDATE` and `DELETE` on the log |
| `test_the_log_is_totally_ordered` | `seq` is assigned, monotonic, folded by, and cut at the committed horizon |
| `test_every_claim_has_a_time_and_a_confidence` | `observed_at` and `confidence` on every claim kind (RFC 0015, 0016) |
| `test_a_claim_names_its_value_kind` | the caller states the kind; a mismatch says so |
| `test_standing_is_a_claim_on_a_claim` | retract and attest are positions on the record, for every kind (A3) |
| `test_a_claim_cites_its_sources` | `DERIVED_FROM` under the citing act (RFC 0017) |
| `test_a_words_identity_is_immutable` | `Term` / `StructureKind` / `MetricKind` identity columns cannot be rewritten (RFC 0022) |
| `test_a_write_names_a_word_not_a_view` | a claim under a word no view declares is recorded and picked up later |
| `test_the_log_is_tenant_scoped` | shared within an organization, fenced between them |
| `test_comments_are_claims` | author and time are the assertion; resolution is a standing |

### identity — A5 / C3

| Module | Holds |
|---|---|
| `test_the_organization_fold_agrees_with_the_log` | the org-grain identity cache equals a refold |
| `test_the_fold_is_the_views` | `samenessRule` decides whose merges count, across categories (RFC 0024) |
| `test_a_view_draws_one_vertex_per_individual` | one vertex per component, members listed, any member addresses it (RFC 0018) |
| `test_a_difference_vetoes_sameness` | `DIFFERENT_FROM` vetoes the direct `SAME_AS`; a conflict through a third stays merged and is reported (RFC 0019) |
| `test_the_panel_folds_over_the_component` | the panel is unioned over the component, never one instance |

### view — A6

| Module | Holds |
|---|---|
| `test_a_definition_is_a_rule_list` | the rule language and its compiler (RFC 0010); CONFIDENCE / OBSERVED_AT total over kinds; migrations 0019, 0020, 0024 |
| `test_a_definition_is_refused_by_name` | what no view can draw is refused rather than dropped |
| `test_a_view_admits_the_claims_its_rules_cover` | primitive and defined categories; corrections across derived words |
| `test_a_claim_is_drawn_under_every_admitting_category` | every admitting label, one vertex; a conflicting property is refused (RFC 0019) |
| `test_existence_folds_per_category` | existence is a fold per category; the view holds only what exists |
| `test_an_edge_is_the_fold_of_its_claims` | two claims, one edge; participations by role; `admitting_categories` (RFC 0021) |
| `test_trust_is_the_categorys_rule` | the category's rule governs classification, existence, edges and measurements (RFC 0009) |
| `test_rule_evidence_is_the_propertys_own_rule` | `rule.evidence` replaces the category's rule for one property (RFC 0014) |
| `test_a_rule_reads_belief_time_and_world_time` | `ASSERTED_AT` and `OBSERVED_AT` are two axes |
| `test_rules_on_every_claim_family` | structure relations and measurements carry rules too (RFC 0012) |
| `test_every_change_to_a_view_is_a_version` | a meaning change is a version; product state is not |
| `test_a_schema_change_costs_what_the_diff_says` | the rescan matrix |
| `test_changing_a_view_is_rbac` | owner, admin or superuser (RFC 0013) |
| `test_deleting_a_view_leaves_the_log` | deletion is guarded and records what went; the claims survive |
| `test_the_definition_document_is_the_views_meaning` | `materialize` and the definition mutations |
| `test_the_namespace_is_derived_from_the_view` | spec from the definition, DDL from the spec (RFC 0006) |
| `test_the_asserted_terms_index_agrees_with_the_definitions` | the derived-word index is right, incrementally and rebuilt |

### projection — A7 / C2

| Module | Holds |
|---|---|
| `test_rebuild_equals_the_write_path` | **the matrix**: every kind of thing a view draws, drawn by the write path, then by a full rebuild and by `reproject --incremental`, compared whole |
| `test_drawing_converges` | drawing twice leaves one vertex |
| `test_incremental_replay_draws_what_is_owed` | the outbox says what is owed; the replay draws that and settles exactly it |
| `test_the_cursor_is_derived_from_the_outbox` | the cursor is never stored; a failed draw holds it; evidence commits first |
| `test_the_runner_converges_what_the_write_path_left` | a failed drawing is a pending act; the runner applies the outbox under the organization lock that `rebuild` shares (A7) |
| `test_the_state_vector_is_a_monoid` | incremental folds equal a recompute over random sequences |
| `test_derived_properties_are_materialized` | every derived value is on the vertex before a read |
| `test_a_write_reaches_every_view_that_reads_it` | ingest fans out over every informed individual in every view |
| `test_reads_do_not_compute` | destroy the fold's inputs and the read still answers |
| `test_the_database_refuses_an_undeclared_category` | the composite FK on labels (RFC 0006) |
| `test_a_rule_change_redraws_what_it_owns` | a category edit redraws its nodes, in-request |
| `test_the_operator_commands_rebuild_and_redraw` | `reproject`, `rematerialize` and their reports |

### datum — C6

| Module | Holds |
|---|---|
| `test_a_structure_is_an_individual` | a datum has a standing, the folds honour it, agreement is countable; never `ensure`d (RFC 0023) |
| `test_kinds_are_the_organizations_vocabulary` | one kind per identifier per organization |
| `test_a_measurement_informs_what_it_describes` | metrics, supersession, and the INFORMS claim's standing |

### surface — C4 / C5

| Module | Holds |
|---|---|
| `test_two_surfaces_never_mix` | a `Node` names its view and its position; `drawnIn` and `node(id:, graph:)` agree (RFC 0025) |
| `test_a_write_returns_the_act` | `assertion` + claim + `drawings` |
| `test_a_node_names_its_view` | membership is the rule's, kind is the claim's |
| `test_edge_lists_round_trip` | list ids are claim ids; an undrawn edge is labelled by its kind |
| `test_claim_lists_page_filter_and_order` | claim lists at the log's grain |
| `test_the_log_is_readable` | `assertions`, `assertion`, `standings`, `changes` (RFC 0020) |
| `test_interface_fields_resolve_fragments` | interface fragments resolve by `kind` |
| `test_categories_and_views_are_listable` | categories and views list; presentation is inert |
| `test_loaders_are_per_request` | loaders batch, tolerate misses, die with the request |
| `test_reads_are_tenant_scoped` | every read is fenced to the caller's organization |
| `test_a_property_can_explain_itself` | the BIOLOGIST.md sentence as one query |
| `test_the_vocabulary_is_navigable` | terms and categories, both directions |

### product — C7

| Module | Holds |
|---|---|
| `test_product_state_is_inert` | archiving, images and layout persist and move nothing else |
| `test_a_saved_query_is_a_plan` | the plan is the contract |
| `test_uploads_reach_the_object_store` | presigned grants work end to end |

## Rules the suite keeps

1. **One conftest.** `tests/conftest.py` holds every fixture. `api_context` is the static
   token's tenant (`static_org`); `organization` (`evidence-org`) is a second tenant for
   tests writing evidence rows directly. A test that mixes them writes evidence the API caller
   cannot see.
2. **A test module imports only `tests.support.*`** — never another test module.
3. **Every GraphQL document is declared once.** Mutations in `support/writes.py`, queries in
   `support/reads.py`. A document only one module uses may stay local; the moment a second
   module wants it, it moves.
4. **`rebuild_projection` is called in four places**: the matrix, the incremental-replay
   module, the cursor module, and `support/graphs.py::rebuild`. Everything else rebuilds
   through `graphs.rebuild`.
5. **Names are the model's**: `retract`, not `archive`, for a claim; `supersede` /
   `recordMetrics`, not `update_*`; no `selector`, no `lifecycle`, no lowercase `rollup`, no
   graph database. `guards/test_vocabulary.py` enforces it; a `History:` paragraph and a line
   ending `# retired` are exempt.
6. **Docstrings state the property first.** The story of the bug a test was written against
   goes in a trailing `History:` paragraph, or goes.
7. **Strict asyncio.** Every async test carries `@pytest.mark.asyncio` and
   `@pytest.mark.django_db(transaction=True)`; no module-level `pytestmark` mixes sync and
   async or DB and no-DB tests.

## Support

| Module | Offers |
|---|---|
| `writes.py` | every mutation document, and `execute`, `create_entity`, `create_event`, `create_relation`, `create_structure`, `classify`, `assert_entity`, `merge`, `differ`, `roi` |
| `reads.py` | every query document, and `node_properties`, `property_of`, `standings_of`, `retrieved_node` |
| `claims.py` | writer-level claims by named annotators at chosen moments: `mint`, `classify`, `relate`, `participate`, `same`, `different`, `measure`, `structure`, `ensure_kind`, `structure_row`, `metric_row` |
| `drawing.py` | what a view drew: `vertex_count`, `labels_of`, `members_of`, `edge_count`, `edges_between`, `participations`, `assertion_counts`, `snapshot`, `edge_snapshot` |
| `graphs.py` | views from definition documents (`graph_with`, `example_graph`, `graph_declaring`, `define_entity`), `rebuild`, and the shared dates and definitions |
| `rules.py` | terse builders for the RFC 0010 rule language |
| `namespaces.py` | catalog-level assertions about a graph's namespace |
| `sessions.py` | a second database session |
| `sdl.py` | the rendered schema's mutation fields |
| `identity.py` | the identity the static token authenticates as |

## Where the old files went

The suite used to be 117 modules in `tests/{api,evidence,projector,schema,instance,insights}`
plus thirteen at the top level. `tests/instance/` was never in git: `.gitignore` line 69
(`instance/`) hid the whole directory, so its seven modules first appear in history inside
their targets below. Whole-module moves:

| Old | New |
|---|---|
| `test_no_dead_imports.py` | `guards/test_every_module_imports.py` |
| `test_print_schema.py` | `guards/test_the_schema_renders_and_splits_its_grain.py` |
| `projector/test_projector_protocol.py` | `guards/test_the_projector_is_a_protocol.py` |
| `test_config.py` | `guards/test_config_validates.py` |
| `api/test_no_hard_deletes.py` | `guards/test_the_surface_offers_no_erasure.py` |
| `test_property_leakage.py` | `guards/test_internal_keys_never_leak.py` |
| `evidence/test_append_only.py` | `log/test_the_log_is_append_only.py` |
| `evidence/test_total_order.py` | `log/test_the_log_is_totally_ordered.py` |
| `api/test_lineage.py` | `log/test_a_claim_cites_its_sources.py` |
| `api/test_comments.py` | `log/test_comments_are_claims.py` |
| `evidence/test_org_scoping.py` | `log/test_the_log_is_tenant_scoped.py` |
| `api/test_batch_claims.py` | `log/test_an_act_is_one_transaction.py` |
| `api/test_attest_covers_every_claim_kind.py` | `log/test_standing_is_a_claim_on_a_claim.py` |
| `evidence/test_value_column_errors.py` | `log/test_a_claim_names_its_value_kind.py` |
| `api/test_term_writes.py` | `log/test_a_write_names_a_word_not_a_view.py` |
| `evidence/test_observed_at.py` | `log/test_every_claim_has_a_time_and_a_confidence.py` |
| `evidence/test_identity.py` | `identity/test_the_organization_fold_agrees_with_the_log.py` |
| `api/test_different_from.py` | `identity/test_a_difference_vetoes_sameness.py` |
| `api/test_known_about.py` | `identity/test_the_panel_folds_over_the_component.py` |
| `projector/test_one_vertex_per_individual.py` | `identity/test_a_view_draws_one_vertex_per_individual.py` |
| `api/test_sameness_is_the_views.py` | `identity/test_the_fold_is_the_views.py` |
| `evidence/test_rule_compilation.py` | `view/test_a_definition_is_a_rule_list.py` |
| `test_edge_properties_refused.py` | `view/test_a_definition_is_refused_by_name.py` |
| `projector/test_defined_categories.py` | `view/test_a_view_admits_the_claims_its_rules_cover.py` |
| `projector/test_several_categories.py` | `view/test_a_claim_is_drawn_under_every_admitting_category.py` |
| `projector/test_existence.py` | `view/test_existence_folds_per_category.py` |
| `projector/test_relation_replay.py` | `view/test_an_edge_is_the_fold_of_its_claims.py` |
| `api/test_category_trust.py` | `view/test_trust_is_the_categorys_rule.py` |
| `projector/test_rule_evidence_filters.py` | `view/test_rule_evidence_is_the_propertys_own_rule.py` |
| `api/test_as_of.py` | `view/test_a_rule_reads_belief_time_and_world_time.py` |
| `schema/test_definitions_across_kinds.py` | `view/test_rules_on_every_claim_family.py` |
| `schema/test_versioning.py` | `view/test_every_change_to_a_view_is_a_version.py` |
| `schema/test_schema_diff.py` | `view/test_a_schema_change_costs_what_the_diff_says.py` |
| `test_definition_rbac.py` | `view/test_changing_a_view_is_rbac.py` |
| `api/test_delete_graph_is_guarded.py` | `view/test_deleting_a_view_leaves_the_log.py` |
| `test_materialize.py` | `view/test_the_definition_document_is_the_views_meaning.py` |
| `projector/test_namespace.py` | `view/test_the_namespace_is_derived_from_the_view.py` |
| `evidence/test_asserted_terms.py` | `view/test_the_asserted_terms_index_agrees_with_the_definitions.py` |
| `projector/test_draw_converges.py` | `projection/test_drawing_converges.py` |
| `projector/test_reproject_idempotent.py` | `projection/test_rebuild_equals_the_write_path.py` |
| `projector/test_incremental_replay.py` | `projection/test_incremental_replay_draws_what_is_owed.py` |
| `projector/test_watermark.py` | `projection/test_the_cursor_is_derived_from_the_outbox.py` |
| `evidence/test_state_vector.py` | `projection/test_the_state_vector_is_a_monoid.py` |
| `api/test_indexed_properties.py` | `projection/test_derived_properties_are_materialized.py` |
| `projector/test_org_wide_fanout.py` | `projection/test_a_write_reaches_every_view_that_reads_it.py` |
| `api/test_reads_do_not_compute.py` | `projection/test_reads_do_not_compute.py` |
| `projector/test_category_fk.py` | `projection/test_the_database_refuses_an_undeclared_category.py` |
| `api/test_rematerialization.py` | `projection/test_a_rule_change_redraws_what_it_owns.py` |
| `projector/test_reproject_command.py` | `projection/test_the_operator_commands_rebuild_and_redraw.py` |
| `api/test_structure_is_an_individual.py` | `datum/test_a_structure_is_an_individual.py` |
| `evidence/test_shared_structure_schema.py` | `datum/test_kinds_are_the_organizations_vocabulary.py` |
| `instance/test_metric.py` | `datum/test_a_measurement_informs_what_it_describes.py` |
| `api/test_two_surfaces.py` | `surface/test_two_surfaces_never_mix.py` |
| `api/test_write_payloads_are_claims.py` | `surface/test_a_write_returns_the_act.py` |
| `api/test_node_lists_are_claims.py` | `surface/test_a_node_names_its_view.py` |
| `api/test_edge_lists_round_trip.py` | `surface/test_edge_lists_round_trip.py` |
| `instance/test_entity_list.py` | `surface/test_claim_lists_page_filter_and_order.py` |
| `api/test_log_reads.py` | `surface/test_the_log_is_readable.py` |
| `api/test_interface_fragments.py` | `surface/test_interface_fields_resolve_fragments.py` |
| `schema/test_entity_category.py` | `surface/test_categories_and_views_are_listable.py` |
| `api/test_loaders.py` | `surface/test_loaders_are_per_request.py` |
| `api/test_reads_are_tenant_scoped.py` | `surface/test_reads_are_tenant_scoped.py` |
| `api/test_rich_property.py` | `surface/test_a_property_can_explain_itself.py` |
| `api/test_term_surface.py` | `surface/test_the_vocabulary_is_navigable.py` |
| `api/test_archiving_persists.py` | `product/test_product_state_is_inert.py` |
| `insights/test_saved_query_mutations.py` | `product/test_a_saved_query_is_a_plan.py` |
| `test_s3.py` | `product/test_uploads_reach_the_object_store.py` |
| `claims.py`, `writes.py`, `drawing.py`, `rules.py`, `namespaces.py` | `support/` |

The other forty-five modules were split by property and merged into the targets above; the
commit `test: split and merge the remaining modules into the model's layers` lists every
source by target.

## Open

Two columns the model leaves undecided are recorded here rather than tested:

- **`Link.role`** is a free string on a participation claim. Whether a role is a word (A4) or
  a property of the claim is open; `test_an_edge_is_the_fold_of_its_claims` pins only that the
  role the claim states is the role the edge carries.
- **`Comment`'s columns.** A comment is a claim about a structure (A3), and its `text`,
  `parent`, `mentions` and `descendants` columns are lok's shape carried over. Whether a reply's
  `parent` should be a `DERIVED_FROM`-style link rather than a column, and whether `descendants`
  (a cache) belongs on a log row at all, is open; `log/test_comments_are_claims` holds what the
  columns do today.
