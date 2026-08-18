"""An edge cannot carry a derived property, so declaring one is a schema error.

`projector.project_edges` writes `category_id` and `__assertion_count` onto a
relationship and stops. Measurements are not drawn as AGE edges at all — they are
read back from their `Link` rows. No derivation rule has ever run for an edge
category.

Until this guard, the API accepted such a rule, `validate_derivation_rules`
*validated* it, and it was stored in `property_definitions` — so a client got a
valid schema and a permanently empty property, with no error at any point.
(`Relation.richProperties`/`properties` have since been removed from the schema
outright, for the same structural reason: nothing ever put a derived value on an
edge for them to read.)

`bio_graph_schema` itself shipped one (`IS_CONNECTED_TO.distance`, a
`EUCLIDEAN_RANGE` rollup over `ROI.centroid`), which is how long this survived:
the fixture the whole suite runs against contained a rule nothing executed and
nothing failed.

Both surfaces are covered here, because they are separate code paths that accept
the same input. `materialize` checks a whole `GraphDefinitionInput`; the
`create_*_category` mutations take one definition at a time and never reach it.
"""

import pytest

from graph_engine import input_models as models
from graph_engine.materialize import materialize

RULE = models.DerivationRuleInput(source_node="ROI", key="centroid", aggregation=models.AggregationFunction.EUCLIDEAN_RANGE)


def _schema(extensions: models.GraphExtensionsInput) -> models.GraphDefinitionInput:
    return models.GraphDefinitionInput(system_version="1.0.0", extensions=extensions)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "extensions",
    [
        pytest.param(
            models.GraphExtensionsInput(
                entities=[models.EntityDefinitionInput(key="Cell", property_definitions=[])],
                relations=[
                    models.RelationDefinitionInput(
                        key="IS_CONNECTED_TO",
                        source=models.EntityDescriptorInput(keys=["Cell"]),
                        target=models.EntityDescriptorInput(keys=["Cell"]),
                        properties=[models.PropertyDefinitionInput(key="distance", type=models.PropertyType.FLOAT, derivation=models.DerivationType.ROLLUP, rule=RULE)],
                    )
                ],
            ),
            id="relation",
        ),
        pytest.param(
            models.GraphExtensionsInput(
                entities=[models.EntityDefinitionInput(key="Cell", property_definitions=[])],
                structure_relations=[
                    models.StructureRelationDefinitionInput(
                        key="DEPICTS",
                        source=models.StructureDescriptorInput(identifiers=["ROI"]),
                        target=models.StructureDescriptorInput(identifiers=["Mask"]),
                        properties=[models.PropertyDefinitionInput(key="overlap", type=models.PropertyType.FLOAT, derivation=models.DerivationType.ROLLUP, rule=RULE)],
                    )
                ],
            ),
            id="structure_relation",
        ),
    ],
)
def test_a_schema_declaring_edge_properties_is_refused(extensions, age_engine, authenticated_context) -> None:
    """Refused before any category exists, naming the fix.

    Same shape as the existing refusal of a rule-less node property: the schema
    is unsatisfiable, so it fails where it is declared rather than producing a
    category whose property silently never populates.
    """
    request = authenticated_context.request

    with pytest.raises(ValueError, match="an edge carries no derived properties"):
        materialize(
            _schema(extensions),
            age_engine,
            user=request._user,
            organization=request._organization,
            membership=request.membership,
            name="edge_property_graph",
        )


@pytest.mark.django_db(transaction=True)
def test_events_keep_their_properties(age_engine, authenticated_context) -> None:
    """The guard has to distinguish edges from nodes, and an event is a node.

    `NaturalEventCategory` and `ProtocolEventCategory` are `NodeCategory`
    subclasses, so `project` derives onto them exactly as it does for an entity.
    Refusing their properties along with the relations would have been the easy
    over-correction — and the suite would still have passed, since nothing else
    asserts on an event property.
    """
    request = authenticated_context.request

    graph = materialize(
        _schema(
            models.GraphExtensionsInput(
                entities=[models.EntityDefinitionInput(key="Cell", property_definitions=[])],
                events=[
                    models.EventDefinitionInput(
                        key="Mitosis",
                        kind=models.EventKind.INTRINSIC,
                        inputs=[models.EventRoleInput(key="Cell", role="a", descriptor=models.EntityDescriptorInput(keys=["Cell"]))],
                        outputs=[models.EventRoleInput(key="Cell", role="b", descriptor=models.EntityDescriptorInput(keys=["Cell"]))],
                        properties=[models.PropertyDefinitionInput(key="cell_count", type=models.PropertyType.INTEGER, derivation=models.DerivationType.ROLLUP, rule=models.DerivationRuleInput(source_node="ROI", key="cell_marker", aggregation=models.AggregationFunction.COUNT))],
                    )
                ],
            )
        ),
        age_engine,
        user=request._user,
        organization=request._organization,
        membership=request.membership,
        name="event_property_graph",
    )

    from core import models as core_models

    category = core_models.NaturalEventCategory.objects.get(graph=graph, key="Mitosis")
    assert [prop["key"] for prop in category.property_definitions] == ["cell_count"], "An event is a node; its properties materialize"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_single_category_mutation_refuses_it_too(api_schema, simple_api_context, test_graph) -> None:
    """The path that bypasses `validate_derivation_rules` entirely.

    `createRelationCategory` takes one definition and writes one row; it never
    builds a `GraphDefinitionInput`, so the whole-schema guard never sees it. A
    guard on only one of the two surfaces would just move the silent empty result
    to the other.

    Note the field name. `CreateRelationCategoryInput` extends
    `EntityDefinitionInput` and so calls it `propertyDefinitions`, where the
    structure-relation and measurement inputs call it `properties`. The resolver
    read `model.properties` and therefore raised `AttributeError` on every call —
    a mutation that had never worked, which is also why nothing noticed it was
    storing rules nothing ran.
    """
    result = await api_schema.execute(
        """
        mutation CreateRelationCategory($input: CreateRelationCategoryInput!) {
            createRelationCategory(input: $input) { id }
        }
        """,
        variable_values={
            "input": {
                "graph": str(test_graph.id),
                "key": "SITS_BESIDE",
                "propertyDefinitions": [{"key": "distance", "valueKind": "FLOAT", "derivation": "ROLLUP", "rule": {"sourceNode": "ROI", "key": "centroid", "aggregation": "EUCLIDEAN_RANGE"}}],
            }
        },
        context_value=simple_api_context,
    )

    assert result.errors, "Declaring a property on a relation must be an error, not an empty property"
    assert "an edge carries no derived properties" in str(result.errors[0])


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_creating_a_relation_category_without_properties_works(api_schema, simple_api_context, test_graph) -> None:
    """The mutation had never worked at all, so the refusal needs a control.

    Without this, `test_the_single_category_mutation_refuses_it_too` would pass
    just as well on the old `AttributeError` — an error is an error at the
    GraphQL boundary. This is the case that must now *succeed*.
    """
    result = await api_schema.execute(
        """
        mutation CreateRelationCategory($input: CreateRelationCategoryInput!) {
            createRelationCategory(input: $input) { id }
        }
        """,
        variable_values={"input": {"graph": str(test_graph.id), "key": "SITS_BESIDE"}},
        context_value=simple_api_context,
    )

    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data["createRelationCategory"]["id"]
