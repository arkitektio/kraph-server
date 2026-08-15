"""Creating and updating a saved query, for all nine kinds at once.

Nine kinds — graph, node and edge × table, pairs and path — and until now
**eighteen** of their mutations were `raise NotImplementedError`. Every one was
mounted, so a client could call `createNodeTableQuery`, have the request
accepted, and get a 500.

The knock-on was larger than the mutations themselves. `NodeTableQuery`,
`NodePairsQuery`, `NodePathQuery`, `EdgeTableQuery`, `EdgePairsQuery`,
`EdgePathQuery`, `GraphPairsQuery` and `GraphPathQuery` had **no constructor
anywhere in the codebase** — not in a manager, not in `materialize`, nowhere. So
`nodeQueries`, `edgeQueries` and every `*Queries` field beside them were mounted,
documented, and could only ever return an empty list. Implementing the writes is
what makes those reads mean anything.

One module rather than nine copies, because the three families are the same
shape: `graph`, `key`, `query`, `label`, `description`, `kind`, `columns`
(`core/models.py`, `GraphQuery` / `NodeQuery` / `EdgeQuery`). The differences are
which model, and whether the kind carries columns.

**Nothing here passes `kind`.** `managers.KindedManager` stamps it from the proxy
being used, so `models.NodeTableQuery.objects.create(...)` writes `kind="TABLE"`
by itself. That is also why `kind` was removed from the inputs: the manager sets
it with `setdefault`, so a client-supplied kind would have *won*, writing a row
that the matching manager then filtered out of every read.
"""

from typing import Any

from kante.types import Info

from api.mutations._scoped import accessible_graph, scoped


def create_saved_query(info: Info, model: Any, django_model: Any, what: str) -> Any:
    """Save a new query against the graph it names.

    `accessible_graph` before anything is written, which is the same check
    `create_entity_category` makes: the graph id arrives from the client, so
    without it a caller could save a query into another tenant's view — and a
    saved query is executed later against that view's data.
    """
    graph = accessible_graph(info, model.graph)

    values: dict[str, Any] = {
        "graph": graph,
        "key": model.key,
        "query": model.query,
        # The label is what a UI shows; falling back to the key means a query is
        # never nameless, which `label` being non-null on the model requires.
        "label": model.name or model.key,
        "description": model.description,
    }

    # Only the table kinds carry columns; pairs and path queries have no such
    # input, and writing `[]` onto them would claim an empty column set rather
    # than no column set.
    columns = getattr(model, "column_input", None)
    if columns is not None:
        values["columns"] = [column.model_dump(mode="json") for column in columns]

    return django_model.objects.create(**values)


def update_saved_query(info: Info, model: Any, django_model: Any, what: str) -> Any:
    """Change a saved query the caller is allowed to reach.

    `scoped` rather than a bare primary-key fetch, for the reason
    `api/mutations/_scoped.py` gives at length: the client names a pk and never
    names a tenant, so authorization has to come from the row.

    Patches only what was sent. Every field on the update inputs is optional
    except the id, so a `None` means "leave it alone" — assigning it would let a
    client blank a description by omitting it.
    """
    item = scoped(info, django_model, model.id, what=what)

    if model.key is not None:
        item.key = model.key
    if model.query is not None:
        item.query = model.query
    if model.name is not None:
        item.label = model.name
    if model.description is not None:
        item.description = model.description

    columns = getattr(model, "column_input", None)
    if columns is not None:
        item.columns = [column.model_dump(mode="json") for column in columns]

    item.save()
    return item
