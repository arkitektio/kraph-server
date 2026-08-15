"""Activity node query resolvers."""

from typing import List

import strawberry
from kante.types import Info

from api import context, filters, order, pagination, types
from graph_engine import input_models, retrieved, scalars


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


def activity(info: Info, id: scalars.GraphID) -> types.Activity:
    """Fetch a specific activity node by composite graph ID."""
    controller = context.get_controller()

    response = controller.get_node_for_composite_id(composite_id=id, info=info)
    node_type = str(response.node_type or "").upper()
    if node_type not in {"ASSERTION", "ACTIVITY"}:
        raise ValueError(f"Node {id} is not an activity")

    return types.Activity(_value=response)


def activities(
    info: Info,
    graph: strawberry.ID,
    filters: filters.NodeFilters | None = None,
    ordering: list[order.NodeOrder] | None = None,
    pagination: pagination.NodePaginationInput | None = None,
) -> List[types.Activity]:
    """Fetch activities in a graph with optional filters, ordering, and pagination."""
    controller = context.get_controller()
    graph_model = context.get_accessible_graph(info, graph)

    filter_model = filters.to_pydantic() if filters else input_models.NodeFilters()
    ordering_models = [entry.to_pydantic() for entry in ordering] if ordering else []
    pagination_model = pagination.to_pydantic() if pagination else input_models.NodePagination()

    # No `n:Assertion` branch: nothing has ever written an `Assertion` vertex, so
    # matching one only widened the pattern with a label that cannot occur.
    where_clauses = ["(n:Activity OR toUpper(coalesce(n.type, '')) = 'ACTIVITY')"]
    params: dict[str, object] = {}

    if filter_model.ids:
        # Matched on the uuid the vertex carries, not on `id(n)`. A client holds
        # the durable id; the AGE vertex id is reassigned by every reproject.
        params["ids"] = [str(node_id) for node_id in filter_model.ids]
        where_clauses.append("n.id IN $ids")

    if filter_model.has_property:
        params["has_property"] = filter_model.has_property
        where_clauses.append("n[$has_property] IS NOT NULL")

    if filter_model.search:
        params["search"] = filter_model.search
        where_clauses.append("toString(n) CONTAINS $search")

    _append_match_conditions("n", where_clauses, params, filter_model.matches)

    order_clauses: list[str] = []
    for order_model in ordering_models:
        if order_model.created_at:
            order_clauses.append(f"coalesce(n.created_at, 0) {_order_direction(order_model.created_at)}")
        if order_model.category:
            order_clauses.append(f"coalesce(n.category_id, '') {_order_direction(order_model.category)}")
        if order_model.id:
            order_clauses.append(f"id(n) {_order_direction(order_model.id)}")
        if order_model.property:
            property_key = f"order_property_{len(params)}"
            params[property_key] = order_model.property.key
            order_clauses.append(f"n[$${property_key}] {_order_direction(order_model.property.direction)}".replace("$$", "$"))

    if not order_clauses:
        order_clauses.append("id(n) DESC")

    params["offset"] = int(pagination_model.offset or 0)
    params["limit"] = int(pagination_model.limit or 100)

    result = controller.engine.execute(
        graph_model,
        f"""
        MATCH (n)
        WHERE {" AND ".join(where_clauses)}
        RETURN n, labels(n)[0] as label, id(n) as id
        ORDER BY {", ".join(order_clauses)}
        SKIP $offset
        LIMIT $limit
        """,
        params,
    )

    nodes = [
        retrieved.RetrievedNode(
            controller=controller,
            graph_name=str(graph_model.age_name),
            id=int(row["id"]),
            label=str(row.get("label", "Activity")),
            properties=(row.get("n") or {}).get("properties", {}) if isinstance(row.get("n"), dict) else {},
        )
        for row in result
    ]

    return [types.Activity(_value=node) for node in nodes]
