"""A view's rule admits words of its own kind, and a list never mislabels a node.

`Term` identity is `(organization, kind, key)`: "Mitosis" the natural-event word and
"Mitosis" the entity word are two terms. A definition is written on a category of
one kind, so the words it derives from are words of that kind — but
`selector.term_ids_for` and `resolve_categories` matched on the key alone, so an
`EntityCategory` defined over the word "Mitosis" admitted every *event*
classified under the event word, and `entities()` wrapped them as `Entity`. The
same defect class the label map was deleted for, reached through a constructor.
"""

import pytest
from asgiref.sync import sync_to_async

from core import models as core_models
from evidence import models as evidence_models
from core import asserted_terms
from graph_engine import projector
from tests import rules, writes

ENTITIES = """
    query($category: ID!) {
        entities(entityCategoryId: $category) { __typename id }
    }
"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_entity_category_defined_over_an_event_word_admits_no_events(api_schema, simple_api_context, test_graph: core_models.Graph) -> None:
    event_id = await writes.create_event(api_schema, simple_api_context, "Mitosis")

    @sync_to_async
    def defined_over_mitosis():
        category = core_models.EntityCategory.objects.create(graph=test_graph, key="MitoticThing", label="Mitotic thing", age_name="MitoticThing", definition=rules.definition(rules.rule(rules.word("Mitosis"))))
        admitted = projector.refs_admitted_by(category)
        return category.pk, admitted, asserted_terms.keys_and_kinds_for_graph(test_graph)

    category_pk, admitted, derived = await defined_over_mitosis()
    assert event_id not in admitted, "an entity definition must not admit an event's classification"
    assert ("Mitosis", "ENTITY") in derived and ("Mitosis", "NATURAL_EVENT") not in derived, "the derived half of the vocabulary is keyed on kind as well as key"

    listed = await api_schema.execute(ENTITIES, variable_values={"category": str(category_pk)}, context_value=simple_api_context)
    assert listed.errors is None, f"GraphQL errors: {listed.errors}"
    assert listed.data["entities"] == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_plural_lists_dispatch_on_the_claims_kind(api_schema, simple_api_context, test_graph: core_models.Graph) -> None:
    """Even if a rule admitted a node of another kind, the list would type it by its claim."""
    entity_id = await writes.create_entity(api_schema, simple_api_context, "AIS")

    @sync_to_async
    def ais_category():
        return core_models.EntityCategory.objects.get(graph=test_graph, key="AIS").pk

    listed = await api_schema.execute(ENTITIES, variable_values={"category": str(await ais_category())}, context_value=simple_api_context)
    assert listed.errors is None, f"GraphQL errors: {listed.errors}"
    assert {node["id"]: node["__typename"] for node in listed.data["entities"]}[entity_id] == "Entity"
