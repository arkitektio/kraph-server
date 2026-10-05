"""What this image answers a hub's installer: ``python -m hub_contract <verb>`` (see ``hub_contract``).

The installer knows the hub; how this release spells its config is written here, with the
settings it is read by. A key renamed in ``configuration.py`` is renamed in :func:`render` in
the same commit, and no installer has to learn of it.
"""

from __future__ import annotations

from hub_contract import JSON, Contract, Description, Facts, Needs, Offers, blocks

from kraph_server.configuration import Settings


def render(facts: Facts) -> dict[str, JSON]:
    """This release's config for the hub ``facts`` describes."""
    document: dict[str, JSON] = blocks.server(facts)
    document["datalayer"] = blocks.datalayer(facts, "media")
    return document


contract = Contract(
    description=Description(
        name="kraph",
        summary="The graph that ties samples, images and measurements together.",
        needs=Needs(storage=["media", "zarr", "bigfile"], instance_key=False, peers=[]),
        offers=Offers(),
    ),
    settings=Settings,
    render=render,
)
