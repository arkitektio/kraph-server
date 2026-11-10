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
from graph_engine.input_models import ColumnInput, MatchPathInput, PairEndInput, PairsQueryPlanInput, ReturnStatementInput, WhereClauseInput, WhereOperator

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


#: The aliases a pairs plan lowers its two ends to. `id` is the vertex's ref; `identifier`
#: and `object` are what a drawn structure carries (RFC 0027), null on a drawn instance.
PAIR_ALIASES = ("source_ref", "source_identifier", "source_object", "target_ref", "target_identifier", "target_object")


class PairsQueryPlan(BaseModel):
    """One saved pairs query: a match over a view's drawing, and which two of its nodes are the pair.

    It is a table query with fixed returns, and compiles as one: :meth:`to_table_plan`
    lowers it, so the same compiler, validation and cost bound apply.
    """

    model_config = ConfigDict(extra="forbid")

    version: int = Field(default=PLAN_VERSION, description="Shape version of this plan")
    matches: list[MatchPathInput] = Field(default_factory=list, description="The paths to match")
    wheres: list[WhereClauseInput] = Field(default_factory=list, description="Predicates over matched nodes' properties")
    source: PairEndInput = Field(..., description="The node every pair starts from")
    target: PairEndInput = Field(..., description="The node every pair ends at")

    @classmethod
    def from_stored(cls, value: Mapping[str, JSONValue] | None) -> Optional["PairsQueryPlan"]:
        """The plan a row carries, or None when it carries none."""
        if not value:
            return None
        return cls.model_validate(value)

    def to_stored(self) -> dict[str, JSONValue]:
        return self.model_dump(mode="json")

    def to_table_plan(self) -> TableQueryPlan:
        """The table plan returning both ends' ref, identifier and object."""
        returns: list[ReturnStatementInput] = []
        for side, end in (("source", self.source), ("target", self.target)):
            for prop, alias in (("id", f"{side}_ref"), ("identifier", f"{side}_identifier"), ("object", f"{side}_object")):
                returns.append(ReturnStatementInput(path=end.path, node=end.node, property=prop, alias=alias))
        return TableQueryPlan(matches=list(self.matches), wheres=list(self.wheres), returns=returns)

    def end_category(self, end: PairEndInput) -> str | None:
        """The vertex label the plan constrains one end to, if it does."""
        for index, path in enumerate(self.matches):
            if (path.title or f"path_{index}") != end.path:
                continue
            categories = list(path.node_categories or [])
            for position, node in enumerate(path.nodes):
                if str(node) == end.node and position < len(categories):
                    return categories[position]
        return None


def pairs_plan_from_input(plan_input: PairsQueryPlanInput, projector: "Projector | None" = None) -> PairsQueryPlan:
    """A validated pairs plan from a client's input: refused at save time if its lowering cannot compile."""
    plan = PairsQueryPlan(matches=list(plan_input.matches), wheres=list(plan_input.wheres or []), source=plan_input.source, target=plan_input.target)
    if projector is None:
        from graph_engine.projection.context import current_or_default

        projector = current_or_default()
    projector.validate_plan(plan.to_table_plan())
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


__all__ = ["PAIR_ALIASES", "PLAN_VERSION", "PairsQueryPlan", "TableQueryPlan", "WhereOperator", "is_identifier", "pairs_plan_from_input", "sanitize_identifier"]
