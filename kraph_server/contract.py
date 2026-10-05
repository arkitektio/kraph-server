"""What this image answers a hub's installer: ``python -m arkitekt_service <verb>`` (see ``arkitekt_service.contract``).

The installer knows the hub; how this release spells its config is written here, with the
settings it is read by. A key renamed in ``configuration.py`` is renamed in :func:`render` in
the same commit, and no installer has to learn of it.
"""

from __future__ import annotations

from arkitekt_service.contract import JSON, Contract, Description, Facts, Needs, Offers, Scope, blocks

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
        summary="The graph that ties samples, images and measurements together.",
        needs=Needs(scopes=SCOPES, roles=ROLES, storage=["media", "zarr", "bigfile"], instance_key=False, peers=[]),
        offers=Offers(),
    ),
    settings=Settings,
    render=render,
)
