"""Structures are drawn where a view mounts them, and a structure relation is an edge between them (RFC 0027).

A view mounts a structure kind (`@mikro/arraylens` as `Image`); a structure-relation
category whose ends name mounted identifiers admits claims under its word, and each
admitted claim is an edge between two structure vertices carrying `identifier` and
`object`. A structure is a vertex only where an admitted claim touches it. The write
path and a rebuild draw the same thing, a retracted endpoint takes its edge with it,
and an end naming an identifier the view does not mount is refused when it is declared.
"""

import kante
import pytest
from asgiref.sync import sync_to_async
from kante.context import HttpContext

from core import models as core_models
from graph_engine import input_models as models
from graph_engine import namespace as namespace_module
from graph_engine.materialize import materialize
from tests.support import drawing, graphs, reads, writes

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

IMAGE = "@mikro/arraylens"
ROI = "@mikro/roi"
WORD = "GROUND_TRUTH_OF"

RETRACT_STRUCTURE = """
    mutation RetractStructure($input: RetractStructureInput!) {
        retractStructure(input: $input) { __typename }
    }
"""


MOUNT = """
    mutation Mount($input: CreateStructureCategoryInput!) {
        createStructureCategory(input: $input) { id key identifier }
    }
"""

UNMOUNT = """
    mutation Unmount($input: DeleteStructureCategoryInput!) {
        deleteStructureCategory(input: $input)
    }
"""

MOUNTS = """
    query Mounts($id: ID!) {
        graph(id: $id) { structureCategories { key identifier } }
    }
"""


async def _run(schema: kante.Schema, context: HttpContext, document: str, **variables) -> dict:
    result = await schema.execute(document, variable_values=variables, context_value=context)
    assert result.errors is None, f"GraphQL errors: {result.errors}"
    assert result.data is not None
    return result.data


def _definition(*, mounts: list[tuple[str, str]], ends: list[str]) -> models.GraphDefinitionInput:
    descriptor = models.StructureDescriptorInput(identifiers=ends)
    return models.GraphDefinitionInput(
        system_version="1.0.0",
        extensions=models.GraphExtensionsInput(
            structures=[models.StructureDefinitionInput(key=key, identifier=identifier) for key, identifier in mounts],
            structure_relations=[models.StructureRelationDefinitionInput(key=WORD, source=descriptor, target=descriptor)],
        ),
    )


@sync_to_async
def _view(api_context, table_projector, *, mounts=(("Image", IMAGE),), ends=(IMAGE,)) -> core_models.Graph:
    request = api_context.request
    return materialize(
        _definition(mounts=list(mounts), ends=list(ends)),
        table_projector,
        user=request._user,
        organization=request._organization,
        membership=request.membership,
        name="training pairs",
    )


@sync_to_async
def _labels(graph: core_models.Graph) -> tuple[str, str]:
    image = core_models.StructureCategory.objects.get(graph=graph, key="Image")
    word = core_models.StructureRelationCategory.objects.get(graph=graph, key=WORD)
    return image.age_name, word.age_name


@sync_to_async
def _drawn(graph: core_models.Graph) -> tuple[dict, dict]:
    return drawing.snapshot(graph), drawing.edge_snapshot(graph)


async def test_an_admitted_claim_is_an_edge_between_two_drawn_structures(api_schema, api_context, table_projector) -> None:
    graph = await _view(api_context, table_projector)
    image, word = await _labels(graph)

    noisy = await writes.create_structure(api_schema, api_context, identifier=IMAGE, object="noisy")
    clean = await writes.create_structure(api_schema, api_context, identifier=IMAGE, object="clean")
    roi = await writes.create_structure(api_schema, api_context, identifier=ROI, object="roi")
    for source, target in ((noisy, clean), (noisy, roi)):
        await _run(api_schema, api_context, writes.ASSERT_STRUCTURE_RELATION, input={"term": WORD, "sourceId": source, "targetId": target})

    assert await sync_to_async(drawing.edge_count)(graph, word) == 1, "the ROI end is not mounted, so only the image pair is drawn"
    assert sorted(await sync_to_async(drawing.refs_with_label)(graph, image)) == sorted([noisy, clean]), "a structure is a vertex only where an admitted claim touches it"
    properties = await sync_to_async(drawing.vertex_properties)(graph, noisy)
    assert (properties["identifier"], properties["object"], properties["type"]) == (IMAGE, "noisy", "STRUCTURE")

    written = await _drawn(graph)
    await sync_to_async(graphs.rebuild)(graph, table_projector)
    assert await _drawn(graph) == written, "the write path and a rebuild draw the same thing"

    # A retracted endpoint takes its edge, and its now-untouched partner, with it.
    await _run(api_schema, api_context, RETRACT_STRUCTURE, input={"id": clean})
    assert await sync_to_async(drawing.edge_count)(graph, word) == 0
    assert await sync_to_async(drawing.refs_with_label)(graph, image) == []
    retracted = await _drawn(graph)
    await sync_to_async(graphs.rebuild)(graph, table_projector)
    assert await _drawn(graph) == retracted


async def test_an_end_naming_an_unmounted_identifier_is_refused(api_context, table_projector) -> None:
    with pytest.raises(ValueError, match="mounts no structure @mikro/roi"):
        await _view(api_context, table_projector, ends=(IMAGE, ROI))


async def test_the_namespace_carries_structure_vertices_and_their_edges(api_context, table_projector) -> None:
    graph = await _view(api_context, table_projector)
    image, word = await _labels(graph)
    spec = await sync_to_async(namespace_module.namespace_spec)(graph)
    image_pk = await sync_to_async(lambda: core_models.StructureCategory.objects.get(graph=graph, key="Image").pk)()

    assert image in spec.vertex_labels
    assert [(edge.source_pk, edge.target_pk) for edge in spec.edges if edge.label == word] == [(image_pk, image_pk)]


async def test_a_words_end_pins_round_trip_through_the_schema(api_schema, api_context, table_projector) -> None:
    """End pins are written and read back as GraphQL, and an end with none reads null."""
    graph = await _view(api_context, table_projector)
    pin = {"key": "@mikro/n_space_axes", "operator": "EQUALS", "value": 3}

    made = await _run(
        api_schema,
        api_context,
        writes.CREATE_STRUCTURE_RELATION_CATEGORY,
        input={"graph": str(graph.pk), "key": "MASK_OF", "source": {"identifiers": [IMAGE], "requires": [pin]}, "target": {"identifiers": [IMAGE]}},
    )
    created = made["createStructureRelationCategory"]
    read = (await _run(api_schema, api_context, reads.STRUCTURE_RELATION_CATEGORY_ENDS, id=created["id"]))["structureRelationCategory"]

    assert read["sourceDescriptor"] == {"identifiers": [IMAGE], "requires": [pin]} == created["sourceDescriptor"]
    assert read["targetDescriptor"] == {"identifiers": [IMAGE], "requires": None}


async def test_a_mount_is_made_read_and_kept_while_an_end_names_it(api_schema, api_context, table_projector) -> None:
    graph = await _view(api_context, table_projector)

    mounted = (await _run(api_schema, api_context, MOUNT, input={"graph": str(graph.pk), "key": "Region", "identifier": ROI}))["createStructureCategory"]
    assert (mounted["key"], mounted["identifier"]) == ("Region", ROI)
    mounts = (await _run(api_schema, api_context, MOUNTS, id=str(graph.pk)))["graph"]["structureCategories"]
    assert sorted((row["key"], row["identifier"]) for row in mounts) == [("Image", IMAGE), ("Region", ROI)]

    image = await sync_to_async(lambda: core_models.StructureCategory.objects.get(graph=graph, key="Image").pk)()
    refused = await api_schema.execute(UNMOUNT, variable_values={"input": {"id": str(image)}}, context_value=api_context)
    assert refused.errors and f"is named by {WORD}" in str(refused.errors[0]), "an end still names it"
    await _run(api_schema, api_context, UNMOUNT, input={"id": mounted["id"]})
