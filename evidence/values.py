"""The two shapes every layer passes around, named once so no layer says `Any`.

Neither is a model and neither imports Django, on purpose: `evidence.models`,
`graph_engine.projection.protocol` (which must stay framework-neutral — it is
the seam a second projection kind implements) and the projector all need these
names, and a module they can *all* import has to sit under every one of them.

`Any` said "do not check me" at each of those sites. These say what is
actually true: a claim's value is a JSON document the reader has to narrow, and
a ref is a uuid that half the codebase carries as text because one opaque
column addresses four tables.
"""

from __future__ import annotations

import uuid

#: What a claim's stored value can be — whatever JSONB holds. A `Metric.value`
#: is a number *or* a string *or* a flag, and every fold has to decide which,
#: which is exactly the obligation `Any` used to hide.
type JSONValue = str | int | float | bool | None | list[JSONValue] | dict[str, JSONValue]

#: A claim's primary key as callers hold it: the uuid, or its text. Both are in
#: the wild because `Link.source_ref` is a CharField — it addresses four tables,
#: so it cannot be a uuid column — while every claim's own `pk` is a uuid.
type Ref = str | uuid.UUID

__all__ = ["JSONValue", "Ref"]
