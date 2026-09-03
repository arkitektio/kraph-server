# RFC 0013 — Graph access rules are gone; schema changes are RBAC

- **Status:** Implemented.
- **Question:** `Graph.rules` was a per-action allow/deny list
  (`AUTO_ADD_STRUCTURES`, `CREATE_BUILDER_ARG`, ...) evaluated against request
  context. Its role/scope filters had been dead since RFC 0009 stripped them,
  and most actions were checked nowhere. The user: "remove graph rules (the
  access rules), admins and the owner of a graph can change its definition
  (it's RBAC)."
- **What was done:** The rule list is removed. Who may change a graph's
  definition is now a fixed check: the graph's owner, a member with the
  "admin" role in the graph's organization, or a superuser.

## Changes

- Removed: `Graph.rules` (column, migration `core/0018`), `rules_model`,
  `can_perform_action`, `validate_action_allowed`, `can_auto_add_structures`
  and the dead `allow_*` properties; the `Action` enum, `ActionRuleInput`, and
  `GraphDefinitionInput.rules`; `validate_graph_actions` and the `actions`
  argument of `get_accessible_graph`. The `CREATE_BUILDER_ARG` check on the
  saved-query builder went with it — saved queries are tenancy-scoped like the
  other insights.
- Added: `Graph.validate_definition_editable(info)` in `core/models.py`, and
  two wrappers in `api/mutations/_scoped.py` (`schema_graph`, `schema_scoped`)
  used by every category create, update and delete mutation across all six
  families. Tenancy is checked first, then owner-or-admin.
- "Admin" means the request's membership in the graph's organization carries
  the role `"admin"` (`Membership.roles`). An admin of another organization is
  refused; tenancy would have refused them anyway, but the guard does not rely
  on that.
- Reads and instance writes are unchanged: organization-scoped, as before.
  Renaming, pinning and archiving a graph keep their existing checks
  (archiving stays owner-or-superuser, since it precedes deletion).
- Migration `core/0005` used to import `ActionRuleInput` at migrate time; its
  key set is now frozen inline so history stays replayable.

## Tests

`tests/test_definition_rbac.py`: owner passes end to end, a plain colleague is
refused with a message naming the requirement, an organization admin passes, an
admin of another organization does not, a superuser does, and the `rules` key
is no longer accepted by `createGraph`.
