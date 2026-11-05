"""What this image answers a hub's installer: ``arkitekt-service <verb>`` (see ``arkitekt_service.contract``).

The installer knows the hub; how this release spells its config is written here, with the
settings it is read by. A key renamed in ``configuration.py`` is renamed in :func:`render` in
the same commit, and no installer has to learn of it.
"""

from __future__ import annotations

from arkitekt_service.contract import JSON, Contract, Description, Descriptor, Facts, Hosts, Job, Needs, Offers, Role, Scope, Signal, Start, Structure, blocks

from kraph_server.configuration import Settings

#: What an app may do here on a user's behalf: defined at the coordination server when the hub
#: enrols. Every root field of the schema asks for one of them (`AuthExtension(scopes=...)`).
SCOPES = [
    Scope(key="kraph_read", description="Browse the knowledge graph and run graph queries and views."),
    Scope(key="kraph_assert", description="Record facts in the knowledge graph (entities, structures, metrics, measurements, relations, events, comments) and retract or supersede them."),
    Scope(key="kraph_insights", description="Create and change graphs, table queries, plots and todo lists."),
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


#: What a todo item says about itself, for a trigger to test: "an item of this project finished".
TODO_ITEM_DESCRIPTORS = [
    Descriptor(key="@kraph/status", type="STRING", description="Its board column: TODO, DOING or DONE"),
    Descriptor(key="@kraph/done", type="INT", description="How many of its objects are done"),
    Descriptor(key="@kraph/total", type="INT", description="How many objects it is about"),
    Descriptor(key="@kraph/list", type="STRING", description="The id of the todo list it is on"),
    Descriptor(key="@kraph/project", type="STRING", description="The id of the project its list belongs to"),
    Descriptor(key="@kraph/assignee", type="STRING", description="Who it is for (a sub): its own assignee, else its list's"),
]

#: What one object on an item says, for a trigger to test: "an image of this item is done".
TODO_OBJECT_DESCRIPTORS = [
    Descriptor(key="@kraph/identifier", type="STRING", description="The structure identifier of the object, e.g. @mikro/arraydataset"),
    Descriptor(key="@kraph/object", type="STRING", description="The object's id within its structure"),
    Descriptor(key="@kraph/status", type="STRING", description="How far along this object is: TODO, DOING or DONE"),
    Descriptor(key="@kraph/done_by", type="STRING", description="Who ticked it (a sub), once it is done"),
    Descriptor(key="@kraph/item", type="STRING", description="The id of the todo item it is on"),
    Descriptor(key="@kraph/list", type="STRING", description="The id of the todo list its item is on"),
    Descriptor(key="@kraph/project", type="STRING", description="The id of the project its list belongs to"),
]

#: What exists on a hub because kraph is there, said as data so the hub knows it from the image.
#: ``kraph_server/service.py`` binds each to its model. Todos are product state, not evidence.
HOSTS = Hosts(
    structures=[
        Structure(
            identifier="@kraph/todoitem",
            label="Todo Item",
            description="One card on a todo board: something somebody is asked to do over a set of objects (annotate these images), with a column (To do, Doing, Done) and the objects ticked off one by one.",
            descriptors=TODO_ITEM_DESCRIPTORS,
        ),
        Structure(
            identifier="@kraph/todoitemstructure",
            label="Todo Object",
            description="One object a todo item is about (an image to annotate), with its own To do / Doing / Done.",
            descriptors=TODO_OBJECT_DESCRIPTORS,
        ),
    ],
    signals=[
        Signal(
            identifier="@kraph/todoitem",
            kinds=["CREATED", "UPDATED", "DELETED"],
            descriptors=[d.key for d in TODO_ITEM_DESCRIPTORS],
            description="A todo item was made, changed (moved, reassigned, an object ticked) or deleted, with its column and how many of its objects are done: e.g. run an analysis once an item is Done.",
        ),
        Signal(
            identifier="@kraph/todoitemstructure",
            kinds=["CREATED", "UPDATED", "DELETED"],
            descriptors=[d.key for d in TODO_OBJECT_DESCRIPTORS],
            description="An object was put on a todo item, moved to To do / Doing / Done, or taken off: e.g. segment an image as soon as it is marked done.",
        ),
    ],
)


contract = Contract(
    description=Description(
        name="kraph",
        identifier="live.arkitekt.kraph",
        summary="The graph that ties samples, images and measurements together.",
        # The instance key signs the hook agent's reports and its reads of mikro's change feed.
        needs=Needs(scopes=SCOPES, roles=ROLES, storage=["media", "zarr", "bigfile"], instance_key=True, peers=["rekuest", "mikro"]),
        # `rekuest_hook`: the hook agent (`kraph_server.hook_agent`), whose `ingest_metrics` a
        # trigger on mikro's metrics and a schedule run (internal network only).
        offers=Offers(endpoints={"rekuest_hook": "_rekuest/hook", "rekuest_service": "_rekuest/service"}),
        hosts=HOSTS,
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
        "restore_descriptors": Job(("restore_descriptors",), "Store the descriptors of every todo row that misses one its structure declares (--all: of every row)"),
        "reproject": Job(("reproject",), "Rebuild a graph's projection from the evidence, or converge what is owed: --graph, --all, --incremental"),
        "rematerialize": Job(("rematerialize",), "Redraw the vertices of categories whose rules moved on without them: --graph, --stale"),
        "refresh_namespaces": Job(("refresh_namespaces",), "Rebuild graphs' queryable namespaces from their categories: --graph, --all"),
        "rebuild_identity": Job(("rebuild_identity",), "Rebuild the instance-identity fold from the sameness claims that stand: --check, --stale"),
        "rebuild_asserted_terms": Job(("rebuild_asserted_terms",), "Rebuild the index of the words each category's definition derives from: --check"),
        "backfill_schema": Job(("backfill_schema",), "Apply a schema change to the data it affects: --graph, --to-version"),
        "list_legacy_queries": Job(("list_legacy_queries",), "Name the saved queries that still store raw Cypher instead of a plan"),
        "redact": Job(("redact",), "Destroy evidence on purpose, logged: what no mutation can do"),
    },
    # `restore_descriptors`: todo rows from before a descriptor key existed are given it, announcing nothing.
    setup=("ensureadmin", "restore_descriptors"),
)
