"""An event category's declared roles are the roles it has (A6, RFC 0006, RFC 0021).

`inputs` and `outputs` say which entity categories may take part in an event and
under what role name. They are not decoration: `graph_engine/namespace.py`
expands them into the participation edge views of the graph's property graph, and
`_role_endpoints` reads an **absent or empty list as admitting everything**. So a
category whose declared roles are stored nowhere does not merely lose a label — it
silently widens to every entity-like category in the view.

History: `create_natural_event_category` and `create_protocol_event_category`
built their `defaults` dict by hand and never wrote `source_entity_roles` or
`target_entity_roles`, so every event category created through the API had open
roles while the same category created through `materialize` had the declared ones.
Two creation paths for one row, disagreeing about what the row means.
"""

import pytest

from core import models as core_models
from tests.support import graphs


CREATE_PROTOCOL_EVENT = """
    mutation C($input: CreateProtocolEventCategoryInput!) {
        createProtocolEventCategory(input: $input) { id inputs { key role } outputs { key role } }
    }
"""

CREATE_NATURAL_EVENT = """
    mutation C($input: CreateNaturalEventCategoryInput!) {
        createNaturalEventCategory(input: $input) { id inputs { key role } outputs { key role } }
    }
"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_protocol_event_category_keeps_the_roles_it_was_created_with(api_schema, simple_api_context) -> None:
    graph_id = await graphs.graph_declaring(api_schema, simple_api_context, "Cell", name="protocol-roles")

    made = await api_schema.execute(
        CREATE_PROTOCOL_EVENT,
        variable_values={
            "input": {
                "graph": graph_id,
                "key": "Staining",
                "protocol": "staining-v1",
                "kind": "EXTRINSIC",
                "inputs": [{"key": "Cell", "role": "subject", "descriptor": {"keys": ["Cell"]}}],
                "outputs": [{"key": "Cell", "role": "stained", "descriptor": {"keys": ["Cell"]}}],
            }
        },
        context_value=simple_api_context,
    )
    assert made.errors is None, f"GraphQL errors: {made.errors}"

    payload = made.data["createProtocolEventCategory"]
    assert [role["role"] for role in payload["inputs"]] == ["subject"], "the roles a category was declared with are the roles it reports"
    assert [role["role"] for role in payload["outputs"]] == ["stained"]

    category = await core_models.ProtocolEventCategory.objects.aget(pk=payload["id"])
    assert category.source_entity_roles, "a declared input role is a stored role; an empty list admits every entity category (`namespace._role_endpoints`)"
    assert category.target_entity_roles, "and so is a declared output role"
    assert [role["role"] for role in category.source_entity_roles] == ["subject"]
    assert [role["role"] for role in category.target_entity_roles] == ["stained"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_natural_event_category_keeps_the_roles_it_was_created_with(api_schema, simple_api_context) -> None:
    """The same property, asserted for the other event kind, because the two
    mutations were copies of one module and a field could go missing from one alone."""
    graph_id = await graphs.graph_declaring(api_schema, simple_api_context, "Cell", name="natural-roles")

    made = await api_schema.execute(
        CREATE_NATURAL_EVENT,
        variable_values={
            "input": {
                "graph": graph_id,
                "key": "Mitosis",
                "kind": "INTRINSIC",
                "inputs": [{"key": "Cell", "role": "mother", "descriptor": {"keys": ["Cell"]}}],
                "outputs": [{"key": "Cell", "role": "daughter", "descriptor": {"keys": ["Cell"]}}],
            }
        },
        context_value=simple_api_context,
    )
    assert made.errors is None, f"GraphQL errors: {made.errors}"

    category = await core_models.NaturalEventCategory.objects.aget(pk=made.data["createNaturalEventCategory"]["id"])
    assert [role["role"] for role in category.source_entity_roles] == ["mother"]
    assert [role["role"] for role in category.target_entity_roles] == ["daughter"]
