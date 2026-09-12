"""Maintaining :class:`core.models.CategoryAssertedTerm`.

The fold is trivial — a category's ``definition.asserted_as`` is a list of words,
and this table is that list, one row per word. What is not trivial is *when* it
runs, and the three rules below are the whole module:

- **Rewrite, never insert.** A definition can stop naming a word as easily as
  start naming one, so :func:`sync_category` deletes what the category had and
  writes what it has. Inserting would leave a graph deriving from a word its own
  definition no longer mentions, and nothing would ever notice.
- **Not gated on `versioning.is_suspended()`.** That gate exists so
  `materialize()` emits one schema version instead of one per category. Sharing
  it here would leave a freshly materialized graph deriving from nothing, which is
  precisely the case where the table has the most to say.
- **The rebuild is the definition of correct.** :func:`refold` recomputes from the
  JSON, and `manage.py rebuild_asserted_terms --check` compares. If the two
  disagree, the incremental path is wrong — `CLAUDE.md` records what it costs when
  a fold and its rebuild are allowed to drift.

Reading `asserted_as` goes through :func:`evidence.selector.asserted_as_keys`,
which is also what turns a definition into a predicate over claims. Two spellings
of "which words does this definition name" would make a category match claims the
graph could not see, which is the bug `term_ids_for` documents having already been
fixed once.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from authentikate.models import Organization
from django.db import transaction
from core import models as core_models
import logging

if TYPE_CHECKING:
    # Imported inside every function body at runtime — this module is loaded
    # while `core.models` is still being defined — so the names are here for the
    # type checker alone.
    from core.models import Category, CategoryAssertedTerm, Graph
    from evidence.selector import Definition


def keys_in(definition: Definition | None) -> list[str]:
    """The words a definition derives from, deduplicated and in order.

    Deduplicated because ``(category, key)`` is unique and a hand-written
    definition may list a word twice; that is a redundant statement, not an error
    worth refusing a schema over.
    """
    from evidence import selector

    return list(dict.fromkeys(selector.asserted_as_keys(definition)))


def keys_for(category: Category) -> list[str]:
    """The words this category's definition derives from."""
    return keys_in(category.definition)


@transaction.atomic
def sync_category(category: Category) -> int:
    """Bring one category's rows in line with its definition. Returns how many it has.

    Called from the signal handler, so it has to tolerate a half-built row: a
    category saved before its graph is assigned has nothing to attribute the words
    to, and skipping is correct — the save that assigns the graph will fire again.
    """

    if category.pk is None or category.graph_id is None:
        return 0

    core_models.CategoryAssertedTerm.objects.filter(category_id=category.pk).delete()

    keys = keys_for(category)
    if not keys:
        return 0

    # `organization_id` off the graph rather than the category: a category has no
    # organization of its own, and the denormalization is what keeps the
    # organization-wide map a scan of this table instead of a join to `Graph`.
    organization_id = core_models.Graph.objects.filter(pk=category.graph_id).values_list("organization_id", flat=True).first()
    if organization_id is None:
        return 0

    core_models.CategoryAssertedTerm.objects.bulk_create(
        [
            core_models.CategoryAssertedTerm(
                organization_id=organization_id,
                graph_id=category.graph_id,
                category_id=category.pk,
                key=key,
            )
            for key in keys
        ]
    )
    return len(keys)


def forget_category(category: Category) -> None:
    """Drop a deleted category's rows.

    A separate entry point from :func:`sync_category` even though the body is the
    same delete, because `post_delete` hands over a row whose `pk` is still set but
    which no longer exists — calling the sync would read its definition and write
    rows for a category that is gone.
    """

    if category.pk is None:
        return
    core_models.CategoryAssertedTerm.objects.filter(category_id=category.pk).delete()


def graph_ids_by_key(organization: Organization, keys: Iterable[str] | None = None) -> dict[str, list[int]]:
    """Which graphs derive from each word — the read this table exists for.

    ``keys`` narrows it to an indexed seek on ``(organization, key)``, which is
    what the panel wants when it asks about the words on one page of subjects.
    Omitting it builds the organization-wide map `selector._graph_ids_by_term`
    needs, which is inherently a scan — but of two narrow columns rather than of
    every ``definition`` blob in the ontology.
    """

    rows = core_models.CategoryAssertedTerm.objects.filter(organization=organization)
    if keys is not None:
        keys = list(keys)
        if not keys:
            return {}
        rows = rows.filter(key__in=keys)

    by_key: dict[str, list[int]] = {}
    for key, graph_id in rows.values_list("key", "graph_id").distinct():
        by_key.setdefault(str(key), []).append(graph_id)
    return by_key


def keys_for_graph(graph: Graph) -> set[str]:
    """Every word this graph's categories derive from. One indexed lookup."""

    return {str(key) for key in core_models.CategoryAssertedTerm.objects.filter(graph=graph).values_list("key", flat=True)}


def keys_and_kinds_for_graph(graph: Graph) -> set[tuple[str, str]]:
    """Every `(word, kind)` this graph's categories derive from — the kind being the deriving category's.

    A `Term` is identified by kind as well as key, and a definition belongs to a
    category of one kind, so this is the join `evidence.selector.term_ids_for`
    needs; the key alone admitted words of the wrong kind.
    """

    return {(str(key), str(kind)) for key, kind in core_models.CategoryAssertedTerm.objects.filter(graph=graph).values_list("key", "category__kind")}


def expected(organization: Organization) -> set[tuple[int, str]]:
    """The ``(category_id, key)`` pairs the definitions imply, computed without writing.

    What `--check` compares the stored rows against, and what :func:`refold`
    writes. One function so the two cannot disagree about what "correct" is.
    """

    pairs: set[tuple[int, str]] = set()
    for category_id, definition in core_models.Category.objects.filter(graph__organization=organization).values_list("id", "definition"):
        for key in keys_in(definition):
            pairs.add((category_id, key))
    return pairs


def stored(organization: Organization) -> set[tuple[int, str]]:
    """The ``(category_id, key)`` pairs currently in the table."""

    return {(category_id, str(key)) for category_id, key in core_models.CategoryAssertedTerm.objects.filter(organization=organization).values_list("category_id", "key")}


@transaction.atomic
def refold(organization: Organization) -> int:
    """Rebuild every row in the organization from the definitions. Returns rows written.

    Deletes by organization rather than by category so that rows orphaned by a
    graph that changed hands, or written by a version of this code that keyed them
    differently, do not survive a rebuild.
    """

    core_models.CategoryAssertedTerm.objects.filter(organization=organization).delete()

    # `organization_id` comes off the graph, not off the argument. They agree
    # today, but `stored()` reads the denormalized column while `expected()` reads
    # `graph__organization` — so taking it from the argument would let a rebuild
    # rewrite a disagreement between those two rather than resolve it, and
    # `--check` would report drift it could not explain.
    rows: list[CategoryAssertedTerm] = []
    for category_id, graph_id, organization_id, definition in core_models.Category.objects.filter(graph__organization=organization).values_list("id", "graph_id", "graph__organization_id", "definition"):
        rows.extend(
            core_models.CategoryAssertedTerm(
                organization_id=organization_id,
                graph_id=graph_id,
                category_id=category_id,
                key=key,
            )
            for key in keys_in(definition)
        )

    core_models.CategoryAssertedTerm.objects.bulk_create(rows)
    return len(rows)


def on_category_saved(sender: type[Category], instance: Category, **kwargs: object) -> None:
    """Signal handler: a category was saved.

    Deliberately tolerant, for the same reason `versioning.on_category_changed`
    is: failing to index a word must not roll back the schema change that
    introduced it. But a silent failure here means a graph quietly stops deriving
    from a word, so it warns rather than passing.
    """
    try:
        sync_category(instance)
    except Exception as error:  # noqa: BLE001 - see docstring

        logging.getLogger(__name__).warning("Could not index asserted terms for category %s: %s", instance.pk, error)


def on_category_deleted(sender: type[Category], instance: Category, **kwargs: object) -> None:
    """Signal handler: a category was deleted.

    The cascade from `CategoryAssertedTerm.category` already removes the rows when
    Django performs the delete, so this is belt and braces — and it is the path
    that covers a raw-SQL or `_raw_delete` removal, where the cascade is the
    database's rather than Django's.
    """
    try:
        forget_category(instance)
    except Exception as error:  # noqa: BLE001 - see docstring

        logging.getLogger(__name__).warning("Could not drop asserted terms for category %s: %s", instance.pk, error)
