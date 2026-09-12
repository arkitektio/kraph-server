"""The rendered schema, for tests that assert what the surface offers and what it does not."""

from __future__ import annotations

import re

from api.schema import schema


def mutation_fields() -> set[str]:
    """The field names on the root Mutation type.

    Parsed from the Mutation block rather than the whole SDL: `deleteEntity` is a
    substring of `deleteEntityCategory` and of `DeleteEntityInput`, so a
    document-wide search would pass while the mutation was still mounted.
    """
    sdl = str(schema)
    block = re.search(r"type Mutation \{(.*?)\n\}", sdl, re.S)
    assert block, "schema must expose a Mutation type"
    return set(re.findall(r"^\s+(\w+)\(", block.group(1), re.M))
