"""Terse builders for the RFC 0010 rule language, for tests.

One dict shape serves all three contexts — GraphQL variables, pydantic
validation (`CategoryDefinitionInput.model_validate`), and the stored JSON —
because the field names are identical in all of them. Datetimes are emitted as
ISO strings, which every context accepts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def condition(field: str, operator: str, value: Any) -> dict:
    return {"field": field, "operator": operator, "value": _iso(value)}


def word(*words: str) -> dict:
    return condition("WORD", "IS", words[0]) if len(words) == 1 else condition("WORD", "IN", list(words))


def by(*subjects: str) -> dict:
    return condition("SUBJECT", "IS", subjects[0]) if len(subjects) == 1 else condition("SUBJECT", "IN", list(subjects))


def not_by(*subjects: str) -> dict:
    return condition("SUBJECT", "NOT_IN", list(subjects))


def via(*apps: str) -> dict:
    return condition("APP", "IS", apps[0]) if len(apps) == 1 else condition("APP", "IN", list(apps))


def by_action(*names: str) -> dict:
    return condition("ACTION", "IS", names[0]) if len(names) == 1 else condition("ACTION", "IN", list(names))


def before(moment: Any) -> dict:
    return condition("ASSERTED_AT", "BEFORE", moment)


def since(moment: Any) -> dict:
    return condition("ASSERTED_AT", "SINCE", moment)


def measured_before(moment: Any) -> dict:
    return condition("MEASURED_AT", "BEFORE", moment)


def measured_since(moment: Any) -> dict:
    return condition("MEASURED_AT", "SINCE", moment)


def key(*keys: str) -> dict:
    """The metric key — measurement rules only (RFC 0014)."""
    return condition("KEY", "IS", keys[0]) if len(keys) == 1 else condition("KEY", "IN", list(keys))


def not_key(*keys: str) -> dict:
    return condition("KEY", "NOT_IN", list(keys))


def rule(*conditions: dict, unless: list[list[dict]] | None = None) -> dict:
    built: dict = {"when": list(conditions)}
    if unless:
        built["unless"] = [{"when": list(group)} for group in unless]
    return built


def definition(*rules: dict) -> dict:
    """A definition: a claim counts when any rule matches."""
    return {"rules": list(rules)}


def evidence(*rules: dict) -> dict:
    """A property's `rule.evidence`: the same rule list, minus WORD and KIND (RFC 0014)."""
    return {"rules": list(rules)}


def of_kind(*kinds: str) -> dict:
    """This rule covers only these claim kinds."""
    return condition("KIND", "IS", kinds[0]) if len(kinds) == 1 else condition("KIND", "IN", list(kinds))


def not_kind(*kinds: str) -> dict:
    """This rule covers everything but these claim kinds."""
    return condition("KIND", "NOT_IN", list(kinds))
