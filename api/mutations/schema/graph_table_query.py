import re
from typing import cast

from kante.types import Info

from api import context, inputs, types
from core import models
from graph_engine import input_models


def _sanitize_identifier(value: str, fallback: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_]", "_", str(value))
    if not sanitized:
        sanitized = fallback
    if not re.match(r"^[A-Za-z_]", sanitized):
        sanitized = f"n_{sanitized}"
    return sanitized


def _format_cypher_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return "null"

    text = str(value)
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        return text
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _operator_to_cypher(operator: input_models.WhereOperator) -> str:
    mapping = {
        input_models.WhereOperator.EQUALS: "=",
        input_models.WhereOperator.NOT_EQUALS: "<>",
        input_models.WhereOperator.GREATER_THAN: ">",
        input_models.WhereOperator.LESS_THAN: "<",
        input_models.WhereOperator.GREATER_OR_EQUAL: ">=",
        input_models.WhereOperator.LESS_OR_EQUAL: "<=",
        input_models.WhereOperator.CONTAINS: "CONTAINS",
        input_models.WhereOperator.STARTS_WITH: "STARTS WITH",
        input_models.WhereOperator.ENDS_WITH: "ENDS WITH",
        input_models.WhereOperator.IN: "IN",
        input_models.WhereOperator.NOT_IN: "NOT IN",
    }
    if operator not in mapping:
        raise ValueError(f"Unsupported where operator: {operator}")
    return mapping[operator]


def _build_graph_table_query(builder_args: input_models.BuilderArgsInput) -> str:
    if not builder_args.match_paths:
        raise ValueError("builder_args.match_paths is required to build a graph table query")

    path_nodes: dict[str, dict[str, str]] = {}
    default_path_node: dict[str, str] = {}
    match_clauses: list[str] = []

    for path_index, path in enumerate(builder_args.match_paths):
        path_key = path.title or f"path_{path_index}"
        path_nodes[path_key] = {}

        if not path.nodes:
            raise ValueError(f"Match path '{path_key}' requires at least one node")

        node_vars: list[str] = []
        for node_index, node in enumerate(path.nodes):
            var_name = _sanitize_identifier(f"{path_key}_{node}", f"n_{path_index}_{node_index}")
            node_vars.append(var_name)
            path_nodes[path_key][str(node)] = var_name

        default_path_node[path_key] = node_vars[0]

        pattern_parts = [f"({node_vars[0]})"]
        for rel_index in range(len(node_vars) - 1):
            relation_name = ""
            if path.relations and rel_index < len(path.relations):
                relation_name = _sanitize_identifier(path.relations[rel_index], f"rel_{path_index}_{rel_index}")

            relation_fragment = f":{relation_name}" if relation_name else ""
            direction_out = True
            if path.relation_directions and rel_index < len(path.relation_directions):
                direction_out = bool(path.relation_directions[rel_index])

            if direction_out:
                pattern_parts.append(f"-[{relation_fragment}]->({node_vars[rel_index + 1]})")
            else:
                pattern_parts.append(f"<-[{relation_fragment}]-({node_vars[rel_index + 1]})")

        clause = "OPTIONAL MATCH" if path.optional else "MATCH"
        match_clauses.append(f"{clause} {''.join(pattern_parts)}")

    where_parts: list[str] = []
    for where in builder_args.where_clauses or []:
        path_key = where.path
        node_var = None
        if where.node is not None:
            node_var = path_nodes.get(path_key, {}).get(str(where.node))
        if node_var is None:
            node_var = default_path_node.get(path_key)
        if node_var is None:
            raise ValueError(f"Unknown path/node reference in where clause: path={where.path}, node={where.node}")

        op = _operator_to_cypher(where.operator)
        value = _format_cypher_value(where.value)
        where_parts.append(f"{node_var}.{where.property} {op} {value}")

    return_parts: list[str] = []
    for index, ret in enumerate(builder_args.return_statements or []):
        path_key = ret.path
        node_var = None
        if ret.node is not None:
            node_var = path_nodes.get(path_key, {}).get(str(ret.node))
        if node_var is None:
            node_var = default_path_node.get(path_key)
        if node_var is None:
            raise ValueError(f"Unknown path/node reference in return statement: path={ret.path}, node={ret.node}")

        if ret.property:
            alias = _sanitize_identifier(f"{path_key}_{ret.node or 'node'}_{ret.property}_{index}", f"c_{index}")
            return_parts.append(f"{node_var}.{ret.property} AS {alias}")
        else:
            alias = _sanitize_identifier(f"{path_key}_{ret.node or 'node'}_{index}", f"node_{index}")
            return_parts.append(f"{node_var} AS {alias}")

    if not return_parts:
        return_parts = [f"{node_var} AS {_sanitize_identifier(path_key, 'node')}" for path_key, node_var in default_path_node.items()]

    lines = [*match_clauses]
    if where_parts:
        lines.append("WHERE " + " AND ".join(where_parts))
    lines.append("RETURN " + ", ".join(return_parts))

    return "\n".join(lines)


def create_graph_table_query_through_builder(
    info: Info,
    input: inputs.CreateGraphTableQueryThroughBuilderInput,
) -> types.GraphTableQuery:
    """Create or update a graph table query from builder arguments."""
    model = input.to_pydantic()

    graph = context.get_accessible_graph(
        info,
        str(model.graph),
        actions=[input_models.Action.CREATE_BUILDER_ARG],
    )
    query = _build_graph_table_query(model.builder_args)

    graph_table_query, _ = models.GraphTableQuery.objects.update_or_create(
        graph=graph,
        key=model.key,
        defaults={
            "label": model.name or model.key,
            "description": model.description,
            "kind": "TABLE",
            "query": query,
            "columns": [column.model_dump(mode="json") for column in model.column_input],
            "matches": [match_path.model_dump(mode="json") for match_path in (model.builder_args.match_paths or [])],
            "wheres": [where_clause.model_dump(mode="json") for where_clause in (model.builder_args.where_clauses or [])],
            "returns": [return_statement.model_dump(mode="json") for return_statement in (model.builder_args.return_statements or [])],
        },
    )

    return cast(types.GraphTableQuery, graph_table_query)
