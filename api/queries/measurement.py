"""Measurement query resolvers."""

from typing import List

import strawberry
from kante.types import Info

from api import context, types, filters, order, pagination
from core import models
from graph_engine import input_models, retrieved, scalars


def _to_retrieved_edge(graph_name: str, row: dict) -> retrieved.RetrievedEdge:
    edge_payload = row.get("r") if isinstance(row.get("r"), dict) else {}
    return retrieved.RetrievedEdge(
        graph_name=graph_name,
        id=int(row["id"]),
        label=str(row.get("label", "UNKNOWN")),
        left_id=int(row["left_id"]),
        right_id=int(row["right_id"]),
        properties=edge_payload.get("properties", {}) if isinstance(edge_payload, dict) else {},
    )


def _order_direction(value: object) -> str:
    return "DESC" if str(value).upper().endswith("DESC") else "ASC"


def _append_match_conditions(alias: str, where_clauses: list[str], params: dict, matches: list[input_models.PropertyMatch] | None) -> None:
    if not matches:
        return

    for index, match in enumerate(matches):
        key_param = f"match_key_{index}"
        value_param = f"match_value_{index}"
        params[key_param] = match.key
        params[value_param] = match.value

        operator = str(match.operator)
        if operator.endswith("EQUALS"):
            where_clauses.append(f"{alias}[$${key_param}] = $${value_param}".replace("$$", "$"))
        elif operator.endswith("NOT_EQUALS"):
            where_clauses.append(f"{alias}[$${key_param}] <> $${value_param}".replace("$$", "$"))
        elif operator.endswith("GREATER_THAN"):
            where_clauses.append(f"{alias}[$${key_param}] > $${value_param}".replace("$$", "$"))
        elif operator.endswith("LESS_THAN"):
            where_clauses.append(f"{alias}[$${key_param}] < $${value_param}".replace("$$", "$"))
        elif operator.endswith("GREATER_OR_EQUAL") or operator.endswith("GREATER_THAN_OR_EQUAL"):
            where_clauses.append(f"{alias}[$${key_param}] >= $${value_param}".replace("$$", "$"))
        elif operator.endswith("LESS_OR_EQUAL") or operator.endswith("LESS_THAN_OR_EQUAL"):
            where_clauses.append(f"{alias}[$${key_param}] <= $${value_param}".replace("$$", "$"))
        elif operator.endswith("CONTAINS"):
            where_clauses.append(f"toString({alias}[$${key_param}]) CONTAINS toString($${value_param})".replace("$$", "$"))
        elif operator.endswith("STARTS_WITH"):
            where_clauses.append(f"toString({alias}[$${key_param}]) STARTS WITH toString($${value_param})".replace("$$", "$"))
        elif operator.endswith("ENDS_WITH"):
            where_clauses.append(f"toString({alias}[$${key_param}]) ENDS WITH toString($${value_param})".replace("$$", "$"))
        elif operator.endswith("IN"):
            where_clauses.append(f"{alias}[$${key_param}] IN $${value_param}".replace("$$", "$"))
        elif operator.endswith("NOT_IN"):
            where_clauses.append(f"NOT {alias}[$${key_param}] IN $${value_param}".replace("$$", "$"))


def measurement(info: Info, id: scalars.GraphID) -> types.Measurement:
    """Fetch one measurement by the id of the claim that made it.

    Resolved from the `Link` row, not from Apache AGE. The id a client holds is
    that row's primary key — `RetrievedEdge.unique_id` returns it for every
    row-backed edge, which is all of them — and this used to split it on the first
    hyphen to recover a graph name and an integer AGE edge id. Given a uuid that
    yielded a graph named after its first segment and `int()` over the rest:
    `invalid literal for int() with base 10`, on the very id the API had just
    handed out.

    It could not be made to work by parsing harder. An AGE edge carries no claim
    id and cannot: `project_edges` merges every assertion of one proposition onto
    a single edge, which is the point — agreement is countable in the evidence and
    a traversal still sees one connection.
    """
    controller = context.get_controller()

    edge = controller.get_relation_by_id(str(id), info=info)
    if edge is None:
        raise ValueError(f"Measurement with ID {id} not found")

    return types.Measurement(_value=edge)


def measurements(
    info: Info,
    measurement_category_id: strawberry.ID,
    filters: filters.MeasurementFilter | None = None,
    ordering: list[order.MeasurementOrder] | None = None,
    pagination: pagination.MeasurementPaginationInput | None = None,
) -> List[types.Measurement]:
    """Fetch measurements for a given category with optional filters, ordering, and pagination."""
    controller = context.get_controller()

    category = models.MeasurementCategory.objects.filter(id=measurement_category_id).first()
    if category is None:
        raise ValueError(f"Measurement category {measurement_category_id} not found")

    graph = context.get_accessible_graph(info, str(category.graph.age_name))

    filter_model = filters.to_pydantic() if filters else input_models.MeasurementFilters()
    filter_model.category = str(category.id)
    ordering_models = [entry.to_pydantic() for entry in ordering] if ordering else []
    pagination_model = pagination.to_pydantic() if pagination else input_models.MeasurementPagination()

    where_clauses = ["r.category_id = $category_id"]
    params: dict[str, object] = {"category_id": str(category.id)}

    if filter_model.ids:
        edge_ids: list[int] = []
        for graph_id in filter_model.ids:
            if str(context.extract_graph_id(graph_id)) == str(graph.age_name):
                edge_ids.append(int(context.extract_node_id(graph_id)))
        if not edge_ids:
            return []
        params["ids"] = edge_ids
        where_clauses.append("id(r) IN $ids")

    if filter_model.has_property:
        params["has_property"] = filter_model.has_property
        where_clauses.append("r[$has_property] IS NOT NULL")

    if filter_model.search:
        params["search"] = filter_model.search
        where_clauses.append("toString(r) CONTAINS $search")

    _append_match_conditions("r", where_clauses, params, filter_model.matches)

    order_clauses: list[str] = []
    for order_model in ordering_models:
        if order_model.created_at:
            order_clauses.append(f"coalesce(r.created_at, 0) {_order_direction(order_model.created_at)}")
        if order_model.category:
            order_clauses.append(f"coalesce(r.category_id, '') {_order_direction(order_model.category)}")
        if order_model.id:
            order_clauses.append(f"id(r) {_order_direction(order_model.id)}")
        if order_model.property:
            property_key = f"order_property_{len(params)}"
            params[property_key] = order_model.property.key
            order_clauses.append(f"r[$${property_key}] {_order_direction(order_model.property.direction)}".replace("$$", "$"))

    if not order_clauses:
        order_clauses.append("id(r) DESC")

    params["offset"] = int(pagination_model.offset or 0)
    params["limit"] = int(pagination_model.limit or 100)

    result = controller.engine.execute(
        graph,
        f"""
        MATCH ()-[r]->()
        WHERE {" AND ".join(where_clauses)}
        RETURN r, type(r) as label, id(r) as id, id(startNode(r)) as left_id, id(endNode(r)) as right_id
        ORDER BY {", ".join(order_clauses)}
        SKIP $offset
        LIMIT $limit
        """,
        params,
    )

    return [types.Measurement(_value=_to_retrieved_edge(str(graph.age_name), row)) for row in result]
