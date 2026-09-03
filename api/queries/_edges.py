"""Listing edges from the evidence base rather than from Apache AGE.

Every one of the plural edge queries used to build Cypher. That was wrong in two
ways at once, and the second is the one that made the first hard to see.

**They handed out ids nothing could take back.** `_to_retrieved_edge` built a
`RetrievedEdge` with no `row_id`, so `unique_id` fell back to
``{graph_name}:{age_edge_id}`` — while the matching singular fetcher expects a
`Link` primary key. The ids `relations(...)` returned could not be fed to
`relation(id:)`. Their `ids` *filter* had the mirror defect: it compared
`extract_graph_id(id)` against the graph's `age_name`, and since a uuid contains
hyphens that call returns the uuid's **first segment** — never equal, so the
filter silently answered "no matches" to a list of ids the API had just issued.

**And five of the six could not match anything at all.** `projector.create_vertex`
labels a vertex with `category.age_name` and writes exactly ``{id, category_id}``;
`graph_engine/vocab.py` records that `Structure`, `Metric` and `Assertion` are
names the *reader* looks for and never names the writer produces. So:

- `descriptions` matched ``(m:Metric)-[r]->(s:Structure)`` — neither label exists;
- the participation queries matched ``(:Entity)-[r]->(:NaturalEvent)`` — nor those;
- measurements and structure relations have **no AGE edge at all**, which their
  own mutation descriptions say ("Drawings are always empty").

Only `relations` was ever able to return a row. The rest were the same
guaranteed-empty shape as the `assertion`/`assertions` queries that were deleted
for exactly this reason.

Reading `Link` fixes both at once: the ids round-trip because they *are* the claim
ids, and the answer is the claim rather than the drawing — so it is right whether
or not a view happens to project the edge.
"""

from __future__ import annotations

from typing import Any, Iterable

from evidence import claims as claims_module
from evidence import models as evidence_models
from evidence import selector as selector_module

#: Filters that only ever meant something against an Apache AGE edge's properties.
#: A claim has none: `project_edges` writes `category_id` and `__assertion_count`
#: onto the drawing, and both are bookkeeping. Refused rather than ignored — a
#: filter that narrows nothing is how a wrong answer looks right.
_VERTEX_ONLY_FILTERS = ("has_property", "search", "matches")


def refuse_vertex_filters(filter_model: Any) -> None:
    """Reject filters that only applied to a projected edge's properties."""
    offending = [name for name in _VERTEX_ONLY_FILTERS if getattr(filter_model, name, None)]
    if offending:
        raise ValueError(f"{', '.join(offending)} filtered on properties of a projected edge. Edges are read from the evidence log now, and a claim carries no such properties — filter on `ids`, or read the endpoints' properties instead.")


def links_of_kind(organization: Any, kind: Any) -> Any:
    """Every standing claim of one kind in the organization."""
    return claims_module.standing(
        evidence_models.Link.objects.for_organization(organization).filter(kind=kind),
        "link",
    ).select_related("assertion", "term")


def links_for_category(organization: Any, category: Any, kind: Any) -> Any:
    """Standing claims of one kind, under the category's rule.

    A primitive category lists every claim naming its word, standings
    organization grain — two graphs declaring the same word list the same
    claims, which is the gain from the log naming a term. A **defined**
    category lists what its rules admit (RFC 0012): the claims its
    CLASSIFICATION-covering rules match, standings folded under its EXISTENCE
    trust — the same two-part fold every other claim kind gets.

    The organization is passed in rather than reached through `category.graph`. The
    claims are the tenant's and the category only supplies the rule, so taking the
    tenant from a graph would say that a view owns the claims it lists — and it made
    the one thing the caller has already authorized implicit here.
    """
    if category.definition:
        return claims_module.standing(
            evidence_models.Link.objects.for_organization(organization)
            .filter(kind=kind, term__kind=str(category.kind))
            .filter(selector_module.classification_filter(category.definition)),
            "link",
            predicate=selector_module.trust_predicate(category.definition, kind="EXISTENCE"),
        ).select_related("assertion", "term")
    return links_of_kind(organization, kind).filter(term_id=category.term_id)


def links_in_graph(graph: Any, kind: Any, *, ref_field: str) -> Any:
    """Standing claims of one kind touching a node this graph contains, folded
    under each claim's category rule.

    ``ref_field`` says which end has to be in the graph — for a participation the
    event does, and `participation_key` stores the event as `target_ref` on both
    the input and the output side.

    Membership comes from `selector.instance_refs_for`, the same subquery
    `informs_links_for` uses. The **fold** is per category (RFC 0009): each
    link's term names a category of this graph, and that category's clauses say
    whether the claim counts and whose standings fold — so this list agrees with
    what `projector.active_participation_links` would draw. This used to apply
    only the membership half, listing claims the same view refused to draw.
    """
    from graph_engine import projector as projector_module

    base = (
        evidence_models.Link.objects.for_organization(graph.organization)
        .filter(kind=kind)
        .filter(**{f"{ref_field}__in": selector_module.instance_refs_for(graph)})
    )

    by_term = projector_module.categories_by_term(graph)
    surviving: set[Any] = set()
    for term_id in set(base.values_list("term_id", flat=True)):
        category = by_term.get(term_id)
        if category is None:
            continue
        if category.definition:
            claims = base.filter(selector_module.classification_filter(category.definition), term__kind=str(category.kind))
            predicate = selector_module.trust_predicate(category.definition, kind="EXISTENCE")
        else:
            claims = base.filter(term_id=category.term_id)
            predicate = None
        surviving.update(claims_module.standing(claims, "link", predicate=predicate).values_list("pk", flat=True))

    return evidence_models.Link.objects.for_organization(graph.organization).filter(pk__in=surviving).select_related("assertion", "term")


def narrow(links: Any, filter_model: Any, ordering_models: Iterable[Any], pagination_model: Any) -> list[Any]:
    """Apply the ids filter, the ordering and the page. Returns rows.

    Ordering is over the log's own columns. `created_at` is when the row was
    stored; `id` breaks ties deterministically, which `id(r) DESC` over reassigned
    Apache AGE edge ids never could.
    """
    refuse_vertex_filters(filter_model)

    if getattr(filter_model, "ids", None):
        # Primary keys, straight through. This is the filter that used to parse a
        # composite id out of a uuid and quietly match nothing.
        links = links.filter(pk__in=[str(edge_id) for edge_id in filter_model.ids])

    order_by: list[str] = []
    for order_model in ordering_models:
        if getattr(order_model, "created_at", None):
            order_by.append(_direction("created_at", order_model.created_at))
        if getattr(order_model, "id", None):
            order_by.append(_direction("id", order_model.id))
    if not order_by:
        order_by = ["-created_at", "-id"]

    offset = int(getattr(pagination_model, "offset", 0) or 0)
    limit = int(getattr(pagination_model, "limit", 100) or 100)
    return list(links.order_by(*order_by)[offset : offset + limit])


def _direction(column: str, value: Any) -> str:
    return f"-{column}" if str(value).upper().endswith("DESC") else column
