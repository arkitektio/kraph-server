"""Derived properties are deliberately dark between M1 and M3.

Metrics moved out of Apache AGE into Postgres, so the rollup Cypher that used to
compute derived entity properties (`MATCH (m:Metric)-[:DESCRIBES]->(s)`) now
matches nothing. The dangerous version of that is silence: writing `null` over
every derived property, where a null is indistinguishable from "no evidence yet"
and the breakage stays invisible until somebody notices their numbers are gone.

So the gap is loud instead. This test is the tripwire that keeps it loud, and it
is written to fail once M3 lands — at which point the correct action is to delete
this file, not to loosen it.

Nothing that previously worked was lost here. `create_metric` never re-derived,
`link_structure_to_entity` raised a `NameError` before reaching derivation, and
relations never executed at all.
"""

import pytest

from graph_engine.controller import GraphController
from graph_engine.engine.testing.mock_cypher_engine import MockCypherEngine


def test_recalculate_entity_raises_rather_than_writing_nulls(mock_engine: MockCypherEngine) -> None:
    """The gap must announce itself."""
    controller = GraphController(engine=mock_engine)

    with pytest.raises(NotImplementedError) as excinfo:
        controller._recalculate_entity(entity_category=None, local_id=1)

    assert "M3" in str(excinfo.value), "The error must say where the replacement lands"


def test_recalculate_entity_writes_nothing(mock_engine: MockCypherEngine) -> None:
    """Raising early matters: a partial write would leave half-derived entities.

    If the raise were moved below the per-property loop, some properties would be
    written and the rest silently skipped — worse than either extreme.
    """
    controller = GraphController(engine=mock_engine)

    with pytest.raises(NotImplementedError):
        controller._recalculate_entity(entity_category=None, local_id=1)

    assert mock_engine.query_log == [], "Derivation must not touch the graph at all"


def test_creating_an_entity_still_works(mock_engine: MockCypherEngine) -> None:
    """The gap is scoped to derived *values*, not to entity creation.

    `_stamp_projection` keeps writing the three facts that need no derivation —
    schema version, derivation timestamp, lifecycle state — so entities are still
    creatable and identifiable while their derived properties wait for M3.
    """
    assert hasattr(GraphController, "_stamp_projection")
    assert hasattr(GraphController, "_lifecycle_state_for_entity")
