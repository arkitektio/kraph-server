"""What a test may share: helpers, never state.

`claims` writes evidence rows the way the controller does (named subjects,
back-dated acts); `writes` and `reads` go through GraphQL; `drawing` reads a
view's drawing; `graphs` builds views and rebuilds them; `rules` spells the rule
language; `namespaces` reads the per-graph schema. A test module imports from
here and from nowhere else under `tests/`.
"""
