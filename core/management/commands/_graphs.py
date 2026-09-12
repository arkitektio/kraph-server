"""Resolve the `--graph` argument the projection commands share.

A graph is named by its **primary key** or its **name**. Never by its AGE handle:
that is random and internal now (`core.models.new_projection_handle`), so a
branch matching it would be dead weight that also taught operators to address a
view by a projection detail.

A name is not unique — two graphs in two organizations may both be called
"Cells", and nothing stops one organization from reusing a name either. An
ambiguous name is refused with the candidates listed, rather than resolved to
whichever row sorts first: every command this serves drops or redraws a
projection, and "the wrong one" is not a recoverable mistake from the command's
point of view.
"""

from __future__ import annotations

from django.core.management.base import CommandError

from core import models


def describe(graph: models.Graph) -> str:
    """How a command names a graph in its output: name and pk, never the handle."""
    return f"{graph.name} (#{graph.pk})"


def select_graph(identifier: str) -> models.Graph:
    """One graph by pk or name; refuses an ambiguous name."""
    found = select_graphs(identifier)
    if not found:
        raise CommandError(f"No matching graphs: nothing is named {identifier!r}, and no graph has that id.")
    if len(found) > 1:
        candidates = ", ".join(describe(graph) for graph in found)
        raise CommandError(f"{len(found)} graphs are called {identifier!r}: {candidates}. Pass the id.")
    return found[0]


def select_graphs(identifier: str) -> list[models.Graph]:
    """Every graph a pk or name denotes. Empty when none does."""
    text = str(identifier)
    if text.isdigit():
        return list(models.Graph.objects.filter(id=int(text)))
    return list(models.Graph.objects.filter(name=text).order_by("id"))
