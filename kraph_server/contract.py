"""What this image answers a hub's installer: ``arkitekt-service <verb>`` (see ``arkitekt_service.contract``).

The installer knows the hub; how this release spells its config is written here, with the
settings it is read by. A key renamed in ``configuration.py`` is renamed in :func:`render` in
the same commit, and no installer has to learn of it.
"""

from __future__ import annotations

from arkitekt_service.contract import JSON, Contract, Description, Facts, Job, Needs, Offers, Scope, Start, blocks

from kraph_server.configuration import Settings

#: What a token may be allowed to do here: defined at the coordination server when the hub enrols.
SCOPES = [
    Scope(key="kraph_read", description="Read graph data"),
    Scope(key="kraph_write", description="Write graph data"),
    Scope(key="kraph_query", description="Execute graph queries"),
    Scope(key="read", description="Generic read access"),
    Scope(key="write", description="Generic write access"),
]

#: The roles a member of an organization can hold here.
ROLES = [
    Scope(key="admin", description="Full administrative access"),
    Scope(key="user", description="Standard user access"),
    Scope(key="editor", description="Can edit graph data"),
    Scope(key="viewer", description="Read-only access"),
]


def render(facts: Facts) -> dict[str, JSON]:
    """This release's config for the hub ``facts`` describes."""
    document: dict[str, JSON] = blocks.server(facts)
    document["datalayer"] = blocks.datalayer(facts, "media")
    return document


contract = Contract(
    description=Description(
        name="kraph",
        identifier="live.arkitekt.kraph",
        summary="The graph that ties samples, images and measurements together.",
        needs=Needs(scopes=SCOPES, roles=ROLES, storage=["media", "zarr", "bigfile"], instance_key=False, peers=[]),
        offers=Offers(),
    ),
    settings=Settings,
    render=render,
    # How this service is started: there is no script beside it. `arkitekt-service serve`
    # (and `debug`) become these, so they get the container's signals themselves.
    serve=Start(("daphne", "-b", "0.0.0.0", "-p", "80", "--websocket_timeout", "-1", "kraph_server.asgi:application")),
    debug=Start(("python", "manage.py", "runserver", "0.0.0.0:80")),
    jobs={
        "ensureadmin": Job(("ensureadmin",), "Create the operator account the config names"),
        "reproject": Job(("reproject",), "Rebuild a graph's projection from the evidence, or converge what is owed: --graph, --all, --incremental"),
        "rematerialize": Job(("rematerialize",), "Redraw the vertices of categories whose rules moved on without them: --graph, --stale"),
        "refresh_namespaces": Job(("refresh_namespaces",), "Rebuild graphs' queryable namespaces from their categories: --graph, --all"),
        "rebuild_identity": Job(("rebuild_identity",), "Rebuild the instance-identity fold from the sameness claims that stand: --check, --stale"),
        "rebuild_asserted_terms": Job(("rebuild_asserted_terms",), "Rebuild the index of the words each category's definition derives from: --check"),
        "backfill_schema": Job(("backfill_schema",), "Apply a schema change to the data it affects: --graph, --to-version"),
        "list_legacy_queries": Job(("list_legacy_queries",), "Name the saved queries that still store raw Cypher instead of a plan"),
        "redact": Job(("redact",), "Destroy evidence on purpose, logged: what no mutation can do"),
    },
    setup=("ensureadmin",),
)
