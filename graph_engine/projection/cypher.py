"""The Apache AGE projector — the one module that emits Cypher for a drawing.

Every query the projection layer runs lives here, phrased once. `rebuild` and a
fresh write draw through the same methods, which is what keeps a replayed vertex
and a freshly written one from drifting apart; the controller and
`graph_engine.projector` never see a query string.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

from graph_engine.engine.protocol import CypherEngine
from graph_engine.projection.protocol import DrawnEdge

_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class CypherProjector:
    """Draws a view into an Apache AGE graph named by `Graph.get_age_name()`."""

    kind = "age"

    def __init__(self, engine: CypherEngine) -> None:
        self.engine = engine

    # ------------------------------------------------------------------ namespace

    def create_namespace(self, graph: Any) -> None:
        self.engine.create_graph(age_name=graph.get_age_name())

    def drop_namespace(self, graph: Any) -> None:
        self.engine.drop_graph(graph.get_age_name(), cascade=True)

    # ------------------------------------------------------------------ writer: nodes

    def draw_node(self, graph: Any, ref: str, label: str, category_id: Any, kind: str) -> None:
        # `MERGE` on the id, not `CREATE`: drawing a node that is already drawn —
        # `attest_node` on a standing node, `project_all` over a populated
        # namespace, an incremental replay — has to converge on one vertex. The
        # label is part of the pattern, so a node whose *label* moved still needs
        # its old vertex cleared first; `reproject_node` does that, `rebuild`
        # drops the namespace.
        self.engine.execute(
            graph,
            f"""
            MERGE (e:{label} {{id: $eid}})
            SET e.category_id = $cid, e.type = $ntype
            RETURN id(e) as db_id
            """,
            {"eid": str(ref), "cid": category_id, "ntype": str(kind)},
        )

    def write_properties(self, graph: Any, ref: str, label: str, values: Mapping[str, Any]) -> bool:
        # Matched by the node's stable `id` property rather than by vertex id,
        # because vertex ids do not survive a rebuild. Returns whether a vertex was
        # matched: a `SET` against nothing is a silent no-op in Cypher.
        if not values:
            return True
        set_clause = ", ".join(f"e.{self.validate_key(key)} = $u_{key}" for key in values)
        params: dict[str, Any] = {f"u_{key}": value for key, value in values.items()}
        params["node_uuid"] = str(ref)
        result = self.engine.execute(
            graph,
            f"""
            MATCH (e:{label}) WHERE e.id = $node_uuid
            SET {set_clause}
            RETURN id(e) as node_id
            """,
            params,
        )
        return bool(result)

    def clear_properties(self, graph: Any, label: str, refs: Iterable[str], keys: Iterable[str]) -> None:
        owned = sorted({self.validate_key(key) for key in keys})
        refs = [str(ref) for ref in refs]
        if not owned or not refs:
            return
        remove_clause = ", ".join(f"e.{key}" for key in owned)
        self.engine.execute(
            graph,
            f"""
            MATCH (e:{label}) WHERE e.id IN $refs
            REMOVE {remove_clause}
            RETURN id(e) as node_id
            """,
            {"refs": refs},
        )

    def erase_nodes(self, graph: Any, refs: Iterable[str]) -> int:
        removed = 0
        for ref in refs:
            # Counted before the delete: AGE reports nothing useful back from
            # `DETACH DELETE`, and a count that always said "1" would be the same
            # kind of lie `project_edges` used to tell.
            found = self.engine.execute(graph, "MATCH (e) WHERE e.id = $node_uuid RETURN id(e) as db_id", {"node_uuid": str(ref)})
            if not found:
                continue
            # `DETACH`, because an edge to a nonexistent node is not in the view
            # either. The `Link` rows behind those edges are claims and survive.
            self.engine.execute(graph, "MATCH (e) WHERE e.id = $node_uuid DETACH DELETE e", {"node_uuid": str(ref)})
            removed += 1
        return removed

    # ------------------------------------------------------------------ writer: edges

    def draw_edge(self, graph: Any, source_ref: str, target_ref: str, label: str, properties: Mapping[str, Any]) -> bool:
        set_clause = ", ".join(f"r.{self.validate_key(key)} = $p_{key}" for key in properties)
        params: dict[str, Any] = {f"p_{key}": value for key, value in properties.items()}
        params.update({"src": str(source_ref), "tgt": str(target_ref)})
        result = self.engine.execute(
            graph,
            f"""
            MATCH (s) WHERE s.id = $src
            MATCH (t) WHERE t.id = $tgt
            MERGE (s)-[r:{label}]->(t)
            {("SET " + set_clause) if set_clause else ""}
            RETURN id(r) as edge_id
            """,
            params,
        )
        # An unmatched endpoint yields no rows, so the `MERGE` never fired.
        return bool(result)

    def erase_edge(self, graph: Any, source_ref: str, target_ref: str, label: str, match: Mapping[str, Any] | None = None) -> None:
        match = dict(match or {})
        extra = "".join(f" AND r.{self.validate_key(key)} = $m_{key}" for key in match)
        params: dict[str, Any] = {f"m_{key}": value for key, value in match.items()}
        params.update({"src": str(source_ref), "tgt": str(target_ref)})
        self.engine.execute(
            graph,
            f"""
            MATCH (s)-[r:{label}]->(t)
            WHERE s.id = $src AND t.id = $tgt{extra}
            DELETE r
            """,
            params,
        )

    # ------------------------------------------------------------------ writer: keys

    def validate_key(self, key: str) -> str:
        """A property key has to be a bare identifier — it is interpolated into `SET e.{key}`."""
        if not _KEY.match(str(key)):
            raise ValueError(f"Invalid property key '{key}'.")
        return str(key)

    # ------------------------------------------------------------------ reader

    def drawn_nodes(self, graph: Any, refs: Iterable[str]) -> list[dict[str, Any]]:
        refs = [str(ref) for ref in refs]
        if not refs:
            return []
        if len(refs) == 1:
            rows = self.engine.execute(graph, "MATCH (n) WHERE n.id = $nid RETURN n", {"nid": refs[0]})
        else:
            rows = self.engine.execute(graph, "MATCH (n) WHERE n.id IN $nids RETURN n", {"nids": refs})
        return [row["n"] for row in rows]

    def drawn_edge(self, graph: Any, source_ref: str, target_ref: str, label: str) -> DrawnEdge | None:
        result = self.engine.execute(
            graph,
            f"""
            MATCH (s)-[r:{label}]->(t)
            WHERE s.id = $src AND t.id = $tgt
            RETURN id(r) as id, id(s) as sid, id(t) as tid
            """,
            {"src": str(source_ref), "tgt": str(target_ref)},
        )
        if not result:
            return None
        return DrawnEdge(edge_id=int(result[0]["id"]), left_id=int(result[0]["sid"]), right_id=int(result[0]["tid"]))

    def list_drawn(self, graph: Any, label: str, where: str, params: Mapping[str, Any], order: str, page: str) -> list[dict[str, Any]]:
        # `WHERE true` so the filter can be appended with AND.
        query = f"""
            MATCH (e:{label})
            WHERE true
            {("AND " + where) if where else ""}
            RETURN e
            {order}
            {page}
        """
        return [row["e"] for row in self.engine.execute(graph, query, dict(params))]

    def render_table(self, graph: Any, plan: Any, *, filters: Any = None, order: Any = None, pagination: Any = None) -> list[Any]:
        query, params = compile_table_plan(plan, filters=filters, order=order, pagination=pagination)
        return list(self.engine.execute(graph, query, params))

    def render(self, graph: Any, query: str, params: Mapping[str, Any]) -> list[Any]:
        return list(self.engine.execute(graph, query, dict(params)))


# ---------------------------------------------------------------------------
# Saved table queries: compiling a plan to Cypher.
# ---------------------------------------------------------------------------

_OPERATORS = {
    "EQUALS": "{lhs} = {rhs}",
    "NOT_EQUALS": "{lhs} <> {rhs}",
    "GREATER_THAN": "{lhs} > {rhs}",
    "LESS_THAN": "{lhs} < {rhs}",
    "GREATER_OR_EQUAL": "{lhs} >= {rhs}",
    "LESS_OR_EQUAL": "{lhs} <= {rhs}",
    "IN": "{lhs} IN {rhs}",
    "NOT_IN": "NOT {lhs} IN {rhs}",
    "CONTAINS": "toString({lhs}) CONTAINS toString({rhs})",
    "STARTS_WITH": "toString({lhs}) STARTS WITH toString({rhs})",
    "ENDS_WITH": "toString({lhs}) ENDS WITH toString({rhs})",
}


def _operator(name: Any) -> str:
    key = str(getattr(name, "value", name)).upper()
    if key not in _OPERATORS:
        raise ValueError(f"Unsupported where operator: {name}")
    return _OPERATORS[key]


def compile_table_plan(plan: Any, *, filters: Any = None, order: Any = None, pagination: Any = None) -> tuple[str, dict[str, Any]]:
    """Compile a `TableQueryPlan` (plus a render-time filter/order/page) to Cypher and parameters.

    Every value is a **parameter**; nothing client-supplied is interpolated except
    identifiers, and those are sanitized. Structure:

        MATCH / OPTIONAL MATCH <paths>          -- the plan's matches
        WHERE <plan predicates>                 -- the plan's wheres
        WITH <expr AS alias>, …                 -- the plan's returns
        WHERE <render filter on an alias>       -- renderGraphTable(filters:)
        RETURN <aliases>
        ORDER BY <alias> / SKIP / LIMIT         -- renderGraphTable(order:, pagination:)

    The `WITH` is what makes a render filter on a *returned alias* work — the
    natural thing a client filters on, since the aliases are what `columns[].key`
    names — where the old regex splice put the predicate before `RETURN`, out of
    the alias's scope. A node label is emitted when a path names a category for
    that node (`node_categories`), so a pattern can be constrained to a category
    rather than matching every vertex.
    """
    from graph_engine.query_ir import is_identifier, sanitize_identifier

    params: dict[str, Any] = {}
    matches = list(getattr(plan, "matches", []) or [])
    if not matches:
        raise ValueError("A table query plan needs at least one match path")

    path_nodes: dict[str, dict[str, str]] = {}
    default_path_node: dict[str, str] = {}
    match_clauses: list[str] = []

    for path_index, path in enumerate(matches):
        path_key = path.title or f"path_{path_index}"
        path_nodes[path_key] = {}
        if not path.nodes:
            raise ValueError(f"Match path '{path_key}' requires at least one node")

        node_vars: list[str] = []
        for node_index, node in enumerate(path.nodes):
            var_name = sanitize_identifier(f"{path_key}_{node}", f"n_{path_index}_{node_index}")
            node_vars.append(var_name)
            path_nodes[path_key][str(node)] = var_name
        default_path_node[path_key] = node_vars[0]

        labels = list(getattr(path, "node_categories", None) or [])

        def node_pattern(index: int) -> str:
            label = labels[index] if index < len(labels) else None
            if label:
                return f"({node_vars[index]}:{sanitize_identifier(label, 'Node')})"
            return f"({node_vars[index]})"

        pattern_parts = [node_pattern(0)]
        for rel_index in range(len(node_vars) - 1):
            relation_name = ""
            if path.relations and rel_index < len(path.relations):
                relation_name = sanitize_identifier(path.relations[rel_index], f"rel_{path_index}_{rel_index}")
            relation_fragment = f":{relation_name}" if relation_name else ""
            direction_out = True
            if path.relation_directions and rel_index < len(path.relation_directions):
                direction_out = bool(path.relation_directions[rel_index])
            arrow = f"-[{relation_fragment}]->" if direction_out else f"<-[{relation_fragment}]-"
            pattern_parts.append(f"{arrow}{node_pattern(rel_index + 1)}")

        clause = "OPTIONAL MATCH" if path.optional else "MATCH"
        match_clauses.append(f"{clause} {''.join(pattern_parts)}")

    def resolve(path_key: str, node: Any, what: str) -> str:
        var = None
        if node is not None:
            var = path_nodes.get(path_key, {}).get(str(node))
        if var is None:
            var = default_path_node.get(path_key)
        if var is None:
            raise ValueError(f"Unknown path/node reference in {what}: path={path_key}, node={node}")
        return var

    where_parts: list[str] = []
    for index, where in enumerate(getattr(plan, "wheres", []) or []):
        var = resolve(where.path, where.node, "where clause")
        if not is_identifier(where.property):
            raise ValueError(f"Invalid property key '{where.property}'.")
        param = f"w_{index}"
        params[param] = where.value
        where_parts.append(_operator(where.operator).format(lhs=f"{var}.{where.property}", rhs=f"${param}"))

    return_parts: list[str] = []
    aliases: list[str] = []
    for index, ret in enumerate(getattr(plan, "returns", []) or []):
        var = resolve(ret.path, ret.node, "return statement")
        requested = getattr(ret, "alias", None)
        if ret.property:
            if not is_identifier(ret.property):
                raise ValueError(f"Invalid property key '{ret.property}'.")
            alias = sanitize_identifier(requested or f"{ret.path}_{ret.node or 'node'}_{ret.property}_{index}", f"c_{index}")
            return_parts.append(f"{var}.{ret.property} AS {alias}")
        else:
            alias = sanitize_identifier(requested or f"{ret.path}_{ret.node or 'node'}_{index}", f"node_{index}")
            return_parts.append(f"{var} AS {alias}")
        aliases.append(alias)

    if not return_parts:
        for path_key, var in default_path_node.items():
            alias = sanitize_identifier(path_key, "node")
            return_parts.append(f"{var} AS {alias}")
            aliases.append(alias)

    lines = [*match_clauses]
    if where_parts:
        lines.append("WHERE " + " AND ".join(where_parts))
    lines.append("WITH " + ", ".join(return_parts))

    if filters is not None and getattr(filters, "key", None):
        key = str(filters.key)
        if not is_identifier(key):
            raise ValueError(f"Invalid property key '{key}'.")
        if key not in aliases:
            raise ValueError(f"Filter key '{key}' is not a returned alias of this query; returned: {', '.join(aliases)}")
        params["f_value"] = getattr(filters, "value", None)
        lines.append("WHERE " + _operator(getattr(filters, "operator", None) or "EQUALS").format(lhs=key, rhs="$f_value"))

    lines.append("RETURN " + ", ".join(aliases))

    if order is not None and getattr(order, "key", None):
        key = str(order.key)
        if key not in aliases:
            raise ValueError(f"Order key '{key}' is not a returned alias of this query; returned: {', '.join(aliases)}")
        direction = "DESC" if str(getattr(order, "direction", "asc")).lower() == "desc" else "ASC"
        lines.append(f"ORDER BY {key} {direction}")
    if pagination is not None:
        offset = getattr(pagination, "offset", None)
        limit = getattr(pagination, "limit", None)
        if offset is not None and int(offset) > 0:
            lines.append(f"SKIP {int(offset)}")
        if limit is not None:
            lines.append(f"LIMIT {int(limit)}")

    return "\n".join(lines), params
