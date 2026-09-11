"""A category created one at a time keeps the rule it was declared with (A6, RFC 0009).

`createEntityCategory`, `createRelationCategory` and the two event mutations all
take a `definition` — the union of clauses that decides which claims the category
admits. Accepting one and storing nothing is worse than refusing it: the caller is
told the view means something it does not mean, and every fold afterwards answers
for the primitive category instead.

History: `create_natural_event_category` built its `defaults` dict by hand and
left `definition` out of it, while its twin `create_protocol_event_category` —
115 diff lines away over a 136-line file, otherwise the same module — included it.
Neither module could see the other, so the omission read as a difference between
event kinds rather than as the copy-paste slip it was. Both go through one creator
now; this module is what holds them together.
"""

import pytest

from core import models as core_models
from tests.support import graphs, rules


CREATE_NATURAL_EVENT = """
    mutation C($input: CreateNaturalEventCategoryInput!) {
        createNaturalEventCategory(input: $input) { id definition { rules { when { field operator value } } } }
    }
"""

CREATE_PROTOCOL_EVENT = """
    mutation C($input: CreateProtocolEventCategoryInput!) {
        createProtocolEventCategory(input: $input) { id definition { rules { when { field operator value } } } }
    }
"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_natural_event_category_keeps_the_rule_it_was_created_with(api_schema, simple_api_context) -> None:
    """The rule reaches the row, not just the payload."""
    graph_id = await graphs.graph_declaring(api_schema, simple_api_context, "Cell", name="natural-event-rule")

    definition = rules.definition(rules.rule(rules.word("Mitosis"), rules.by("curator")))
    made = await api_schema.execute(
        CREATE_NATURAL_EVENT,
        variable_values={"input": {"graph": graph_id, "key": "Mitosis", "kind": "EXTRINSIC", "inputs": [], "outputs": [], "definition": definition}},
        context_value=simple_api_context,
    )
    assert made.errors is None, f"GraphQL errors: {made.errors}"

    read_back = made.data["createNaturalEventCategory"]["definition"]["rules"][0]["when"]
    assert {"field": "SUBJECT", "operator": "IS", "value": "curator"} in read_back, "the rule the category was declared with is the rule it reports"

    category = await core_models.NaturalEventCategory.objects.aget(pk=made.data["createNaturalEventCategory"]["id"])
    assert category.definition, "a category that reports a rule has one stored; an empty `definition` is a primitive category"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_both_event_kinds_store_their_rule_the_same_way(api_schema, simple_api_context) -> None:
    """Natural and protocol events differ in what they *are*, not in what a create stores.

    The two mutations were separate copies of one module, so a field present in one
    and absent from the other was invisible. Asserting them side by side is what
    makes that kind of divergence fail rather than merely exist.
    """
    graph_id = await graphs.graph_declaring(api_schema, simple_api_context, "Cell", name="both-event-kinds")
    definition = rules.definition(rules.rule(rules.word("Staining"), rules.by("curator")))

    natural = await api_schema.execute(
        CREATE_NATURAL_EVENT,
        variable_values={"input": {"graph": graph_id, "key": "Drying", "kind": "EXTRINSIC", "inputs": [], "outputs": [], "definition": rules.definition(rules.rule(rules.word("Drying"), rules.by("curator")))}},
        context_value=simple_api_context,
    )
    assert natural.errors is None, f"GraphQL errors: {natural.errors}"

    protocol = await api_schema.execute(
        CREATE_PROTOCOL_EVENT,
        variable_values={"input": {"graph": graph_id, "key": "Staining", "protocol": "staining-v1", "kind": "EXTRINSIC", "inputs": [], "outputs": [], "definition": definition}},
        context_value=simple_api_context,
    )
    assert protocol.errors is None, f"GraphQL errors: {protocol.errors}"

    natural_row = await core_models.NaturalEventCategory.objects.aget(pk=natural.data["createNaturalEventCategory"]["id"])
    protocol_row = await core_models.ProtocolEventCategory.objects.aget(pk=protocol.data["createProtocolEventCategory"]["id"])

    assert bool(natural_row.definition) == bool(protocol_row.definition), "both event kinds store a declared rule, or neither does"
