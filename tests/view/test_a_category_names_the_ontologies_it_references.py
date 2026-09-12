"""A category records the ontology terms it was declared against (A6).

`ontologyReferences` is how a view says "my word `Mitosis` is OBI's `Mitosis`" —
a prefix and a URI. Storing it is the whole point of accepting it.

History: four of the six category mutations carried a hand-copied loop that read
`GraphOntology.objects.filter(prefix=…)` and
`OntologyReference.objects.get_or_create(graph_id=…, category_key=…)`. None of
those fields exist: `GraphOntology` has `graph / name / url / description` and
`OntologyReference` has `category / name / ontology`. So the block raised
`FieldError` the moment a reference was passed, and was dormant only because the
input defaults to an empty list and no test had ever sent one. It could not be
de-duplicated into a shared helper, because it was not code that ran — it was
replaced by `CategoryManager._apply_ontology_references`, the only implementation
that has ever executed. That helper *upserts* the ontology by prefix rather than
refusing an unknown one, and replaces the reference set whole; both are choices
this module is here to pin, since there was no prior behaviour to preserve.
"""

import pytest

from core import models as core_models
from tests.support import graphs


CREATE_ENTITY_CATEGORY = """
    mutation C($input: CreateEntityCategoryInput!) {
        createEntityCategory(input: $input) { id }
    }
"""

CREATE_NATURAL_EVENT = """
    mutation C($input: CreateNaturalEventCategoryInput!) {
        createNaturalEventCategory(input: $input) { id }
    }
"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_category_stores_the_ontology_references_it_was_given(api_schema, simple_api_context) -> None:
    graph_id = await graphs.graph_declaring(api_schema, simple_api_context, "Cell", name="ontology-refs")

    made = await api_schema.execute(
        CREATE_ENTITY_CATEGORY,
        variable_values={"input": {"graph": graph_id, "key": "Neuron", "ontologyReferences": [{"prefix": "OBI", "uri": "http://purl.obolibrary.org/obo/CL_0000540"}]}},
        context_value=simple_api_context,
    )
    assert made.errors is None, f"GraphQL errors: {made.errors}"

    category_id = made.data["createEntityCategory"]["id"]
    stored = [reference async for reference in core_models.OntologyReference.objects.filter(category_id=category_id)]
    assert len(stored) == 1, "the reference the category was declared with is stored against it"
    assert stored[0].name == "http://purl.obolibrary.org/obo/CL_0000540"

    ontology = await core_models.GraphOntology.objects.aget(pk=stored[0].ontology_id)
    assert ontology.name == "OBI", "the prefix names the ontology the reference belongs to"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_declaring_a_category_again_replaces_its_references(api_schema, simple_api_context) -> None:
    """The reference set is replaced whole, not merged.

    `createEntityCategory` is an upsert on `(graph, key)`, so a second call is the
    same declaration made again — and a declaration that omits a reference is
    saying the category no longer carries it.
    """
    graph_id = await graphs.graph_declaring(api_schema, simple_api_context, "Cell", name="ontology-refs-again")

    first = await api_schema.execute(
        CREATE_ENTITY_CATEGORY,
        variable_values={"input": {"graph": graph_id, "key": "Neuron", "ontologyReferences": [{"prefix": "OBI", "uri": "http://purl.obolibrary.org/obo/CL_0000540"}, {"prefix": "CL", "uri": "http://purl.obolibrary.org/obo/CL_0000000"}]}},
        context_value=simple_api_context,
    )
    assert first.errors is None, f"GraphQL errors: {first.errors}"

    second = await api_schema.execute(
        CREATE_ENTITY_CATEGORY,
        variable_values={"input": {"graph": graph_id, "key": "Neuron", "ontologyReferences": [{"prefix": "OBI", "uri": "http://purl.obolibrary.org/obo/CL_0000540"}]}},
        context_value=simple_api_context,
    )
    assert second.errors is None, f"GraphQL errors: {second.errors}"

    category_id = second.data["createEntityCategory"]["id"]
    stored = [reference.name async for reference in core_models.OntologyReference.objects.filter(category_id=category_id)]
    assert stored == ["http://purl.obolibrary.org/obo/CL_0000540"], "the second declaration is the whole truth about this category's references"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_every_category_family_records_its_references_the_same_way(api_schema, simple_api_context) -> None:
    """An entity category and an event category store a reference alike.

    This is the assertion that separates the two creation paths. `createEntityCategory`
    goes through `EntityCategoryManager`, which reaches
    `CategoryManager._apply_ontology_references` and works. The event, relation and
    structure-relation mutations carried their own hand-copied loop over field names
    that do not exist, so the same input raised `FieldError` there. One category
    family quietly supporting a feature the others cannot is what having two
    creation paths for one row costs.
    """
    graph_id = await graphs.graph_declaring(api_schema, simple_api_context, "Cell", name="ontology-refs-every-family")
    reference = [{"prefix": "OBI", "uri": "http://purl.obolibrary.org/obo/OBI_0000070"}]

    entity = await api_schema.execute(
        CREATE_ENTITY_CATEGORY,
        variable_values={"input": {"graph": graph_id, "key": "Neuron", "ontologyReferences": reference}},
        context_value=simple_api_context,
    )
    assert entity.errors is None, f"GraphQL errors: {entity.errors}"

    event = await api_schema.execute(
        CREATE_NATURAL_EVENT,
        variable_values={"input": {"graph": graph_id, "key": "Mitosis", "kind": "INTRINSIC", "inputs": [], "outputs": [], "ontologyReferences": reference}},
        context_value=simple_api_context,
    )
    assert event.errors is None, f"GraphQL errors: {event.errors}"

    for category_id in (entity.data["createEntityCategory"]["id"], event.data["createNaturalEventCategory"]["id"]):
        stored = [row.name async for row in core_models.OntologyReference.objects.filter(category_id=category_id)]
        assert stored == ["http://purl.obolibrary.org/obo/OBI_0000070"], f"category {category_id} stores the reference it was declared with"
