"""What one view's namespace contains, derived from its categories.

A graph's namespace — the per-graph Postgres schema holding one view per node
category, one view per (edge label x admitted endpoint pair), and one SQL/PGQ
property graph over them — is a **derived artifact**: generated wholesale from
the graph's `core.Category` rows, droppable, and rebuilt by
`Projector.refresh_namespace`, exactly as the drawing itself is rebuilt from
evidence (RFC 0006).

This module is the *what*: a pure spec builder that reads the schema and decides
which element tables and labels the namespace declares. The *how* — the DDL —
lives in `graph_engine/projection/table.py`, the one module allowed to address
the projection's storage; the fence test holds this module to naming no SQL and
no projection table.

Two deliberate absences, both recorded in RFC 0006:

- **Measurement and structure-relation categories appear nowhere.** Nothing
  draws them — a measurement's source is a structure and structures stopped
  being vertices in M1 — so a label for them would declare an element table
  that is empty by construction.
- **An edge drawn between endpoints outside the declared pairs is outside the
  property graph.** It still exists in the base tables (`list_drawn` and
  `drawn_edge` read everything drawn); the namespace is the *schema's shape*,
  which is precisely what makes it an enforcement surface rather than a mirror.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from core import enums as core_enums
from core import models as core_models
from graph_engine.input_models import EntityDescriptorInput

#: Refuse to build a namespace above this many element tables. An open
#: source/target descriptor expands over every entity-like category in the
#: graph, so a schema with many categories and several unconstrained relations
#: goes quadratic — the refusal names the categories to narrow, loudly, instead
#: of silently truncating the namespace.
NAMESPACE_MAX_ELEMENT_TABLES = 512

#: Postgres truncates identifiers beyond 63 bytes silently, which would let two
#: long labels collide into one. Refuse instead.
_MAX_IDENTIFIER_BYTES = 63

#: The category kinds that draw vertices and may anchor an edge endpoint.
_ENTITY_LIKE_KINDS = (
    core_enums.CategoryKindChoices.ENTITY,
    core_enums.CategoryKindChoices.REAGENT,
)

#: The participation labels, per event kind — class constants on the proxies,
#: not rows, so they are folded in here (`AGE_INPUT_EDGE` / `AGE_OUTPUT_EDGE`).
#: Inputs run entity -> event; outputs run event -> entity (the writer already
#: flips outputs when drawing, so these encode the *drawn* direction and the
#: reader never flips anything).
_PARTICIPATION = {
    core_enums.CategoryKindChoices.NATURAL_EVENT: (
        core_models.NaturalEventCategory.AGE_INPUT_EDGE,
        core_models.NaturalEventCategory.AGE_OUTPUT_EDGE,
        "ein",
        "eout",
    ),
    core_enums.CategoryKindChoices.PROTOCOL_EVENT: (
        core_models.ProtocolEventCategory.AGE_INPUT_EDGE,
        core_models.ProtocolEventCategory.AGE_OUTPUT_EDGE,
        "psub",
        "pprod",
    ),
}


@dataclass(frozen=True)
class VertexElement:
    """One node category's element table: a view over its drawn vertices."""

    view_name: str
    label: str
    category_pk: int


@dataclass(frozen=True)
class EdgeElement:
    """One (edge label x endpoint pair) element table."""

    view_name: str
    label: str
    source_pk: int
    target_pk: int


@dataclass(frozen=True)
class NamespaceSpec:
    """Everything the DDL compiler needs to build one graph's namespace."""

    schema_name: str
    graph_pk: int
    vertices: tuple[VertexElement, ...]
    edges: tuple[EdgeElement, ...]

    @property
    def vertex_labels(self) -> frozenset[str]:
        return frozenset(vertex.label for vertex in self.vertices)

    @property
    def edge_labels(self) -> frozenset[str]:
        return frozenset(edge.label for edge in self.edges)


class NamespaceSpecError(ValueError):
    """The schema cannot be spelled as a namespace. Always says why and names names."""


def _guard_label(label: str, *, category: core_models.Category | None = None) -> str:
    where = f" (category #{category.pk}, key {category.key!r})" if category is not None else ""
    if "\x00" in label:
        raise NamespaceSpecError(f"label {label!r}{where} contains a NUL byte, which no identifier can carry")
    if len(label.encode()) > _MAX_IDENTIFIER_BYTES:
        raise NamespaceSpecError(
            f"label {label!r}{where} is longer than {_MAX_IDENTIFIER_BYTES} bytes; Postgres would silently "
            "truncate it, letting two long labels collide — rename the category"
        )
    return label


def _descriptor(value: Any) -> EntityDescriptorInput:
    if not value:
        return EntityDescriptorInput()
    return EntityDescriptorInput(**value)


def _matched(descriptor: EntityDescriptorInput, candidates: Sequence[core_models.Category]) -> list[core_models.Category]:
    return [candidate for candidate in candidates if descriptor.matches(candidate)]


def _role_endpoints(roles: Any, candidates: Sequence[core_models.Category]) -> list[core_models.Category]:
    """The entity-like categories a role list admits; an absent or empty list admits all.

    A role's descriptor narrows the endpoint the same way a relation's does; the
    union over roles is what can participate at all.
    """
    if not roles:
        return list(candidates)
    admitted: dict[int, core_models.Category] = {}
    for role in roles:
        descriptor = _descriptor((role or {}).get("descriptor"))
        for candidate in _matched(descriptor, candidates):
            admitted[candidate.pk] = candidate
    return list(admitted.values())


def namespace_spec(graph: Any) -> NamespaceSpec:
    """Derive the namespace one graph's categories declare.

    Reads `core.Category` rows only — never the drawing — so the spec is a pure
    function of the schema, and rebuilding it is always safe.
    """
    categories = list(
        core_models.Category.objects.filter(graph=graph)
        .prefetch_related("ontology_references")
        .order_by("pk")
    )
    node_categories = [c for c in categories if c.kind in {str(k) for k in core_enums.NODE_CATEGORY_KINDS}]
    entity_like = [c for c in node_categories if c.kind in {str(k) for k in _ENTITY_LIKE_KINDS}]

    participation_labels = {label for labels in _PARTICIPATION.values() for label in labels[:2]}
    vertices: list[VertexElement] = []
    for category in node_categories:
        label = _guard_label(str(category.age_name), category=category)
        if label in participation_labels:
            raise NamespaceSpecError(
                f"category #{category.pk} (key {category.key!r}) is labeled {label!r}, which is a "
                "participation edge label — the namespace cannot carry it as both a vertex and an edge label"
            )
        vertices.append(VertexElement(view_name=f"v{category.pk}", label=label, category_pk=category.pk))

    edges: list[EdgeElement] = []
    for category in categories:
        if category.kind == str(core_enums.CategoryKindChoices.RELATION):
            label = _guard_label(str(category.age_name), category=category)
            sources = _matched(_descriptor(category.source_definition), entity_like)
            targets = _matched(_descriptor(category.target_definition), entity_like)
            for source in sources:
                for target in targets:
                    edges.append(
                        EdgeElement(
                            view_name=f"e{category.pk}_{source.pk}_{target.pk}",
                            label=label,
                            source_pk=source.pk,
                            target_pk=target.pk,
                        )
                    )
        elif category.kind in _PARTICIPATION:
            input_label, output_label, input_prefix, output_prefix = _PARTICIPATION[
                core_enums.CategoryKindChoices(category.kind)
            ]
            inputs = _role_endpoints(category.source_entity_roles, entity_like)
            outputs = _role_endpoints(category.target_entity_roles, entity_like)
            for source in inputs:
                edges.append(
                    EdgeElement(
                        view_name=f"{input_prefix}{category.pk}_{source.pk}",
                        label=input_label,
                        source_pk=source.pk,
                        target_pk=category.pk,
                    )
                )
            for target in outputs:
                edges.append(
                    EdgeElement(
                        view_name=f"{output_prefix}{category.pk}_{target.pk}",
                        label=output_label,
                        source_pk=category.pk,
                        target_pk=target.pk,
                    )
                )
        # MEASUREMENT and STRUCTURE_RELATION: nothing draws them — no element tables.

    total = len(vertices) + len(edges)
    if total > NAMESPACE_MAX_ELEMENT_TABLES:
        open_relations = [
            f"#{c.pk} ({c.key!r})"
            for c in categories
            if c.kind == str(core_enums.CategoryKindChoices.RELATION)
            and not (c.source_definition or {}).get("keys")
            and not (c.source_definition or {}).get("ontology_terms")
        ]
        raise NamespaceSpecError(
            f"graph #{graph.pk} would need {total} element tables (cap {NAMESPACE_MAX_ELEMENT_TABLES}): "
            f"open source/target descriptors expand over every entity category — narrow the descriptors on "
            f"relation categories {', '.join(open_relations) or '(none open — many categories)'}"
        )

    return NamespaceSpec(
        schema_name=str(graph.age_name),
        graph_pk=int(graph.pk),
        vertices=tuple(vertices),
        edges=tuple(edges),
    )


def declared_labels(graph: Any) -> tuple[frozenset[str], frozenset[str]]:
    """The (vertex labels, edge labels) one graph's namespace declares.

    What the query compiler resolves a plan's label strings against: a label in
    neither set is refused by name rather than silently matching nothing.
    """
    spec = namespace_spec(graph)
    return spec.vertex_labels, spec.edge_labels


def participation_edge_labels() -> frozenset[str]:
    """The four participation labels, which exist in every graph with event categories."""
    return frozenset(label for labels in _PARTICIPATION.values() for label in labels[:2])
