"""Every derived property is materialized, so every one is filterable.

This file used to assert the opposite: that only `index=True` properties reached
the graph and the rest were folded from the state vector on read. That split made
adding a property free, and made reads expensive in a way that grew with the
result set — `index` defaults to `False`, so for N entities and P properties a
read was N × (1 + 3P) Postgres round-trips, or more where a selector forced a
metric scan.

The rule now: a graph is rules plus the log, materialized by an event, and a read
is a graph query. Everything a client can ask for is on the vertex before the
query runs. `index` no longer decides what is stored — nothing ever built an
Apache AGE index from it, so it decided only whether a property was materialized
at all.

The trade, stated plainly: adding a property is no longer free. It requires a
rematerialization. Reads become traversals; schema changes get more expensive.
"""

import pytest

from core import models as core_models
from graph_engine import projector
from graph_engine.controller import GraphController

INDEXED = {"key": "indexed_length", "value_kind": "FLOAT", "derivation": "ROLLUP", "index": True, "rule": {"source_node": "ROI", "key": "vector_length", "aggregation": "MEAN"}}
NOT_INDEXED = {"key": "quiet_length", "value_kind": "FLOAT", "derivation": "ROLLUP", "rule": {"source_node": "ROI", "key": "vector_length", "aggregation": "MAX"}}


@pytest.fixture
def category_with_both(test_graph: core_models.Graph) -> core_models.EntityCategory:
    """One indexed derived property and one not."""
    return core_models.EntityCategory.objects.create(
        graph=test_graph,
        key="Mixed",
        age_name="mixed",
        property_definitions=[INDEXED, NOT_INDEXED],
    )


@pytest.fixture
def measured_ref(test_graph: core_models.Graph, category_with_both: core_models.EntityCategory) -> str:
    """An entity ref with real measurements behind it.

    Both declared properties read the same metric key through different
    aggregations — MEAN for the indexed one, MAX for the other — so a test that
    confuses them produces visibly different numbers rather than two empty dicts.
    """
    from core.enums import ValueKind
    from evidence import models as evidence_models
    from evidence import state as state_module
    from evidence import writer

    organization = test_graph.organization
    assertion = writer.create_assertion(organization, subject="tester", app_id="pytest")
    roi = writer.ensure_structure_kind(organization, "ROI")
    metric_category = writer.ensure_metric_kind(organization, roi, "vector_length", ValueKind.FLOAT)

    structure = writer.ensure_structure(organization, roi, "roi-indexed", assertion)
    ref = f"{test_graph.age_name}:11111111-0000-0000-0000-000000000001"
    writer.create_link(
        organization,
        kind=evidence_models.Link.Kind.INFORMS,
        source_ref=str(structure.pk),
        target_ref=ref,
        assertion=assertion,
    )

    for value in (10.0, 30.0):
        metric = writer.record_metric(organization, structure, metric_category, key="vector_length", value=value, assertion=assertion)
        state_module.merge(metric, [ref])

    return ref


@pytest.mark.django_db(transaction=True)
def test_every_derived_property_is_materialized(
    test_graph: core_models.Graph,
    category_with_both: core_models.EntityCategory,
    measured_ref: str,
) -> None:
    """Both properties derive, and `index` no longer decides which reach the graph.

    Asserted against real derived values, not against empty dicts. An earlier
    version of this test ran with no evidence and ended up asserting `{} == {}`
    — the same vacuous-pass shape this whole transition has been removing.
    """
    everything = projector.derive_properties(test_graph, measured_ref, category_with_both)

    assert everything == {"indexed_length": pytest.approx(20.0), "quiet_length": pytest.approx(30.0)}, "Both properties must derive: MEAN of 10 and 30 is 20, MAX is 30"
    assert not hasattr(projector, "split_properties"), "The indexed/on-read split is gone, not merely unused"


@pytest.mark.django_db(transaction=True)
def test_the_statistics_are_materialized_beside_the_value(
    test_graph: core_models.Graph,
    category_with_both: core_models.EntityCategory,
    measured_ref: str,
) -> None:
    """`n_evidence` and `spread` are statistics about a value, so they ship with it.

    `RichProperty` used to read these off the `State` row per property per node,
    which is the same read-time computation the value itself no longer does.
    """
    statistics = projector._property_statistics(test_graph, measured_ref, category_with_both)

    assert statistics[projector.statistic_key("indexed_length", "n")] == 2, "Two measurements stand behind the mean"
    assert statistics[projector.statistic_key("indexed_length", "spread")] == pytest.approx(20.0), "30 - 10"
    assert projector.statistic_key("indexed_length", "from") in statistics
    assert projector.statistic_key("indexed_length", "to") in statistics


@pytest.mark.django_db(transaction=True)
def test_a_property_without_index_is_now_filterable(
    test_graph: core_models.Graph,
    category_with_both: core_models.EntityCategory,
    age_engine,
) -> None:
    """The capability the old split cost you.

    `quiet_length` carries no `index: true`, and filtering on it used to raise.
    It is materialized like everything else now, so a Cypher predicate against it
    matches what it should.
    """
    from graph_engine import input_models

    controller = GraphController(engine=age_engine)

    results = controller.list_entities_for_category(
        category_with_both,
        filters=input_models.EntityFilters(has_property="quiet_length"),
    )
    assert results == []


@pytest.mark.django_db(transaction=True)
def test_filtering_an_indexed_property_is_allowed(
    test_graph: core_models.Graph,
    category_with_both: core_models.EntityCategory,
    age_engine,
) -> None:
    """The indexed one stays queryable, which is the whole reason to mark it."""
    from graph_engine import input_models

    controller = GraphController(engine=age_engine)

    results = controller.list_entities_for_category(
        category_with_both,
        filters=input_models.EntityFilters(has_property="indexed_length"),
    )
    assert results == []


@pytest.mark.django_db(transaction=True)
def test_sorting_a_property_without_index_is_allowed(
    test_graph: core_models.Graph,
    category_with_both: core_models.EntityCategory,
    age_engine,
) -> None:
    """Ordering gains the same capability as filtering, for the same reason."""
    from graph_engine import input_models

    controller = GraphController(engine=age_engine)

    results = controller.list_entities_for_category(
        category_with_both,
        ordering=[input_models.EntityOrder(property=input_models.PropertyOrder(key="quiet_length", direction="ASC"))],
    )
    assert results == []


@pytest.mark.django_db(transaction=True)
def test_a_rule_less_property_is_not_filterable(test_graph: core_models.Graph) -> None:
    """A property nothing writes must not be admitted to the filterable set.

    This asserted the opposite, on the reasoning that "a property set directly is
    always on the node". Nothing sets one: there is no mutation for it, `project`
    writes only derived values, and the read path resolves only derived values.
    Admitting the key let `_assert_indexed` wave through a Cypher predicate that
    could only ever match zero rows — the silent-empty-result the whole
    indexed/derived split exists to eliminate.

    `materialize` now rejects such a property outright; this covers the case
    where one reaches a `Category` row anyway, as here.
    """
    category = core_models.EntityCategory.objects.create(
        graph=test_graph,
        key="Direct",
        age_name="direct",
        property_definitions=[{"key": "nickname", "value_kind": "STRING", "derivation": "LATEST"}, {"key": "plain", "value_kind": "STRING"}],
    )

    controller = GraphController(engine=None)
    assert "plain" not in controller.indexed_property_keys(category)
    # `id` is the exception, and the only one: `create_entity` writes it onto the
    # node itself, so it is genuinely there to filter on.
    assert "id" in controller.indexed_property_keys(category)


@pytest.mark.django_db(transaction=True)
def test_materialize_refuses_a_rule_less_property(age_engine, authenticated_context) -> None:
    """Declaring an uncomputable property fails loudly, naming the fix.

    Same shape as the existing refusal of rollups over an entity source: the
    schema is unsatisfiable, so it is rejected before any category exists rather
    than producing one whose property silently never populates.
    """
    from graph_engine import input_models as models
    from graph_engine.materialize import materialize

    definition = models.GraphDefinitionInput(
        system_version="1.0.0",
        extensions=models.GraphExtensionsInput(
            entities=[
                models.EntityDefinitionInput(
                    key="Person",
                    property_definitions=[models.PropertyDefinitionInput(key="nickname", type=models.PropertyType.STRING)],
                )
            ]
        ),
    )

    request = authenticated_context.request
    with pytest.raises(ValueError, match="needs a `rule` naming a `source_node`"):
        materialize(
            definition,
            age_engine,
            user=request._user,
            organization=request._organization,
            membership=request.membership,
            name="rule_less_graph",
        )


@pytest.mark.django_db(transaction=True)
def test_an_unknown_sort_direction_is_rejected(test_graph: core_models.Graph, age_engine) -> None:
    """Directions are interpolated into Cypher, so `.upper()` is not validation.

    The direction arrives from a GraphQL variable and lands in the query text.
    Anything but an exact ASC/DESC is an injection — the same hole
    `_validate_property_key` closes for keys, previously left open right beside it.
    """
    controller = GraphController(engine=age_engine)

    with pytest.raises(ValueError, match="Invalid sort direction"):
        controller._validate_direction("ASC, x DETACH DELETE n //")

    assert controller._validate_direction("asc") == "ASC"
    assert controller._validate_direction("DESC") == "DESC"
