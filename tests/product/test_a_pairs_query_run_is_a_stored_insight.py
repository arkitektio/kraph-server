"""A pairs query is an insight over a view, and a run of it is the training set a model cites.

LOG -> GRAPH -> QUERY: claims pair images in the log, a view draws the pairs it admits
(RFC 0027), and a saved pairs query selects pairs from that drawing. A preview answers
live; a run stores the answer with where the drawing stood, so it stays what a model
learned from after the log moves on. A training port finds queries and runs by
`requires`; a model registered against a query gets a run of its own, and nothing a
model cites can be deleted from under it.
"""

import kante
import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext

from arkitekt_datalayer.models import BigFileStore
from core import models as core_models
from datasets import logic as datasets
from graph_engine import input_models as models
from graph_engine.materialize import materialize
from tests.support import claims, graphs, reads, writes

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

IMAGE = "@mikro/arraylens"
WORD = "GROUND_TRUTH_OF"
IMAGE_PAIRS = [
    {"key": "@kraph/source_identifier", "operator": "EQUALS", "value": IMAGE},
    {"key": "@kraph/target_identifier", "operator": "EQUALS", "value": IMAGE},
]


async def _run(schema: kante.Schema, context: HttpContext, document: str, **variables) -> dict:
    result = await schema.execute(document, variable_values=variables, context_value=context)
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data is not None
    return result.data


async def _refused(schema: kante.Schema, context: HttpContext, document: str, **variables) -> str:
    result = await schema.execute(document, variable_values=variables, context_value=context)
    assert result.errors, "expected the server to refuse"
    return str(result.errors[0])


@sync_to_async
def _view(api_context, table_projector) -> core_models.Graph:
    request = api_context.request
    ends = models.StructureDescriptorInput(identifiers=[IMAGE])
    definition = models.GraphDefinitionInput(
        system_version="1.0.0",
        extensions=models.GraphExtensionsInput(
            structures=[models.StructureDefinitionInput(key="Image", identifier=IMAGE)],
            structure_relations=[models.StructureRelationDefinitionInput(key=WORD, source=ends, target=ends)],
        ),
    )
    return materialize(definition, table_projector, user=request._user, organization=request._organization, membership=request.membership, name="training pairs")


@sync_to_async
def _pair(graph: core_models.Graph, table_projector, noisy: str, clean: str) -> int:
    """One annotator pairs two images; the view is rebuilt so its drawing is consistent. Returns the log's horizon."""
    org = graph.organization
    claims.relate_structures(org, WORD, claims.structure(org, noisy, "peter", identifier=IMAGE), claims.structure(org, clean, "peter", identifier=IMAGE), "peter")
    graphs.rebuild(graph, table_projector)
    return datasets.horizon(org)


@sync_to_async
def _plan(graph: core_models.Graph) -> dict:
    image = core_models.StructureCategory.objects.get(graph=graph, key="Image").age_name
    word = core_models.StructureRelationCategory.objects.get(graph=graph, key=WORD).age_name
    return {
        "matches": [{"title": "p", "nodes": ["noisy", "clean"], "relations": [word], "nodeCategories": [image, image]}],
        "source": {"path": "p", "node": "noisy"},
        "target": {"path": "p", "node": "clean"},
    }


@sync_to_async
def _weights(api_context) -> str:
    request = api_context.request
    return str(BigFileStore.objects.create(organization=request._organization, creator=request._user, key="weights", bucket="bigfile", populated=True).pk)


async def test_a_run_keeps_the_pairs_a_model_learned_from(api_schema, api_context, table_projector) -> None:
    graph = await _view(api_context, table_projector)
    await _pair(graph, table_projector, "noisy-1", "clean-1")
    horizon = await _pair(graph, table_projector, "noisy-2", "clean-2")

    query = (await _run(api_schema, api_context, writes.CREATE_GRAPH_PAIRS_QUERY, input={"graph": str(graph.pk), "key": "image_pairs", "plan": await _plan(graph)}))["createGraphPairsQuery"]
    assert query["descriptors"] == {"@kraph/graph": str(graph.pk), "@kraph/source_identifier": IMAGE, "@kraph/target_identifier": IMAGE}
    found = (await _run(api_schema, api_context, reads.GRAPH_PAIRS_QUERIES, filters={"requires": IMAGE_PAIRS}))["graphPairsQueries"]
    assert [row["id"] for row in found] == [query["id"]], "a port typed for image pairs is offered the query"

    preview = (await _run(api_schema, api_context, reads.RENDER_GRAPH_PAIRS, id=query["id"]))["renderGraphPairs"]
    assert [(row["sourceObject"], row["targetObject"]) for row in preview] == [("noisy-1", "clean-1"), ("noisy-2", "clean-2")]

    run = (await _run(api_schema, api_context, writes.RUN_PAIRS_QUERY, input={"query": query["id"], "name": "first"}))["runPairsQuery"]
    assert (run["nPairs"], run["asOfSeq"], run["sourceIdentifier"], run["targetIdentifier"]) == (2, horizon, IMAGE, IMAGE)
    assert [(entry["sourceObject"], entry["targetObject"]) for entry in run["entries"]] == [("noisy-1", "clean-1"), ("noisy-2", "clean-2")]
    assert [row["id"] for row in (await _run(api_schema, api_context, reads.PAIRS_QUERY_RUNS, filters={"requires": IMAGE_PAIRS}))["pairsQueryRuns"]] == [run["id"]]

    # The log moves on: the preview follows it, a model registered against the query
    # gets a run of its own, and the first run still holds what it read.
    await _pair(graph, table_projector, "noisy-3", "clean-3")
    assert len((await _run(api_schema, api_context, reads.RENDER_GRAPH_PAIRS, id=query["id"]))["renderGraphPairs"]) == 3
    model = (await _run(api_schema, api_context, writes.CREATE_MODEL, input={"name": "care", "framework": "care", "store": await _weights(api_context), "trainedOnQuery": query["id"]}))["createModel"]
    trained_on = model["trainedOn"]
    assert (trained_on["auto"], trained_on["nPairs"]) == (True, 3)
    assert model["descriptors"]["@kraph/trained_on"] == trained_on["id"]
    assert (model["descriptors"]["@kraph/query"], model["descriptors"]["@kraph/source_identifier"]) == (query["id"], IMAGE)
    assert (await sync_to_async(lambda: core_models.GraphQuery.objects.get(pk=query["id"]).runs.get(pk=run["id"]).entries.count())()) == 2

    # Nothing a model cites goes from under it.
    assert "trained on it" in await _refused(api_schema, api_context, writes.DELETE_PAIRS_QUERY_RUN, input={"id": trained_on["id"]})
    assert "run(s)" in await _refused(api_schema, api_context, writes.DELETE_GRAPH_PAIRS_QUERY, input={"id": query["id"]})
    await _run(api_schema, api_context, writes.DELETE_MODEL, input={"id": model["id"]})
    for stored in (trained_on["id"], run["id"]):
        await _run(api_schema, api_context, writes.DELETE_PAIRS_QUERY_RUN, input={"id": stored})
    await _run(api_schema, api_context, writes.DELETE_GRAPH_PAIRS_QUERY, input={"id": query["id"]})
