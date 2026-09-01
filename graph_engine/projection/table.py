"""The table projector — the one module that reads or writes the drawing's rows.

The drawing lives in two ordinary Postgres tables
(`graph_engine.models.ProjectionVertex` / `ProjectionEdge`), which makes the
projection *transactional with the evidence*: a write's draw commits in the
same transaction as its assertion, so in steady state the outbox settles with
the write and `lag` is structurally zero. Everything else about "the graph is
a projection" is unchanged — the rows are derived, rebuildable by `manage.py
reproject`, carry no foreign key that evidence or core depends on, and are
free to destroy.

Every piece of SQL the projection layer runs lives here, phrased once; the
controller and `graph_engine.projector` never see a query string
(`tests/projector/test_projector_protocol.py` enforces both directions). The
two entry points that *compile* — `list_drawn` over a
:class:`~graph_engine.projection.protocol.ListDrawnSpec` and `render_table`
over a `TableQueryPlan` — bind every client value as a parameter; the only
interpolated identifiers are sanitized aliases and table names from
`Model._meta`.

Property comparisons are jsonb-typed: the client value is JSON-encoded in
Python and cast with ``::jsonb``, so a number compares as a number and a
string as a string, with no per-type SQL. Text operators (`CONTAINS`,
`STARTS_WITH`, `ENDS_WITH`) compare the unwrapped scalar text (``->>`` /
``#>> '{}'``), case-sensitively, as the Cypher forms did.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from typing import Any

from django.db import connection

from graph_engine.projection.protocol import LIST_OPERATORS, DrawnEdge, ListDrawnSpec

_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: The record keys that live in real columns rather than in the `properties`
#: jsonb — the identity trio every drawn record carries.
_VIRTUAL_KEYS = ("id", "category_id", "type")


def _like_pattern(value: Any, *, prefix: str = "", suffix: str = "") -> str:
    """A LIKE pattern matching `value` literally, with optional wildcard ends."""
    escaped = str(value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"{prefix}{escaped}{suffix}"


class TableProjector:
    """Draws a view into the projection tables, keyed by the `Graph` row."""

    kind = "table"

    # ------------------------------------------------------------------ tables

    @property
    def _models(self):
        # Imported lazily so this module can be imported before Django apps load
        # (`api/schema.py` builds a projector at import time).
        from graph_engine import models

        return models

    def _vertex_table(self) -> str:
        return self._models.ProjectionVertex._meta.db_table

    def _edge_table(self) -> str:
        return self._models.ProjectionEdge._meta.db_table

    # ------------------------------------------------------------------ namespace

    def create_namespace(self, graph: Any) -> None:
        """Nothing to make: the namespace is the `graph` key on the rows."""

    def drop_namespace(self, graph: Any) -> None:
        self._models.ProjectionEdge.objects.filter(graph=graph).delete()
        self._models.ProjectionVertex.objects.filter(graph=graph).delete()

    # ------------------------------------------------------------------ writer: nodes

    def draw_node(self, graph: Any, ref: str, label: str, category_id: Any, kind: str) -> None:
        # Upsert on (graph, ref) — the unique constraint is the convergence the
        # protocol promises. Derived properties survive a redraw, exactly as the
        # Cypher `MERGE … SET` left them; a label move without a prior
        # `erase_nodes` converges here too (the row moves), where AGE would have
        # minted a duplicate vertex.
        self._models.ProjectionVertex.objects.update_or_create(
            graph=graph,
            ref=str(ref),
            defaults={"label": str(label), "category_pk": int(category_id) if category_id is not None else None, "kind": str(kind)},
        )

    def write_properties(self, graph: Any, ref: str, label: str, values: Mapping[str, Any]) -> bool:
        if not values:
            return True
        row = self._models.ProjectionVertex.objects.filter(graph=graph, ref=str(ref), label=str(label)).first()
        if row is None:
            return False
        for key, value in values.items():
            row.properties[self.validate_key(key)] = value
        row.save(update_fields=["properties"])
        return True

    def clear_properties(self, graph: Any, label: str, refs: Iterable[str], keys: Iterable[str]) -> None:
        owned = sorted({self.validate_key(key) for key in keys})
        refs = [str(ref) for ref in refs]
        if not owned or not refs:
            return
        rows = list(self._models.ProjectionVertex.objects.filter(graph=graph, label=str(label), ref__in=refs))
        for row in rows:
            for key in owned:
                row.properties.pop(key, None)
        self._models.ProjectionVertex.objects.bulk_update(rows, ["properties"])

    def erase_nodes(self, graph: Any, refs: Iterable[str]) -> int:
        refs = [str(ref) for ref in refs]
        if not refs:
            return 0
        # Edges go by FK cascade — the `DETACH` the protocol promises. The count
        # is vertices only, matching what the Cypher loop counted.
        queryset = self._models.ProjectionVertex.objects.filter(graph=graph, ref__in=refs)
        removed = queryset.count()
        queryset.delete()
        return removed

    # ------------------------------------------------------------------ writer: edges

    def draw_edge(self, graph: Any, source_ref: str, target_ref: str, label: str, properties: Mapping[str, Any]) -> bool:
        vertices = {str(row.ref): row for row in self._models.ProjectionVertex.objects.filter(graph=graph, ref__in=[str(source_ref), str(target_ref)])}
        source = vertices.get(str(source_ref))
        target = vertices.get(str(target_ref))
        if source is None or target is None:
            # An undrawn endpoint means nothing was written — the caller decides
            # whether that is worth a warning.
            return False
        edge, _ = self._models.ProjectionEdge.objects.get_or_create(graph=graph, source=source, target=target, label=str(label))
        if properties:
            for key, value in properties.items():
                edge.properties[self.validate_key(key)] = value
            edge.save(update_fields=["properties"])
        return True

    def erase_edge(self, graph: Any, source_ref: str, target_ref: str, label: str, match: Mapping[str, Any] | None = None) -> None:
        queryset = self._models.ProjectionEdge.objects.filter(graph=graph, source__ref=str(source_ref), target__ref=str(target_ref), label=str(label))
        if match:
            queryset = queryset.filter(properties__contains={self.validate_key(key): value for key, value in match.items()})
        queryset.delete()

    # ------------------------------------------------------------------ writer: keys

    def validate_key(self, key: str) -> str:
        """Identifier keys only — not a storage limit for jsonb, but the shared
        rule that keeps a property addressable by every projection kind."""
        if not _KEY.match(str(key)):
            raise ValueError(f"Invalid property key '{key}'.")
        return str(key)

    # ------------------------------------------------------------------ reader

    def _record(self, row: Any) -> dict[str, Any]:
        """A drawn record in the shape readers have always seen: `{id, label, properties}`."""
        properties = dict(row.properties or {})
        properties["id"] = str(row.ref)
        properties["category_id"] = row.category_pk
        properties["type"] = row.kind
        return {"id": int(row.pk), "label": row.label, "properties": properties}

    def drawn_nodes(self, graph: Any, refs: Iterable[str]) -> list[dict[str, Any]]:
        refs = [str(ref) for ref in refs]
        if not refs:
            return []
        return [self._record(row) for row in self._models.ProjectionVertex.objects.filter(graph=graph, ref__in=refs)]

    def drawn_edge(self, graph: Any, source_ref: str, target_ref: str, label: str) -> DrawnEdge | None:
        row = self._models.ProjectionEdge.objects.filter(graph=graph, source__ref=str(source_ref), target__ref=str(target_ref), label=str(label)).first()
        if row is None:
            return None
        return DrawnEdge(edge_id=int(row.pk), left_id=int(row.source_id), right_id=int(row.target_id))

    def list_drawn(self, graph: Any, spec: ListDrawnSpec) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"graph_pk": graph.pk, "label": str(spec.label)}
        clauses = ["v.graph_id = %(graph_pk)s", "v.label = %(label)s"]

        for index, predicate in enumerate(spec.predicates):
            clauses.append(self._predicate_sql("v", predicate, params, f"p{index}"))

        order_parts: list[str] = []
        for index, order in enumerate(spec.order):
            direction = "DESC" if order.descending else "ASC"
            if order.key == "__internal_id":
                order_parts.append(f"v.id {direction}")
            else:
                order_parts.append(f"{self._prop_jsonb('v', order.key, params, f'o{index}')} {direction}")

        params["offset"] = int(spec.offset)
        params["limit"] = int(spec.limit)
        sql = (
            f"SELECT v.id, v.ref::text AS ref, v.label, v.category_pk, v.kind, v.properties "
            f"FROM {self._vertex_table()} v WHERE {' AND '.join(clauses)}"
            + (f" ORDER BY {', '.join(order_parts)}" if order_parts else "")
            + " OFFSET %(offset)s LIMIT %(limit)s"
        )
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()

        records: list[dict[str, Any]] = []
        for pk, ref, label, category_pk, kind, properties in rows:
            properties = self._as_dict(properties)
            properties["id"] = str(ref)
            properties["category_id"] = category_pk
            properties["type"] = kind
            records.append({"id": int(pk), "label": label, "properties": properties})
        return records

    def render_table(self, graph: Any, plan: Any, *, filters: Any = None, order: Any = None, pagination: Any = None) -> list[Any]:
        sql, params = compile_table_plan_sql(self, plan, filters=filters, order=order, pagination=pagination)
        params["graph_pk"] = graph.pk
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            columns = [col[0] for col in cursor.description]
            # Every returned expression is jsonb, and Django configures the
            # driver with an *identity* json loader — so a cell arrives as JSON
            # text (a stored string keeps its quotes) and one decode is exact.
            return [{column: self._from_jsonb(value) for column, value in zip(columns, row)} for row in cursor.fetchall()]

    # ------------------------------------------------------------------ compiling

    @staticmethod
    def _as_dict(value: Any) -> dict[str, Any]:
        """A jsonb column as a dict, whether the driver parsed it or not."""
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, str):
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        return {}

    @staticmethod
    def _from_jsonb(value: Any) -> Any:
        """A jsonb result cell as a Python value.

        JSON text under the identity loader; already-parsed values (a driver
        configured differently) pass through untouched.
        """
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value
        return value

    def _prop_jsonb(self, var: str, key: str, params: dict[str, Any], slot: str) -> str:
        """The jsonb expression for a record property — column-backed for the identity trio."""
        key = self.validate_key(key)
        if key == "id":
            return f"to_jsonb({var}.ref::text)"
        if key == "category_id":
            return f"to_jsonb({var}.category_pk)"
        if key == "type":
            return f"to_jsonb({var}.kind)"
        params[f"k_{slot}"] = key
        return f"({var}.properties -> %(k_{slot})s)"

    def _prop_text(self, var: str, key: str, params: dict[str, Any], slot: str) -> str:
        """The text expression for a record property, unwrapped (no jsonb quotes)."""
        key = self.validate_key(key)
        if key == "id":
            return f"{var}.ref::text"
        if key == "category_id":
            return f"{var}.category_pk::text"
        if key == "type":
            return f"{var}.kind"
        params[f"k_{slot}"] = key
        return f"({var}.properties ->> %(k_{slot})s)"

    def _predicate_sql(self, var: str, predicate: Any, params: dict[str, Any], slot: str) -> str:
        """One `PropertyPredicate` as parameterized SQL over vertex alias `var`."""
        operator = str(getattr(predicate.operator, "value", predicate.operator)).upper()
        if operator not in LIST_OPERATORS:
            raise ValueError(f"Unsupported filter operator '{predicate.operator}'.")
        key = self.validate_key(predicate.key)

        if operator == "IS_NOT_NULL":
            if key == "id" or key == "type":
                return "TRUE"
            if key == "category_id":
                return f"{var}.category_pk IS NOT NULL"
            params[f"k_{slot}"] = key
            # Present-and-not-json-null, which is what `e.key IS NOT NULL` meant.
            return f"(({var}.properties -> %(k_{slot})s) IS NOT NULL AND ({var}.properties -> %(k_{slot})s) <> 'null'::jsonb)"

        return self._compare_sql(self._prop_jsonb(var, key, params, slot), self._prop_text(var, key, params, f"{slot}t"), operator, predicate.value, params, slot)

    @staticmethod
    def _compare_sql(jsonb_expr: str, text_expr: str, operator: str, value: Any, params: dict[str, Any], slot: str) -> str:
        """One comparison, jsonb-typed for ordering operators and text for the string ones."""
        placeholder = f"%(v_{slot})s"
        if operator in {"EQUALS", "NOT_EQUALS", "GREATER_THAN", "LESS_THAN", "GREATER_OR_EQUAL", "LESS_OR_EQUAL"}:
            symbol = {"EQUALS": "=", "NOT_EQUALS": "<>", "GREATER_THAN": ">", "LESS_THAN": "<", "GREATER_OR_EQUAL": ">=", "LESS_OR_EQUAL": "<="}[operator]
            params[f"v_{slot}"] = json.dumps(value)
            return f"{jsonb_expr} {symbol} {placeholder}::jsonb"
        if operator in {"IN", "NOT_IN"}:
            values = list(value) if isinstance(value, (list, tuple, set)) else [value]
            params[f"v_{slot}"] = json.dumps(values)
            clause = f"{jsonb_expr} <@ {placeholder}::jsonb"
            return clause if operator == "IN" else f"NOT ({clause})"
        if operator == "CONTAINS":
            params[f"v_{slot}"] = _like_pattern(value, prefix="%", suffix="%")
        elif operator == "STARTS_WITH":
            params[f"v_{slot}"] = _like_pattern(value, suffix="%")
        elif operator == "ENDS_WITH":
            params[f"v_{slot}"] = _like_pattern(value, prefix="%")
        else:
            raise ValueError(f"Unsupported filter operator '{operator}'.")
        return f"{text_expr} LIKE {placeholder}"


# ---------------------------------------------------------------------------
# Saved table queries: compiling a plan to SQL.
# ---------------------------------------------------------------------------


def compile_table_plan_sql(projector: TableProjector, plan: Any, *, filters: Any = None, order: Any = None, pagination: Any = None) -> tuple[str, dict[str, Any]]:
    """Compile a `TableQueryPlan` (plus a render-time filter/order/page) to SQL.

    The same contract `compile_table_plan` had for Cypher: every client value is
    a parameter, identifiers are sanitized, and the render filter lands on a
    *returned alias* — here by wrapping the compiled query so the alias is a
    real column in scope. Structure:

        SELECT <aliases> FROM (
            SELECT <expr AS alias>, …                 -- the plan's returns
            FROM (SELECT 1) AS _one
            <CROSS/LEFT JOIN one join tree per path>  -- the plan's matches
            WHERE <plan predicates>                   -- the plan's wheres
        ) AS _t
        WHERE <render filter on an alias>             -- renderGraphTable(filters:)
        ORDER BY <alias> / OFFSET / LIMIT             -- (order:, pagination:)

    Each match path becomes one join tree — vertex, edge, vertex, … with the
    connectivity and label constraints in its ON clause — hung off the `_one`
    seed row: `CROSS JOIN` for a required path, `LEFT JOIN … ON (…)` for an
    optional one, which is exactly `MATCH` versus `OPTIONAL MATCH`. Paths in a
    plan share no node variables (they are namespaced per path), so trees
    combine by product, as separate `MATCH` clauses did.

    A whole-node return is rendered as the drawn record —
    ``{id, label, properties}`` — so a saved query's rows look the same as any
    other read of the drawing.
    """
    from graph_engine.query_ir import is_identifier, sanitize_identifier

    params: dict[str, Any] = {}
    matches = list(getattr(plan, "matches", []) or [])
    if not matches:
        raise ValueError("A table query plan needs at least one match path")

    vertex_table = projector._vertex_table()
    edge_table = projector._edge_table()

    path_nodes: dict[str, dict[str, str]] = {}
    default_path_node: dict[str, str] = {}
    join_clauses: list[str] = []
    where_parts: list[str] = []

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
        conditions: list[str] = []
        tables: list[str] = []

        for node_index, var in enumerate(node_vars):
            tables.append(f"{vertex_table} {var}")
            conditions.append(f"{var}.graph_id = %(graph_pk)s")
            label = labels[node_index] if node_index < len(labels) else None
            if label:
                params[f"nl_{path_index}_{node_index}"] = str(label)
                conditions.append(f"{var}.label = %(nl_{path_index}_{node_index})s")

        for rel_index in range(len(node_vars) - 1):
            edge_var = sanitize_identifier(f"{path_key}_edge_{rel_index}", f"e_{path_index}_{rel_index}")
            tables.append(f"{edge_table} {edge_var}")
            conditions.append(f"{edge_var}.graph_id = %(graph_pk)s")
            if path.relations and rel_index < len(path.relations) and path.relations[rel_index]:
                params[f"el_{path_index}_{rel_index}"] = str(path.relations[rel_index])
                conditions.append(f"{edge_var}.label = %(el_{path_index}_{rel_index})s")
            direction_out = True
            if path.relation_directions and rel_index < len(path.relation_directions):
                direction_out = bool(path.relation_directions[rel_index])
            left, right = (node_vars[rel_index], node_vars[rel_index + 1]) if direction_out else (node_vars[rel_index + 1], node_vars[rel_index])
            conditions.append(f"{edge_var}.source_id = {left}.id")
            conditions.append(f"{edge_var}.target_id = {right}.id")

        tree = tables[0] if len(tables) == 1 else "(" + " CROSS JOIN ".join(tables) + ")"
        if path.optional:
            join_clauses.append(f"LEFT JOIN {tree} ON ({' AND '.join(conditions)})")
        else:
            join_clauses.append(f"CROSS JOIN {tree}")
            where_parts.extend(conditions)

    def resolve(path_key: str, node: Any, what: str) -> str:
        var = None
        if node is not None:
            var = path_nodes.get(path_key, {}).get(str(node))
        if var is None:
            var = default_path_node.get(path_key)
        if var is None:
            raise ValueError(f"Unknown path/node reference in {what}: path={path_key}, node={node}")
        return var

    for index, where in enumerate(getattr(plan, "wheres", []) or []):
        var = resolve(where.path, where.node, "where clause")
        if not is_identifier(where.property):
            raise ValueError(f"Invalid property key '{where.property}'.")
        operator = str(getattr(where.operator, "value", where.operator)).upper()
        slot = f"w{index}"
        where_parts.append(
            TableProjector._compare_sql(
                projector._prop_jsonb(var, where.property, params, slot),
                projector._prop_text(var, where.property, params, f"{slot}t"),
                operator,
                where.value,
                params,
                slot,
            )
        )

    def node_record(var: str) -> str:
        return f"jsonb_build_object('id', {var}.id, 'label', {var}.label, 'properties', coalesce({var}.properties, '{{}}'::jsonb) || jsonb_build_object('id', {var}.ref::text, 'category_id', {var}.category_pk, 'type', {var}.kind))"

    return_parts: list[str] = []
    aliases: list[str] = []
    for index, ret in enumerate(getattr(plan, "returns", []) or []):
        var = resolve(ret.path, ret.node, "return statement")
        requested = getattr(ret, "alias", None)
        if ret.property:
            if not is_identifier(ret.property):
                raise ValueError(f"Invalid property key '{ret.property}'.")
            alias = sanitize_identifier(requested or f"{ret.path}_{ret.node or 'node'}_{ret.property}_{index}", f"c_{index}")
            return_parts.append(f"{projector._prop_jsonb(var, ret.property, params, f'r{index}')} AS \"{alias}\"")
        else:
            alias = sanitize_identifier(requested or f"{ret.path}_{ret.node or 'node'}_{index}", f"node_{index}")
            return_parts.append(f'{node_record(var)} AS "{alias}"')
        aliases.append(alias)

    if not return_parts:
        for path_key, var in default_path_node.items():
            alias = sanitize_identifier(path_key, "node")
            return_parts.append(f'{node_record(var)} AS "{alias}"')
            aliases.append(alias)

    inner = f"SELECT {', '.join(return_parts)} FROM (SELECT 1) AS _one {' '.join(join_clauses)}"
    if where_parts:
        inner += f" WHERE {' AND '.join(where_parts)}"

    quoted = ", ".join(f'"{alias}"' for alias in aliases)
    lines = [f"SELECT {quoted} FROM ({inner}) AS _t"]

    if filters is not None and getattr(filters, "key", None):
        key = str(filters.key)
        if not is_identifier(key):
            raise ValueError(f"Invalid property key '{key}'.")
        if key not in aliases:
            raise ValueError(f"Filter key '{key}' is not a returned alias of this query; returned: {', '.join(aliases)}")
        operator = str(getattr(getattr(filters, "operator", None) or "EQUALS", "value", getattr(filters, "operator", None) or "EQUALS")).upper()
        lines.append(
            "WHERE "
            + TableProjector._compare_sql(f'_t."{key}"', f"(_t.\"{key}\" #>> '{{}}')", operator, getattr(filters, "value", None), params, "f")
        )

    if order is not None and getattr(order, "key", None):
        key = str(order.key)
        if key not in aliases:
            raise ValueError(f"Order key '{key}' is not a returned alias of this query; returned: {', '.join(aliases)}")
        direction = "DESC" if str(getattr(order, "direction", "asc")).lower() == "desc" else "ASC"
        lines.append(f'ORDER BY "{key}" {direction}')
    if pagination is not None:
        offset = getattr(pagination, "offset", None)
        limit = getattr(pagination, "limit", None)
        if offset is not None and int(offset) > 0:
            params["page_offset"] = int(offset)
            lines.append("OFFSET %(page_offset)s")
        if limit is not None:
            params["page_limit"] = int(limit)
            lines.append("LIMIT %(page_limit)s")

    return "\n".join(lines), params
