import logging

import strawberry
from kante.types import Info

from api import inputs, types
from api.extensions.cypher import get_current_cypher_engine
from core import models
from graph_engine import input_models, materialize
from ._guards import delete_or_explain
from .._scoped import accessible_graph

logger = logging.getLogger(__name__)


def create_graph(
    info: Info,
    input: inputs.CreateGraphInput,
) -> types.Graph:
    """GraphQL mutation wrapper for creating graph."""

    model = input.to_pydantic()  # Validate input with Pydantic models

    cypher = get_current_cypher_engine()

    graph = materialize.materialize(
        definition=model.definition or input_models.GraphDefinitionInput(),
        engine=cypher,
        user=info.context.request.user,
        organization=info.context.request.organization,
        name=model.name,
        description=model.description,
        membership=info.context.request.membership,
        backfill=model.backfill,
    )

    return graph


def _refuse_unless_archived(graph: models.Graph) -> None:
    """Deleting is irreversible, so make the reversible step come first.

    The same shape as emptying a trash. It also makes `delete_graph`'s own
    refusal message true for the first time: it has always said *"Archive the
    graph instead"*, and until `is_archived` became a real column that sentence
    pointed at a mutation which set an attribute and dropped it.

    Deliberately **not** a check on whether the graph contains anything. A graph
    is a view, there is no foreign key from it to `Node`, and deleting a view
    that has been used has to stay possible — that is the design
    `test_deleting_a_graph_leaves_the_evidence_standing` exists to hold. What is
    owed for a populated graph is a *record* of what went, not a refusal; see
    `_record_what_deletion_destroys`.
    """
    if not graph.is_archived:
        raise ValueError(f"Cannot delete graph '{graph.name}': archive it first. Deleting a graph is irreversible and takes every rule for reading the evidence with it — its categories, their definitions, its selector and its whole schema history. Archiving is reversible; if the graph is still wanted later, nothing has been lost.")


def _record_what_deletion_destroys(graph: models.Graph) -> None:
    """Say what is about to go, before it goes.

    The evidence survives a deletion — it is organization-scoped, which is the
    second axiom paying for itself. What does not survive is every rule for
    reading it: which words this view declared, what they meant here
    (`Category.definition`), whose claims counted (`Graph.selector`), and the
    whole `GraphSchema` chain. The node count is the number that matters, because
    it says how much evidence just lost its only reader.

    Written before `delete_or_explain` so the line exists even if the cascade
    half-fails.

    A log line is not a record, and this is not the fix. The durable version is
    Tier 2 work: once `snapshot_definition` round-trips everything `materialize`
    consumes, a deletion can persist the final schema and the view becomes
    reconstructible.
    """
    from evidence import selector as selector_module

    logger.warning(
        "Deleting graph '%s' (%s): %d node(s) lose their only reader; %d categor(ies) and %d schema version(s) go with it, and nothing records what they said.",
        graph.name,
        graph.age_name,
        selector_module.nodes_for(graph).count(),
        models.Category.objects.filter(graph=graph).count(),
        models.GraphSchema.objects.filter(graph=graph).count(),
    )


def delete_graph(
    info: Info,
    input: inputs.DeleteGraphInput,
) -> strawberry.ID:
    """GraphQL mutation wrapper for deleting a graph."""

    model = input.to_pydantic()  # Validate input with Pydantic models

    graph = accessible_graph(info, model.id)

    # Check permissions — only the graph's owner or an admin. `graph.owner` does
    # not exist; the field is `user`, so this raised `AttributeError` on every
    # call and no delete ever reached the guard below it.
    if not info.context.request.user.is_superuser and graph.user != info.context.request.user:
        raise PermissionError("You do not have permission to delete this graph.")

    # `delete_or_explain` cannot protect this one. It is a `try/except
    # ProtectedError`, and **nothing anywhere `PROTECT`s `core.Graph`** — every
    # foreign key into it cascades — so the guard could never fire and the call
    # below was an unconditional destruction wearing a refusal's clothes.
    #
    # What the CASCADE takes: every `Category`, `GraphSchema`, `GraphOntology`,
    # `GraphSequence`, `Protocol`, every saved query and plot, and
    # `MaterializedEdge`, plus the AGE namespace below. The evidence survives —
    # it is organization-scoped, which is the second axiom paying for itself —
    # but **every rule for reading it goes, with no record that it existed**. A
    # replayable log whose interpreter can be deleted irrecoverably is only half
    # replayable.
    #
    # So the gate below is the protection, checked in Python because there is no
    # `PROTECT` to lean on — and it is deliberately a gate on *deliberateness*,
    # not on emptiness. A graph is a view and deleting a used view stays legal;
    # what is owed is a record, which is the line after it.
    _refuse_unless_archived(graph)
    _record_what_deletion_destroys(graph)

    age_name = graph.age_name
    delete_or_explain(graph, what=f"graph '{graph.name}'", instead="Archive the graph instead — it keeps the projection out of the way without destroying the evidence other graphs read.")

    # Drop the projection too. The row went and the AGE namespace did not, so
    # every deleted graph left its labels and vertices behind — and the name is
    # unique, so re-creating a graph by the same name then collided with the
    # orphan. The projection is a cache; deleting the thing it caches has to take
    # it with it.
    try:
        get_current_cypher_engine().drop_graph(age_name, cascade=True)
    except Exception:  # noqa: BLE001 - the row is already gone; a stale namespace must not fail the request
        logger.warning("Deleted graph %s but could not drop its AGE namespace; drop it by hand.", age_name)

    return model.id


def archive_graph(
    info: Info,
    input: inputs.ArchiveGraphInput,
) -> types.Graph:
    """GraphQL mutation wrapper for archiving a graph."""

    model = input.to_pydantic()  # Validate input with Pydantic models

    graph = accessible_graph(info, model.id)

    # Check permissions - only graph owner or admin can archive
    if not info.context.request.user.is_superuser and graph.user != info.context.request.user:
        raise PermissionError("You do not have permission to archive this graph.")

    # `is_archived` is a real column as of `core.0003`. It was not before: this
    # set an attribute on the Python object, `save()` wrote nothing, and the
    # caller got the graph back looking archived. Because `Graph` carries
    # `ProvenanceField`, it also wrote a `simple_history` row recording a change
    # that had not happened.
    graph.is_archived = True
    graph.save()

    return graph


def update_graph(
    info: Info,
    input: inputs.UpdateGraphInput,
) -> types.Graph:
    """GraphQL mutation wrapper for updating a graph."""

    model = input.to_pydantic()

    # Tenancy first, and for every field. This resolver used to check nothing at
    # all except inside the `archived` branch below — so the one field that was
    # guarded was the one field with no column behind it, while `name`,
    # `description` and `pinned_by` were written unchecked by any member of any
    # organization who could guess an integer.
    graph = accessible_graph(info, model.id)

    if model.name is not None:
        graph.name = model.name
    if model.description is not None:
        graph.description = model.description
    if model.archived is not None:
        # Stricter than tenancy, and deliberately so — not the leftover of the
        # branch it used to live in. Archiving is now a *precondition of
        # deletion* (`_refuse_unless_archived`), so letting any colleague archive
        # a graph would let them set up its destruction. `archiveGraph` and
        # `deleteGraph` require owner-or-superuser for the same reason, and this
        # is the same operation reached through a different field.
        #
        # Renaming and pinning stay tenancy-scoped, matching every other schema
        # mutation: a shared view is the organization's to curate.
        if not info.context.request.user.is_superuser and graph.user != info.context.request.user:
            raise PermissionError("You do not have permission to archive this graph — archiving is the step before deletion, so it stays with the owner.")
        graph.is_archived = model.archived
    if model.pin is not None:
        if model.pin:
            graph.pinned_by.add(info.context.request.user)
        else:
            graph.pinned_by.remove(info.context.request.user)

    graph.save()

    return graph


def update_graph_visual(info: Info, input: inputs.UpdateGraphVisualInput) -> types.Graph:
    """GraphQL mutation wrapper for updating a graph's visual representation."""

    model = input.to_pydantic()  # Validate input with Pydantic models

    graph = accessible_graph(info, model.id)

    for node_position in model.node_positions:
        categories = graph.categories.get(id=node_position.category)
        categories.position_x = node_position.position_x
        categories.position_y = node_position.position_y
        categories.width = node_position.width
        categories.height = node_position.height
        categories.save()

    return graph


def pin_graph(
    info: Info,
    input: inputs.PinGraphInput,
) -> types.Graph:
    """GraphQL mutation wrapper for pinning a graph."""

    model = input.to_pydantic()  # Validate input with Pydantic models

    # `model.id`, not `model.graph_id`. `PinGraphInput` defines only `id`, so this
    # raised `AttributeError` on every call — twice, since the return read it too.
    graph = accessible_graph(info, model.id)

    if model.pin:
        graph.pinned_by.add(info.context.request.user)
    else:
        graph.pinned_by.remove(info.context.request.user)

    return types.Graph(id=model.id)
