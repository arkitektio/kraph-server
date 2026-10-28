"""What this image answers a hub's installer: ``arkitekt-service <verb>`` (see ``arkitekt_service.contract``).

The installer knows the hub; how this release spells its config is written here, with the
settings it is read by. A key renamed in ``configuration.py`` is renamed in :func:`render` in
the same commit, and no installer has to learn of it.
"""

from __future__ import annotations

from arkitekt_service.contract import JSON, Contract, Description, Facts, Job, Needs, Offers, Role, Scope, Start, blocks

from kraph_server.configuration import Settings

#: What an app may do here on a user's behalf: defined at the coordination server when the hub
#: enrols. Every root field of the schema asks for one of them (`AuthExtension(scopes=...)`).
SCOPES = [
    Scope(key="kraph_read", description="Browse the knowledge graph and run graph queries and views."),
    Scope(key="kraph_assert", description="Record facts in the knowledge graph (entities, structures, metrics, measurements, relations, events, comments) and retract or supersede them."),
    Scope(key="kraph_insights", description="Create and change graphs, table queries and plots."),
    Scope(key="kraph_schema", description="Change the graph's vocabulary: entity, structure, metric, relation and event categories and terms."),
    Scope(key="kraph_all", description="Do everything in Kraph on your behalf.", is_all_scope=True),
]

#: What a member of an organization may do here.
ROLES = [
    Role(key="kraph_admin", description="Full control of Kraph in this organization.", is_admin_role=True),
    Role(key="kraph_editor", description="Record facts and build graphs and queries.", is_default_role=True),
    Role(key="kraph_curator", description="Curate the graph's vocabulary of categories and terms."),
]

#: The role every write asks for, the one a change to the vocabulary asks for instead, and the one
#: that holds both.
EDITOR = "kraph_editor"
CURATOR = "kraph_curator"
ADMIN = "kraph_admin"


#: What mikro offers its change feed as (its `Offers.endpoints`).
FEED = "feed"


def render(facts: Facts) -> dict[str, JSON]:
    """This release's config for the hub ``facts`` describes."""
    document: dict[str, JSON] = blocks.server(facts)
    document["datalayer"] = blocks.datalayer(facts, "media")
    # Without a key of its own (a hub that has not vouched for one yet: `konstruktor authorize`)
    # kraph serves as before and ingests nothing: no hook agent, no reads of mikro's feed.
    if facts.instance is None:
        return document
    document["instance"] = blocks.instance(facts)
    hook = blocks.rekuest_hook(facts)
    if hook is not None:
        document["rekuest_hook"] = hook
    mikro = facts.peers.get("mikro")
    if mikro is not None and FEED in mikro.offers:
        document["mikro"] = {"url": mikro.offers[FEED], "identifier": mikro.identifier or "mikro"}
    return document


contract = Contract(
    description=Description(
        name="kraph",
        identifier="live.arkitekt.kraph",
        summary="The graph that ties samples, images and measurements together.",
        # The instance key signs the hook agent's reports and its reads of mikro's change feed.
        needs=Needs(scopes=SCOPES, roles=ROLES, storage=["media", "zarr", "bigfile"], instance_key=True, peers=["rekuest", "mikro"]),
        # `rekuest_hook`: the hook agent (`kraph_server.hook_agent`), whose `ingest_metrics` a
        # trigger on mikro's metrics and a schedule run (internal network only).
        offers=Offers(endpoints={"rekuest_hook": "_rekuest/hook"}),
        # rekuest 8 registers a hook action's ports: without them the wiregram's trigger on
        # @mikro/metric is refused, and its import with it.
        requires={"rekuest": ">=8"},
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
