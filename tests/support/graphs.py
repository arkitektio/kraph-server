"""Building views and rebuilding their drawings, for tests.

A view is a function of the log (A6); these build one from a definition document
through the API — the door a client uses — and `rebuild` re-derives its drawing
from the log, which is the honesty test every projection property comes down to.
"""

from datetime import datetime, timezone
from typing import Any

from asgiref.sync import sync_to_async

from core import models as core_models
from evidence import identity as identity_module
from evidence import models as evidence_models
from evidence import writer
from graph_engine.controller import GraphController
from tests.support.writes import CREATE_GRAPH, execute

#: Three moments the rule examples bound on: before, at, and after "Dec 5".
DEC5 = datetime(2026, 12, 5, tzinfo=timezone.utc)
BEFORE = datetime(2026, 11, 1, tzinfo=timezone.utc)
AFTER = datetime(2026, 12, 20, tzinfo=timezone.utc)

#: The worked example of RFC 0009: an `AIS` category whose rule names two words,
#: two annotators and a date; a relation and an event category with rules of
#: their own; and a `Cell` declared primitively.
EXAMPLE_DEFINITION: dict[str, Any] = {
    "systemVersion": "2.0.0",
    "extensions": {
        "entities": [
            {
                "key": "AIS",
                "definition": {
                    "rules": [
                        {
                            "when": [
                                {"field": "WORD", "operator": "IS", "value": "AIS"},
                                {"field": "SUBJECT", "operator": "IS", "value": "peter"},
                                {"field": "ASSERTED_AT", "operator": "BEFORE", "value": DEC5.isoformat()},
                            ],
                            "unless": [{"when": [{"field": "APP", "operator": "IS", "value": "sloppy-import"}]}],
                        },
                        {
                            "when": [
                                {"field": "WORD", "operator": "IS", "value": "AxonInitialSegment"},
                                {"field": "SUBJECT", "operator": "IS", "value": "karl"},
                                {"field": "ASSERTED_AT", "operator": "SINCE", "value": DEC5.isoformat()},
                            ]
                        },
                    ]
                },
                "propertyDefinitions": [
                    {
                        "key": "avg_length",
                        "valueKind": "FLOAT",
                        "derivation": "ROLLUP",
                        "rule": {
                            "sourceNode": "ROI",
                            "key": "vector_length",
                            "aggregation": "MEAN",
                            "evidence": {"rules": [{"when": [{"field": "APP", "operator": "IS", "value": "segmenter-v3"}]}]},
                        },
                    }
                ],
            },
            {"key": "Cell"},
        ],
        "relations": [
            {
                "key": "IS_CONNECTED_TO",
                "source": {"keys": ["Cell"]},
                "target": {"keys": ["Cell"]},
                "definition": {
                    "rules": [
                        {
                            "when": [
                                {"field": "WORD", "operator": "IS", "value": "IS_CONNECTED_TO"},
                                {"field": "SUBJECT", "operator": "IS", "value": "karl"},
                                {"field": "ASSERTED_AT", "operator": "SINCE", "value": DEC5.isoformat()},
                            ]
                        }
                    ]
                },
            }
        ],
        "events": [
            {
                "key": "Mitosis",
                "kind": "INTRINSIC",
                "definition": {
                    "rules": [
                        {
                            "when": [
                                {"field": "WORD", "operator": "IS", "value": "Mitosis"},
                                {"field": "APP", "operator": "IS", "value": "event-annotator"},
                            ]
                        }
                    ]
                },
                "inputs": [{"key": "Cell", "role": "mother", "descriptor": {"keys": ["Cell"]}}],
                "outputs": [{"key": "Cell", "role": "daughter", "descriptor": {"keys": ["Cell"]}}],
            }
        ],
    },
}


async def graph_with(api_schema: Any, ctx: Any, name: str, definition: dict[str, Any], *, sameness_rule: dict[str, Any] | None = None) -> str:
    """Create a view from a definition document through the API. Returns its id."""
    payload: dict[str, Any] = {"name": name, "definition": definition}
    if sameness_rule is not None:
        payload["samenessRule"] = sameness_rule
    return (await execute(api_schema, ctx, CREATE_GRAPH, {"input": payload}))["createGraph"]["id"]


async def example_graph(api_schema: Any, ctx: Any, name: str) -> str:
    """The RFC 0009 example view, by name."""
    return await graph_with(api_schema, ctx, name, EXAMPLE_DEFINITION)


async def graph_declaring(api_schema: Any, ctx: Any, word: str, *, name: str | None = None, definition: dict[str, Any] | None = None) -> str:
    """A view declaring one entity word, primitively or under `definition`."""
    entity: dict[str, Any] = {"key": word}
    if definition is not None:
        entity["definition"] = definition
    return await graph_with(api_schema, ctx, name or f"view-of-{word}", {"extensions": {"entities": [entity]}})


def rebuild(graph: Any, table_projector: Any) -> core_models.Graph:
    """Drop this view's drawing and derive it again from the log. Takes a `Graph` or its id."""
    if not isinstance(graph, core_models.Graph):
        graph = core_models.Graph.objects.get(pk=graph)
    GraphController(projector=table_projector).rebuild_projection(graph)
    return graph


async def arebuild(graph: Any, table_projector: Any) -> core_models.Graph:
    return await sync_to_async(rebuild)(graph, table_projector)


def merge_as(organization: Any, left: str, right: str, subject: str) -> None:
    """A sameness claim by a named annotator, folded into the organization-grain
    cache exactly as the controller folds it."""
    assertion = writer.create_assertion(organization, subject=subject, app_id="pytest")
    writer.create_link(organization, kind=evidence_models.Link.Kind.SAME_AS, source_ref=left, target_ref=right, assertion=assertion)
    identity_module.merge(organization, left, right)
