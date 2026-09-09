"""A read is a graph query; nothing it returns is folded at query time (A7).

"Did not compute" is a negative, so these tests destroy the fold's inputs and
read again: delete every `State` row and a read that computes has nothing left
to compute from, while a read that traverses is untouched. Each case carries
its control — after the same deletion a redraw must *lose* the value.
"""

import uuid

import kante
import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext

from core import models as core_models
from tests.support import writes

ENTITY = """
    query Entity($id: ID!, $graph: ID!) {
        node(id: $id, graph: $graph) {
            ... on Entity {
                id
                properties
                richProperties { key value nEvidence spread measuredFrom measuredTo }
            }
        }
    }
"""


async def _node(api_schema: kante.Schema, ctx: HttpContext, entity_id: str, graph) -> dict:
    result = await api_schema.execute(ENTITY, variable_values={"id": entity_id, "graph": str(graph.id)}, context_value=ctx)
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    return result.data["node"]


async def _measured_ais(api_schema: kante.Schema, ctx: HttpContext, values: tuple[float, ...]) -> str:
    """An `AIS` drawn into the projection, with `values` measured behind it."""
    created = await api_schema.execute(
        writes.ASSERT_ENTITY_EXISTS,
        variable_values={
            "input": {
                "term": "AIS",
                "supportingEvidence": [
                    {
                        "identifier": "ROI",
                        "object": f"roi_{uuid.uuid4().hex[:8]}",
                        "metrics": [{"key": "vector_length", "value": value, "valueKind": "FLOAT"} for value in values],
                    }
                ],
            }
        },
        context_value=ctx,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    return created.data["assertEntityExists"]["instance"]["id"]


@sync_to_async
def _burn_the_state(organization) -> int:
    """Delete every state vector in the organization. Returns how many went.

    Legal, unlike deleting a `Metric`: the append-only trigger covers the six log
    tables, and `State` is not one of them. That asymmetry is the point — it is
    the cache, so destroying it is exactly the experiment.
    """
    from evidence import models as evidence_models

    deleted, _ = evidence_models.State.objects.for_organization(organization).delete()
    return deleted


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_value_survives_the_destruction_of_what_derives_it(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The materialized value is the answer, not a cache in front of a fold."""
    entity_id = await _measured_ais(api_schema, simple_api_context, (40.0, 50.0))
    assert (await _node(api_schema, simple_api_context, entity_id, test_graph))["properties"]["avg_length"] == pytest.approx(45.0)

    assert await _burn_the_state(test_graph.organization) > 0, "There must have been state to destroy"

    after = (await _node(api_schema, simple_api_context, entity_id, test_graph))["properties"]
    assert after["avg_length"] == pytest.approx(45.0), "A read that returns the right number with no state to fold is a read that did not fold"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_statistics_survive_it_too(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """`nEvidence`, `spread` and the observation window are materialized as well.

    These were the last read-time computation left after the value moved: one
    `State` lookup per property per node, on a field most clients request
    alongside the value. They are statistics *about* a materialized value, so
    they ship with it.
    """
    entity_id = await _measured_ais(api_schema, simple_api_context, (40.0, 50.0))
    await _burn_the_state(test_graph.organization)

    rich = {prop["key"]: prop for prop in (await _node(api_schema, simple_api_context, entity_id, test_graph))["richProperties"]}

    assert rich["avg_length"]["nEvidence"] == 2, "Two measurements stand behind the mean"
    assert rich["avg_length"]["spread"] == pytest.approx(10.0), "50 - 40"
    assert rich["avg_length"]["measuredFrom"], "The observation window is on the vertex, not looked up"
    assert rich["avg_length"]["measuredTo"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_control_a_rematerialization_loses_the_value(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Without this, the two tests above could be passing on a deletion that did nothing.

    Same destruction, then a redraw. `derive_properties` reads `State`, so with no
    state there is nothing to derive and the sweep in `rematerialize_category`
    takes the value off the vertex. The value disappearing here is what makes its
    survival above meaningful.

    It is also the honest statement of what materialization costs: the vertex is
    now the only place the answer lives, so losing the fold's inputs is losing the
    ability to rebuild it. `refold_state` is what puts them back — the metrics
    themselves are in the log and were never touched.
    """
    from graph_engine.controller import GraphController

    entity_id = await _measured_ais(api_schema, simple_api_context, (40.0, 50.0))
    await _burn_the_state(test_graph.organization)

    @sync_to_async
    def redraw() -> None:
        from api.extensions.projection import current_or_default

        category = core_models.EntityCategory.objects.get(graph=test_graph, key="AIS")
        GraphController(projector=current_or_default()).rematerialize_category(category)

    await redraw()

    after = (await _node(api_schema, simple_api_context, entity_id, test_graph))["properties"]
    assert "avg_length" not in after, "With no state to fold, a redraw must leave no value behind — the deletion was real"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_refold_puts_it_back(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """Because the log is the source of truth and both derived layers are caches.

    `State` folds from `Metric`, the vertex folds from `State`, and neither is
    evidence. Destroying both and rebuilding them from the log alone is the same
    claim `manage.py reproject` makes, applied to the property layer.
    """
    from graph_engine.controller import GraphController

    entity_id = await _measured_ais(api_schema, simple_api_context, (40.0, 50.0))
    await _burn_the_state(test_graph.organization)

    @sync_to_async
    def refold_and_redraw() -> None:
        from api.extensions.projection import current_or_default
        from graph_engine import projector

        projector.refold_state(test_graph.organization)
        category = core_models.EntityCategory.objects.get(graph=test_graph, key="AIS")
        GraphController(projector=current_or_default()).rematerialize_category(category)

    await refold_and_redraw()

    after = (await _node(api_schema, simple_api_context, entity_id, test_graph))["properties"]
    assert after["avg_length"] == pytest.approx(45.0), "The metrics were never touched, so the whole derived stack must rebuild from them"
