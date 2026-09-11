"""The saved-query plan: what a table query *means*, independent of who draws it.

A saved table query used to be a Cypher string the client wrote (or that the
builder wrote and handed back), stored in `GraphQuery.query` and executed
verbatim by `renderGraphTable` with a filter regex-spliced before its last
`RETURN`. That made the query language the public contract and the saved row
unusable by any projection kind but Apache AGE.

The contract is the **plan** now — this module — stored as JSON in
`GraphQuery.plan`, accepted as `TableQueryPlanInput`, returned as
`TableQueryPlan`, and compiled per projection kind
(`graph_engine/projection/table.py::compile_table_plan_sql` for the table
kind). A plan says which paths to match, which predicates to apply, which
values to return under which aliases, and how the result's columns are
described. The model's `query` column survives only on legacy rows saved as
raw Cypher before plans existed; nothing renders it any more.

`version` is stamped so a later shape can be told from this one without guessing.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field

from evidence.values import JSONValue
from graph_engine.input_models import ColumnInput, MatchPathInput, ReturnStatementInput, WhereClauseInput, WhereOperator

if TYPE_CHECKING:
    from graph_engine.projection.protocol import Projector

PLAN_VERSION = 1

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class TableQueryPlan(BaseModel):
    """One saved table query, as the organization meant it."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(default=PLAN_VERSION, description="Shape version of this plan")
    matches: list[MatchPathInput] = Field(default_factory=list, description="The paths to match; the first node of the first path is the default subject")
    wheres: list[WhereClauseInput] = Field(default_factory=list, description="Predicates over matched nodes' properties")
    returns: list[ReturnStatementInput] = Field(default_factory=list, description="What to return, each under an alias a column can name")
    columns: list[ColumnInput] = Field(default_factory=list, description="How the returned aliases are presented")

    @classmethod
    def from_stored(cls, value: Mapping[str, JSONValue] | None) -> Optional["TableQueryPlan"]:
        """The plan a row carries, or None for a legacy row that stores only Cypher."""
        if not value:
            return None
        return cls.model_validate(value)

    def to_stored(self) -> dict[str, JSONValue]:
        return self.model_dump(mode="json")


class PlanShape(Protocol):
    """The three lists a plan is built from, whatever spells them.

    Three shapes reach :func:`plan_from_input` — the saved-query input, the
    unsaved `renderTablePlan` input, and the builder's shim, which renames
    `match_paths`/`where_clauses`/`return_statements` onto these. A protocol
    says what they must agree on; `Any` said only that they need not.
    """

    matches: Sequence[MatchPathInput] | None
    wheres: Sequence[WhereClauseInput] | None
    returns: Sequence[ReturnStatementInput] | None


def plan_from_input(plan_input: PlanShape, columns: Sequence[ColumnInput] | None, projector: "Projector | None" = None) -> TableQueryPlan:
    """A validated plan from a client's input, with the columns folded in.

    Validated once, against nothing, so a plan that cannot be compiled is
    refused at save time — or, for an unsaved render, before anything runs.
    Through the bound projector unless one is passed: the projection kind is
    the seam, and validation is part of it. Lives here rather than in the
    mutations package because the ad-hoc read (`renderTablePlan`) needs it too,
    and a query must not import from mutations.
    """
    plan = TableQueryPlan(
        matches=list(plan_input.matches or []),
        wheres=list(plan_input.wheres or []),
        returns=list(plan_input.returns or []),
        columns=list(columns or []),
    )
    if projector is None:
        from graph_engine.projection.context import current_or_default

        projector = current_or_default()
    projector.validate_plan(plan)
    return plan


def sanitize_identifier(value: str, fallback: str) -> str:
    """A Cypher/SQL-safe identifier derived from a user-supplied name, or `fallback`."""
    sanitized = re.sub(r"[^A-Za-z0-9_]", "_", str(value))
    if not sanitized:
        sanitized = fallback
    if not re.match(r"^[A-Za-z_]", sanitized):
        sanitized = f"n_{sanitized}"
    return sanitized


def is_identifier(value: str) -> bool:
    return bool(_IDENTIFIER.match(str(value)))


__all__ = ["PLAN_VERSION", "TableQueryPlan", "WhereOperator", "is_identifier", "sanitize_identifier"]
