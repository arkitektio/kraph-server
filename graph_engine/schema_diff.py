"""What work a schema change actually implies.

Until now the answer was always "recalculate everything", because there was
nothing to compare: `GraphSchema` was written exactly once per graph and every
category mutation edited rows in place. With a schema emitted per change, the
question becomes answerable — and the answer is usually "nothing".

The distinction that matters, and the reason this module exists:

- Changing a property's **aggregation** (MEAN to MAX) needs **no work at all**.
  The state vector holds sufficient statistics, not an answer, so the new
  aggregation reads the existing row. This is the case that used to trigger a
  full backfill.
- Changing a property's **source or key** needs the affected entities
  re-projected: they are now aggregating a different measurement.
- **Adding** a derived property needs projection but no re-ingest — the evidence
  is already there.
- **Removing** one needs the stale value cleared off the projection.

`jsonpatch` is a declared dependency with no prior uses; this is what it was for.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# The keys of a property definition that change *what is computed*, as opposed to
# how it is displayed or aggregated.
SOURCE_KEYS = ("source_node", "key")

# Keys that change nothing about the evidence a property reads.
COSMETIC_KEYS = ("label", "description", "color", "position_x", "position_y", "index")


@dataclass
class PropertyChange:
    """One property's before and after."""

    category_key: str
    property_key: str
    kind: str  # "added" | "removed" | "source_changed" | "aggregation_changed" | "cosmetic"
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None

    @property
    def needs_reprojection(self) -> bool:
        """Whether entities of this category must be re-derived.

        An aggregation change is deliberately absent: that is the whole point of
        holding sufficient statistics rather than a computed value.
        """
        return self.kind in {"added", "removed", "source_changed"}


@dataclass
class SchemaDiff:
    """Everything that changed between two schema versions, and what it costs."""

    changes: list[PropertyChange] = field(default_factory=list)

    @property
    def work_set(self) -> list[PropertyChange]:
        """The changes that actually require touching data."""
        return [change for change in self.changes if change.needs_reprojection]

    @property
    def categories_needing_reprojection(self) -> set[str]:
        """Which category keys have to be re-derived."""
        return {change.category_key for change in self.work_set}

    @property
    def is_free(self) -> bool:
        """True when the change costs nothing — no backfill, no reprojection."""
        return not self.work_set

    def __bool__(self) -> bool:
        return bool(self.changes)


def _properties_by_category(definition: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    """Index a definition as {category_key: {property_key: property_definition}}."""
    extensions = definition.get("extensions") or {}
    indexed: dict[str, dict[str, dict[str, Any]]] = {}

    for section, property_field in (("entities", "property_definitions"), ("relations", "properties"), ("events", "properties")):
        for item in extensions.get(section) or []:
            key = item.get("key")
            if not key:
                continue
            bucket = indexed.setdefault(key, {})
            for prop in item.get(property_field) or []:
                if prop.get("key"):
                    bucket[prop["key"]] = prop

    return indexed


def _classify(before: dict[str, Any], after: dict[str, Any]) -> str:
    """What kind of change this is, in order of increasing cost."""
    before_rule = before.get("rule") or {}
    after_rule = after.get("rule") or {}

    if any(before_rule.get(key) != after_rule.get(key) for key in SOURCE_KEYS):
        return "source_changed"
    if before.get("derivation") != after.get("derivation"):
        return "source_changed"
    if before_rule.get("aggregation") != after_rule.get("aggregation"):
        return "aggregation_changed"
    return "cosmetic"


def diff(before: dict[str, Any], after: dict[str, Any]) -> SchemaDiff:
    """Compare two graph definitions and report what work the change implies.

    Both arguments are the JSON form stored on `GraphSchema.definition`.
    """
    before_index = _properties_by_category(before)
    after_index = _properties_by_category(after)

    changes: list[PropertyChange] = []

    for category_key in sorted(set(before_index) | set(after_index)):
        before_props = before_index.get(category_key, {})
        after_props = after_index.get(category_key, {})

        for property_key in sorted(set(before_props) | set(after_props)):
            old = before_props.get(property_key)
            new = after_props.get(property_key)

            if old is None:
                changes.append(PropertyChange(category_key, property_key, "added", after=new))
            elif new is None:
                changes.append(PropertyChange(category_key, property_key, "removed", before=old))
            elif old != new:
                changes.append(PropertyChange(category_key, property_key, _classify(old, new), before=old, after=new))

    return SchemaDiff(changes=changes)


def diff_schemas(before_schema: Any, after_schema: Any) -> SchemaDiff:
    """Compare two `GraphSchema` rows."""
    return diff(before_schema.definition or {}, after_schema.definition or {})


def json_patch(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    """The raw RFC-6902 patch between two definitions.

    Useful for showing a human what changed. The structured `diff` above is what
    decides what work to do, because a patch says *where* a document changed but
    not what that means — a replaced `aggregation` and a replaced `source_node`
    are the same shape of operation and wildly different in cost.
    """
    import jsonpatch

    return list(jsonpatch.make_patch(before, after))
