"""Saving a query, reading it back, and changing it — for all nine kinds.

Eighteen mutations — `create*` and `update*` for graph/node/edge × table/pairs/
path — were `raise NotImplementedError` while being mounted on the root Mutation
type, so a client could call any of them and get a 500 after the request had been
accepted.

The knock-on was bigger than the mutations. `NodeTableQuery`, `NodePairsQuery`,
`NodePathQuery`, `EdgeTableQuery`, `EdgePairsQuery`, `EdgePathQuery`,
`GraphPairsQuery` and `GraphPathQuery` had **no constructor anywhere in the
codebase**, so every `*Queries` read field was mounted, documented, and could
only ever return an empty list. That is why each case here reads back through the
matching root query rather than asserting on the mutation payload alone: the
point is not that the write returns something, it is that the read stops being
empty.

Parametrised rather than nine copies, because the nine differ only in names —
which is also why one shared helper implements them.
"""

import uuid

import kante
import pytest
from kante.context import HttpContext

from core import models as core_models

#: (mutation stem, GraphQL type stem, root list field, does it carry columns)
KINDS = [
    ("GraphTableQuery", "graphTableQueries", True),
    ("GraphPairsQuery", "graphPairsQueries", False),
    ("GraphPathQuery", "graphPathQueries", False),
    ("NodeTableQuery", "nodeTableQueries", True),
    ("NodePairsQuery", "nodePairsQueries", False),
    ("NodePathQuery", "nodePathQueries", False),
    ("EdgeTableQuery", "edgeTableQueries", True),
    ("EdgePairsQuery", "edgePairsQueries", False),
    ("EdgePathQuery", "edgePathQueries", False),
]

COLUMN = {"kind": "VALUE", "key": "value", "type": "string", "valueKind": "STRING"}


@pytest.fixture
def outsider_graph(db, backend_stack, test_graph: core_models.Graph) -> core_models.Graph:
    """A graph in a tenant the requesting user is not a member of.

    Declared here rather than imported: the twin in
    `tests/api/test_schema_writes_are_authorized.py` is module-local, and a
    fixture is not reachable across test packages without a conftest.
    """
    from authentikate.models import Membership, Organization, User

    other, _ = Organization.objects.get_or_create(slug="a-rival-lab")
    stranger, _ = User.objects.get_or_create(username="stranger", sub="stranger-sub")
    membership, _ = Membership.objects.get_or_create(user=stranger, organization=other)

    return core_models.Graph.objects.create(
        name="rival_graph",
        age_name="rival_graph_a_rival_lab",
        user=stranger,
        membership=membership,
        organization=other,
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("stem,list_field,has_columns", KINDS, ids=[k[0] for k in KINDS])
async def test_a_saved_query_can_be_created_read_back_and_changed(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    stem: str,
    list_field: str,
    has_columns: bool,
) -> None:
    """Create, read, update — the whole point of the mutations existing."""
    key = f"q_{uuid.uuid4().hex[:8]}"

    payload = {
        "graph": str(test_graph.id),
        "key": key,
        "name": "First name",
        "description": "First description",
        "query": "MATCH (n) RETURN n",
    }
    if has_columns:
        payload["columnInput"] = [COLUMN]

    created = await api_schema.execute(
        f"""
        mutation Create($input: Create{stem}Input!) {{
            create{stem}(input: $input) {{ id key label description query }}
        }}
        """,
        variable_values={"input": payload},
        context_value=simple_api_context,
    )
    assert created.errors is None, f"create{stem} must work: {created.errors}"
    made = created.data[f"create{stem}"]
    assert made["key"] == key
    assert made["label"] == "First name", "The label falls back to the key only when no name was given"
    assert made["query"] == "MATCH (n) RETURN n"

    listed = await api_schema.execute(
        f"query List {{ {list_field} {{ id key }} }}",
        context_value=simple_api_context,
    )
    assert listed.errors is None, f"GraphQL errors: {listed.errors}"
    assert made["id"] in {row["id"] for row in listed.data[list_field]}, f"{list_field} could only ever return [] before there was a way to create one"

    updated = await api_schema.execute(
        f"""
        mutation Update($input: Update{stem}Input!) {{
            update{stem}(input: $input) {{ id key label description query }}
        }}
        """,
        variable_values={"input": {"id": made["id"], "name": "Second name", "query": "MATCH (m) RETURN m"}},
        context_value=simple_api_context,
    )
    assert updated.errors is None, f"update{stem} must work: {updated.errors}"
    changed = updated.data[f"update{stem}"]

    assert changed["id"] == made["id"], "An update changes the row rather than making a new one"
    assert changed["label"] == "Second name"
    assert changed["query"] == "MATCH (m) RETURN m"
    assert changed["key"] == key, "and leaves alone what was not sent"
    assert changed["description"] == "First description", "A field omitted from an update means 'unchanged', not 'blank it'"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_saved_query_defaults_its_label_to_its_key(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """`label` is non-null on the model, so a nameless query still needs one."""
    key = f"q_{uuid.uuid4().hex[:8]}"

    result = await api_schema.execute(
        """
        mutation Create($input: CreateNodePairsQueryInput!) {
            createNodePairsQuery(input: $input) { id key label }
        }
        """,
        variable_values={"input": {"graph": str(test_graph.id), "key": key, "query": "MATCH (n) RETURN n"}},
        context_value=simple_api_context,
    )

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data["createNodePairsQuery"]["label"] == key


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_saved_query_cannot_be_created_in_another_tenants_graph(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    outsider_graph: core_models.Graph,
) -> None:
    """The graph id arrives from the client, so it has to be checked.

    A saved query is executed later against the graph it names, so writing one
    into somebody else's view is a way to read their data through
    `renderGraphTable`.
    """
    result = await api_schema.execute(
        """
        mutation Create($input: CreateGraphTableQueryInput!) {
            createGraphTableQuery(input: $input) { id }
        }
        """,
        variable_values={
            "input": {
                "graph": str(outsider_graph.id),
                "key": f"q_{uuid.uuid4().hex[:8]}",
                "query": "MATCH (n) RETURN n",
                "columnInput": [COLUMN],
            }
        },
        context_value=simple_api_context,
    )

    assert result.errors, "Saving a query into another tenant's graph must be refused"
    assert not await core_models.GraphTableQuery.objects.filter(graph=outsider_graph).aexists()
