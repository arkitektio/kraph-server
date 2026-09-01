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
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from graph_engine.input_models import ColumnInput, MatchPathInput, ReturnStatementInput, WhereClauseInput, WhereOperator

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
    def from_stored(cls, value: Any) -> Optional["TableQueryPlan"]:
        """The plan a row carries, or None for a legacy row that stores only Cypher."""
        if not value:
            return None
        return cls.model_validate(value)

    def to_stored(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


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
