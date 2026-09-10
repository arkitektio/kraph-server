"""Refusals the schema mutations share.

Two kinds, both turning a silent or cryptic failure into an instruction:
deleting schema that evidence still depends on, and declaring schema the
projector will never compute.

## Deleting what evidence depends on

Every foreign key from the evidence base into `core.Category` or into the
organization's vocabulary is `PROTECT`. They used to be `CASCADE`, which meant
deleting one graph's entity category destroyed organization-scoped `Instance` rows
that other projections were built from — the append-only guarantee undone from
the one direction nothing was watching.

`PROTECT` turns that into a database error, which is the right outcome but the
wrong message: Django's `ProtectedError` names a table and a row id. These
helpers turn it into something that says what is in the way and what to do
instead, in the style the rest of the codebase uses for refusals.

## Declaring what nothing computes

`materialize.validate_derivation_rules` refuses an unsatisfiable schema before
any category exists. The single-category mutations never reach it — they take one
definition and write one row — so a rule refused in a `GraphDefinitionInput` was
accepted through `createRelationCategory`. `refuse_edge_properties` closes that
half.
"""

from django.db.models import ProtectedError


def delete_or_explain(item, *, what: str, instead: str) -> None:
    """Delete a schema row, or explain what evidence is holding it.

    `what` names the thing being deleted, `instead` the operation the caller
    probably wanted. Both end up in the message, because "protected foreign key"
    is not an instruction.
    """
    try:
        item.delete()
    except ProtectedError as error:
        blockers = list(error.protected_objects)[:5]
        detail = ", ".join(str(blocker) for blocker in blockers)
        more = "" if len(blockers) < 5 else " (and more)"
        raise ValueError(f"Cannot delete {what}: evidence still refers to it — {detail}{more}. Evidence is append-only, so the term it was recorded under has to outlive it. {instead}") from error


def refuse_edge_properties(key: str, property_definitions) -> None:
    """Refuse an edge category that declares properties. No-op when it declares none.

    Delegates the reasoning and the message to
    `materialize.edge_property_problems`, so the whole-schema path and this one
    cannot drift into refusing different things.
    """
    from graph_engine.materialize import edge_property_problems

    problems = edge_property_problems(key, property_definitions)
    if problems:
        raise ValueError("Cannot create this category:\n  - " + "\n  - ".join(problems))


def refuse_bad_color(color) -> None:
    """Refuse a colour that is not RGB or RGBA. No-op for None or empty.

    Three or four integers in [0, 255]. It was `assert len(color) in (3, 4)` at
    fifteen sites — stripped under `python -O`, and an `AssertionError` rather
    than a refusal a client can read.
    """
    if not color:
        return
    values = list(color)
    if len(values) not in (3, 4) or any(not isinstance(c, int) or isinstance(c, bool) or not 0 <= c <= 255 for c in values):
        raise ValueError(f"Color must be three or four integers in [0, 255] (RGB or RGBA), got {values!r}")
