"""The rich body of a comment: lok's descendant tree, validated and folded.

A comment's ``descendants`` column stores the same shape lok's komment app
renders — a tree of PARAGRAPH / LEAF / MENTION nodes — kept value-compatible so
a lok frontend can post the identical tree here when it starts using kraph for
comments. This module is the one place that shape is defined: the write path
validates against it, and the two folds below derive what the evidence row
stores beside the tree.

Two deliberate departures from lok:

- A MENTION names a **subject** — the same string ``Assertion.subject`` carries —
  not a user row. The evidence layer has no user foreign keys anywhere, and a
  comment is evidence.
- ``text`` and ``mentions`` are derived *on write* and stored, because the row is
  append-only: lok recomputed nothing (it stored ``text=""`` and set mentions
  after the fact, mutating the row), and here there is no after the fact.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from evidence.values import JSONValue


class DescendantNode(BaseModel):
    """One node of the tree. A single model rather than a union per kind.

    lok models the three kinds as separate pydantic classes under a union; the
    stored JSON is the same either way, and a union buys nothing at this layer —
    the GraphQL side (`api/types.py`) is where the kinds surface as distinct
    types, because that is where a client selects on them.
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(
        description="LEAF, MENTION or PARAGRAPH — see `core.enums.DescendantKind`"
    )
    children: list[DescendantNode] | None = Field(
        default=None, description="The children of this node. Always empty for leafs"
    )
    # LEAF
    text: str | None = Field(default=None, description="The text of a leaf")
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None
    code: bool | None = None
    # MENTION
    user: str | None = Field(
        default=None,
        description="The mentioned subject id — `Assertion.subject`'s vocabulary. Named `user` for shape-compatibility with lok's tree",
    )
    # PARAGRAPH
    size: str | None = Field(default=None, description="The size of a paragraph")


DescendantNode.model_rebuild()

_VALID_KINDS = frozenset({"LEAF", "MENTION", "PARAGRAPH"})


def validate_descendants(raw: list[dict[str, JSONValue]]) -> list[dict[str, JSONValue]]:
    """Validate a raw descendant tree and return it in stored form.

    Raises ``ValueError`` on an unknown kind or an unknown key, because a stored
    tree is forever: an append-only row cannot be repaired, so a shape nothing
    can render must be refused at the door rather than discovered in a client.
    """
    nodes = [DescendantNode.model_validate(node) for node in raw]

    def check(node: DescendantNode) -> None:
        if node.kind not in _VALID_KINDS:
            raise ValueError(
                f"Unknown descendant kind '{node.kind}'. One of: {sorted(_VALID_KINDS)}"
            )
        for child in node.children or []:
            check(child)

    for node in nodes:
        check(node)

    return [node.model_dump(exclude_none=True) for node in nodes]


def extract_mentions(descendants: list[dict[str, JSONValue]]) -> list[str]:
    """Every subject the tree mentions, in first-mention order, deduplicated."""
    seen: dict[str, None] = {}

    def walk(node: dict[str, JSONValue]) -> None:
        if node.get("kind") == "MENTION" and node.get("user"):
            seen.setdefault(str(node["user"]), None)
        for child in node.get("children") or []:
            walk(child)

    for node in descendants:
        walk(node)
    return list(seen)


def plain_text(descendants: list[dict[str, JSONValue]]) -> str:
    """The leaves of the tree, flattened to searchable text.

    Paragraphs separate their contents with newlines and mentions render as
    ``@subject`` — enough to search and to show in a notification line, never a
    substitute for rendering the tree.
    """

    def walk(node: dict[str, JSONValue]) -> str:
        kind = node.get("kind")
        if kind == "LEAF":
            return node.get("text") or ""
        if kind == "MENTION":
            return f"@{node.get('user') or ''}"
        inner = "".join(walk(child) for child in node.get("children") or [])
        return inner + "\n" if kind == "PARAGRAPH" else inner

    return "".join(walk(node) for node in descendants).strip()
