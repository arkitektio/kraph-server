"""Only filterable properties are materialized.

The indexability argument holds for properties you *filter or sort on*: Cypher
compares against stored node properties, so `e.length > 40` needs `length` on the
node. It does not hold for the rest, and the rest is most of a schema — a value
read after a node has already been selected can be computed on demand.

So `index` becomes load-bearing. `index: true` projects the property onto the
node; everything else is derived on read from the state vector. Adding a
non-indexed property is then genuinely O(1): no backfill, no projection write,
and nothing that can go stale, because nothing was stored.

The trade is that a non-indexed property cannot be filtered on — and saying so is
the point. A Cypher predicate against a property that is not on the node matches
nothing, and "no results" is indistinguishable from "nothing satisfies this".
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
    from evidence import models as evidence_models
    from evidence import state as state_module
    from evidence import writer

    organization = test_graph.organization
    assertion = writer.create_assertion(organization, subject="tester", app_id="pytest")
    roi = core_models.StructureCategory.objects.create(graph=test_graph, key="ROI", identifier="ROI", age_name="roi_idx")
    metric_category = core_models.MetricCategory.objects.create(graph=test_graph, structure_category=roi, key="vector_length", age_name="vl_idx")

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
def test_only_the_indexed_property_is_projected(
    test_graph: core_models.Graph,
    category_with_both: core_models.EntityCategory,
    measured_ref: str,
) -> None:
    """Both properties compute; only the indexed one is written to the graph.

    Asserted against real derived values, not against empty dicts. An earlier
    version of this test ran with no evidence and ended up asserting `{} == {}`
    — the same vacuous-pass shape this whole transition has been removing.
    """
    everything = projector.derive_properties(test_graph, measured_ref, category_with_both)
    indexed = projector.derive_properties(test_graph, measured_ref, category_with_both, indexed_only=True)

    assert everything == {"indexed_length": pytest.approx(20.0), "quiet_length": pytest.approx(30.0)}, "Both properties must derive: MEAN of 10 and 30 is 20, MAX is 30"
    assert indexed == {"indexed_length": pytest.approx(20.0)}, "Only the indexed property reaches the graph"


@pytest.mark.django_db(transaction=True)
def test_the_split_is_computed_in_one_pass(
    test_graph: core_models.Graph,
    category_with_both: core_models.EntityCategory,
    measured_ref: str,
) -> None:
    """`split_properties` returns both halves without deriving twice."""
    indexed, on_read = projector.split_properties(test_graph, measured_ref, category_with_both)

    assert indexed == {"indexed_length": pytest.approx(20.0)}
    assert on_read == {"quiet_length": pytest.approx(30.0)}
    assert not set(indexed) & set(on_read), "A property belongs to exactly one half"


@pytest.mark.django_db(transaction=True)
def test_filtering_a_non_indexed_property_is_an_error(
    test_graph: core_models.Graph,
    category_with_both: core_models.EntityCategory,
    age_engine,
) -> None:
    """Not silently zero results, which would read as 'nothing matches'."""
    from graph_engine import input_models

    controller = GraphController(engine=age_engine)

    with pytest.raises(ValueError, match="not an indexed property"):
        controller.list_entities_for_category(
            category_with_both,
            filters=input_models.EntityFilters(has_property="quiet_length"),
        )


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
def test_sorting_a_non_indexed_property_is_an_error(
    test_graph: core_models.Graph,
    category_with_both: core_models.EntityCategory,
    age_engine,
) -> None:
    """Ordering has the same constraint as filtering, for the same reason."""
    from graph_engine import input_models

    controller = GraphController(engine=age_engine)

    with pytest.raises(ValueError, match="not an indexed property"):
        controller.list_entities_for_category(
            category_with_both,
            ordering=[input_models.EntityOrder(property=input_models.PropertyOrder(key="quiet_length", direction="ASC"))],
        )


@pytest.mark.django_db(transaction=True)
def test_a_non_derived_property_stays_filterable(test_graph: core_models.Graph) -> None:
    """The split applies to derived properties only.

    A property set directly is always on the node, so marking it `index` would be
    meaningless — and refusing to filter on it would be a regression.
    """
    category = core_models.EntityCategory.objects.create(
        graph=test_graph,
        key="Direct",
        age_name="direct",
        property_definitions=[{"key": "nickname", "value_kind": "STRING", "derivation": "LATEST"}, {"key": "plain", "value_kind": "STRING"}],
    )

    controller = GraphController(engine=None)
    assert "plain" in controller.indexed_property_keys(category)


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
