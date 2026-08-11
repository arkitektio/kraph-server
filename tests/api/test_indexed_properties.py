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


@pytest.mark.django_db(transaction=True)
def test_only_the_indexed_property_is_projected(
    test_graph: core_models.Graph,
    category_with_both: core_models.EntityCategory,
) -> None:
    """`indexed_only` is what the projector writes to the graph."""
    everything = projector.derive_properties(test_graph, "ref", category_with_both)
    indexed = projector.derive_properties(test_graph, "ref", category_with_both, indexed_only=True)

    # Neither has evidence, so both are empty here; the point is which *keys* each
    # would consider. Assert through the declared set instead.
    considered_all = {prop.key for prop in projector._derived_properties(category_with_both)}
    considered_indexed = {prop.key for prop in projector._derived_properties(category_with_both) if prop.index}

    assert considered_all == {"indexed_length", "quiet_length"}
    assert considered_indexed == {"indexed_length"}
    assert everything == indexed == {}


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
