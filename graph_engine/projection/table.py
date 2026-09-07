"""The table projector — the one module that reads or writes the drawing's rows.

The drawing lives in three ordinary Postgres tables
(`graph_engine.models.ProjectionVertex` / `ProjectionMember` / `ProjectionEdge`), which makes the
projection *transactional with the evidence*: a write's draw commits in the
same transaction as its assertion, so in steady state the outbox settles with
the write and `lag` is structurally zero. Everything else about "the graph is
a projection" is unchanged — the rows are derived, rebuildable by `manage.py
reproject`, carry no foreign key that evidence or core depends on, and are
free to destroy.

Every piece of SQL the projection layer runs lives here, phrased once — the
row DML, the namespace DDL (`refresh_namespace` spelling a
`graph_engine.namespace.NamespaceSpec` as schemas, views and one SQL/PGQ
property graph per graph), and the `GRAPH_TABLE` queries `render_table`
compiles; the controller and `graph_engine.projector` never see a query string
(`tests/projector/test_projector_protocol.py` enforces every direction). The
two entry points that *compile* — `list_drawn` over a
:class:`~graph_engine.projection.protocol.ListDrawnSpec` and `render_table`
over a `TableQueryPlan` — bind every client **value** as a parameter; the
interpolated identifiers are sanitized aliases, table names from
`Model._meta`, and (the one addition RFC 0006 sanctions) SQL/PGQ **labels**,
which the standard makes identifiers: a plan's label strings are resolved
against the graph's declared labels and the *category row's own value* is
interpolated, quoted whole — never the client's bytes. Namespace DDL
additionally interpolates `int()`-cast pks and quoted label literals, because
Postgres DDL takes no bind parameters at all.

Property comparisons are jsonb-typed: the client value is JSON-encoded in
Python and cast with ``::jsonb``, so a number compares as a number and a
string as a string, with no per-type SQL. Text operators (`CONTAINS`,
`STARTS_WITH`, `ENDS_WITH`) compare the unwrapped scalar text (``->>`` /
``#>> '{}'``), case-sensitively, as the Cypher forms did.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from django.db import connection

from graph_engine.projection.protocol import LIST_OPERATORS, DrawnEdge, ListDrawnSpec

_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _quote_ident(name: str) -> str:
    """A double-quoted SQL identifier, `""`-escaped. Refuses NUL bytes.

    Length is *not* checked here — the spec builder refuses over-long labels by
    name (`graph_engine.namespace`), which is a better error than a quote helper
    could give.
    """
    name = str(name)
    if "\x00" in name:
        raise ValueError("identifier contains a NUL byte")
    return '"' + name.replace('"', '""') + '"'


def _quote_literal(value: str) -> str:
    """A single-quoted SQL string literal, `''`-escaped. Refuses NUL bytes.

    Used only in namespace DDL, where the values are labels read from this
    database's own `Category` rows — `CREATE VIEW` cannot take bind parameters,
    so the literal is quoted here instead.
    """
    value = str(value)
    if "\x00" in value:
        raise ValueError("literal contains a NUL byte")
    return "'" + value.replace("'", "''") + "'"

#: The record keys that live in real columns rather than in the `properties`
#: jsonb — the identity trio every drawn record carries. `category_ids` is the
#: label rows (RFC 0019), one per category the vertex is drawn under.
_VIRTUAL_KEYS = ("id", "category_ids", "type")


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

    def _member_table(self) -> str:
        return self._models.ProjectionMember._meta.db_table

    def _label_table(self) -> str:
        return self._models.ProjectionLabel._meta.db_table

    # ------------------------------------------------------------------ namespace

    def refresh_namespace(self, graph: Any) -> None:
        """(Re)derive this graph's queryable namespace from its categories.

        One Postgres schema named by the graph's handle (`Graph.age_name`),
        holding one view per node category, one view per (edge label x admitted
        endpoint pair), and one SQL/PGQ property graph (inner name ``graph``)
        over them. Drop-and-recreate, wholesale: the namespace is a **derived
        artifact** — a pure function of the `Category` rows, exactly as the
        drawing is of the evidence — so rebuilding it is always safe and
        idempotent (RFC 0006). What it contains is decided by
        `graph_engine.namespace.namespace_spec`; this method only spells it.

        DDL is transactional in Postgres: called inside a category write's
        transaction, the namespace and the row change commit or roll back
        together, which is why there is no second staleness ledger.
        """
        from graph_engine.namespace import namespace_spec

        spec = namespace_spec(graph)
        statements = [f"DROP SCHEMA IF EXISTS {_quote_ident(spec.schema_name)} CASCADE"]
        statements.extend(compile_namespace_ddl(self, spec))
        with connection.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)

    def drop_namespace(self, graph: Any) -> None:
        # The schema first: it holds the property graph and views, whose
        # dependency tracking would otherwise refuse nothing here — but a
        # dropped graph must leave neither rows nor DDL behind, and no FK
        # cascade reaches DDL.
        with connection.cursor() as cursor:
            cursor.execute(f"DROP SCHEMA IF EXISTS {_quote_ident(str(graph.age_name))} CASCADE")
        self._models.ProjectionEdge.objects.filter(graph=graph).delete()
        self._models.ProjectionVertex.objects.filter(graph=graph).delete()

    def validate_plan(self, plan: Any) -> None:
        """Refuse a structurally invalid plan at save time.

        Compiles without a graph — full parse, alias and key validation, but no
        label resolution (labels are checked at render, where the view is known)
        and nothing executed.
        """
        compile_table_plan_sql(self, plan)

    # ------------------------------------------------------------------ writer: nodes

    def _vertex_for_member(self, graph: Any, ref: str) -> Any | None:
        """The vertex holding `ref` as a member, or None. Any member addresses the vertex (RFC 0018)."""
        member = self._models.ProjectionMember.objects.filter(graph=graph, ref=str(ref)).select_related("vertex").first()
        return member.vertex if member is not None else None

    def draw_node(self, graph: Any, ref: str, categories: Sequence[tuple[str, Any]], kind: str, members: Iterable[str]) -> None:
        # Upsert on (graph, ref) — the unique constraint is the convergence the
        # protocol promises. Derived properties survive a redraw, exactly as the
        # Cypher `MERGE … SET` left them; a label move without a prior
        # `erase_nodes` converges here too (the label rows are replaced), where
        # AGE would have minted a duplicate vertex.
        labels = {(str(label), int(category_id) if category_id is not None else None) for label, category_id in categories}
        if not labels:
            raise ValueError(f"a vertex is drawn under at least one category; {ref} was given none")
        members = sorted({str(member) for member in members} | {str(ref)})
        vertex, _ = self._models.ProjectionVertex.objects.update_or_create(graph=graph, ref=str(ref), defaults={"kind": str(kind)})
        # Labels: insert the new set **before** deleting the stale one. The
        # `projectionlabel_last_label_deletes_vertex` trigger (migration 0009)
        # takes a vertex the moment its last label goes, so a redraw that
        # deleted first would lose the vertex — and its properties — between
        # the two statements.
        held_labels = {(row.label, row.category_pk): row for row in self._models.ProjectionLabel.objects.filter(vertex=vertex)}
        self._models.ProjectionLabel.objects.bulk_create([self._models.ProjectionLabel(graph=graph, vertex=vertex, label=label, category_pk=category_pk) for label, category_pk in sorted(labels, key=lambda pair: (pair[0], pair[1] or 0)) if (label, category_pk) not in held_labels])
        stale = [row.pk for key, row in held_labels.items() if key not in labels]
        if stale:
            self._models.ProjectionLabel.objects.filter(pk__in=stale).delete()
        # The member list is replaced, not merged: a member that left the
        # individual (its sameness retracted, itself retracted) must stop
        # addressing this vertex. A member another vertex still holds is the
        # caller's ordering mistake — `erase_nodes` first — and the unique
        # constraint refuses it rather than silently re-homing the ref.
        self._models.ProjectionMember.objects.filter(vertex=vertex).exclude(ref__in=members).delete()
        held = {str(row) for row in self._models.ProjectionMember.objects.filter(vertex=vertex).values_list("ref", flat=True)}
        self._models.ProjectionMember.objects.bulk_create([self._models.ProjectionMember(graph=graph, vertex=vertex, ref=member) for member in members if member not in held])

    def write_properties(self, graph: Any, ref: str, values: Mapping[str, Any]) -> bool:
        if not values:
            return True
        row = self._vertex_for_member(graph, ref)
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
        rows = list(self._models.ProjectionVertex.objects.filter(graph=graph, labels__label=str(label), members__ref__in=refs).distinct())
        for row in rows:
            for key in owned:
                row.properties.pop(key, None)
        self._models.ProjectionVertex.objects.bulk_update(rows, ["properties"])

    def erase_nodes(self, graph: Any, refs: Iterable[str]) -> int:
        refs = [str(ref) for ref in refs]
        if not refs:
            return 0
        # Every vertex holding any of the refs as a member — erasing one
        # observation of an individual erases the individual's vertex, and the
        # caller redraws what remains. Edges go by FK cascade — the `DETACH` the
        # protocol promises. The count is vertices only, matching what the
        # Cypher loop counted.
        vertex_ids = list(self._models.ProjectionMember.objects.filter(graph=graph, ref__in=refs).values_list("vertex_id", flat=True).distinct())
        if not vertex_ids:
            return 0
        queryset = self._models.ProjectionVertex.objects.filter(graph=graph, pk__in=vertex_ids)
        removed = queryset.count()
        queryset.delete()
        return removed

    # ------------------------------------------------------------------ writer: edges

    def _endpoints(self, graph: Any, source_ref: str, target_ref: str) -> tuple[Any | None, Any | None]:
        """The vertices holding the two refs as members — either may be None."""
        held = {str(member.ref): member.vertex for member in self._models.ProjectionMember.objects.filter(graph=graph, ref__in=[str(source_ref), str(target_ref)]).select_related("vertex")}
        return held.get(str(source_ref)), held.get(str(target_ref))

    def draw_edge(self, graph: Any, source_ref: str, target_ref: str, label: str, properties: Mapping[str, Any]) -> bool:
        source, target = self._endpoints(graph, source_ref, target_ref)
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
        source, target = self._endpoints(graph, source_ref, target_ref)
        if source is None or target is None:
            return
        queryset = self._models.ProjectionEdge.objects.filter(graph=graph, source=source, target=target, label=str(label))
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

    @staticmethod
    def _record(pk: int, ref: str, kind: str, properties: dict[str, Any], labels: Iterable[tuple[str, Any]], members: Iterable[str]) -> dict[str, Any]:
        """A drawn record in the shape readers have always seen — `{id, label, properties}` — plus `labels` and `members`.

        `labels` is every (label, category pk) the vertex is drawn under; the
        record's `label` is the first label sorted, `properties["category_ids"]`
        the pks sorted (RFC 0019).
        """
        pairs = sorted((str(label), category_pk) for label, category_pk in labels)
        properties = dict(properties or {})
        properties["id"] = str(ref)
        properties["category_ids"] = sorted((category_pk for _, category_pk in pairs if category_pk is not None))
        properties["type"] = kind
        names = tuple(label for label, _ in pairs)
        return {"id": int(pk), "label": names[0] if names else "", "labels": names, "properties": properties, "members": tuple(sorted(str(member) for member in members))}

    def drawn_nodes(self, graph: Any, refs: Iterable[str]) -> dict[str, dict[str, Any]]:
        refs = [str(ref) for ref in refs]
        if not refs:
            return {}
        held = list(self._models.ProjectionMember.objects.filter(graph=graph, ref__in=refs).select_related("vertex"))
        vertices = {member.vertex_id: member.vertex for member in held}
        members_by_vertex: dict[int, list[str]] = {}
        for vertex_id, ref in self._models.ProjectionMember.objects.filter(vertex_id__in=list(vertices)).values_list("vertex_id", "ref"):
            members_by_vertex.setdefault(vertex_id, []).append(str(ref))
        labels_by_vertex: dict[int, list[tuple[str, Any]]] = {}
        for vertex_id, label, category_pk in self._models.ProjectionLabel.objects.filter(vertex_id__in=list(vertices)).values_list("vertex_id", "label", "category_pk"):
            labels_by_vertex.setdefault(vertex_id, []).append((label, category_pk))
        records = {vertex_id: self._record(vertex.pk, str(vertex.ref), vertex.kind, vertex.properties, labels_by_vertex.get(vertex_id, ()), members_by_vertex.get(vertex_id, ())) for vertex_id, vertex in vertices.items()}
        return {str(member.ref): records[member.vertex_id] for member in held}

    def drawn_edge(self, graph: Any, source_ref: str, target_ref: str, label: str) -> DrawnEdge | None:
        source, target = self._endpoints(graph, source_ref, target_ref)
        if source is None or target is None:
            return None
        row = self._models.ProjectionEdge.objects.filter(graph=graph, source=source, target=target, label=str(label)).first()
        if row is None:
            return None
        return DrawnEdge(edge_id=int(row.pk), left_id=int(row.source_id), right_id=int(row.target_id))

    def list_drawn(self, graph: Any, spec: ListDrawnSpec) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"graph_pk": graph.pk, "label": str(spec.label)}
        clauses = ["v.graph_id = %(graph_pk)s", f"EXISTS (SELECT 1 FROM {self._label_table()} l WHERE l.vertex_id = v.id AND l.label = %(label)s)"]

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
            f"SELECT v.id, v.ref::text AS ref, v.kind, v.properties, "
            f"(SELECT array_agg(l.label ORDER BY l.label) FROM {self._label_table()} l WHERE l.vertex_id = v.id) AS labels, "
            f"(SELECT array_agg(l.category_pk ORDER BY l.label) FROM {self._label_table()} l WHERE l.vertex_id = v.id) AS category_pks, "
            f"(SELECT array_agg(m.ref::text ORDER BY m.ref) FROM {self._member_table()} m WHERE m.vertex_id = v.id) AS members "
            f"FROM {self._vertex_table()} v WHERE {' AND '.join(clauses)}"
            + (f" ORDER BY {', '.join(order_parts)}" if order_parts else "")
            + " OFFSET %(offset)s LIMIT %(limit)s"
        )
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()

        return [self._record(pk, ref, kind, self._as_dict(properties), zip(labels or (), category_pks or ()), members or ()) for pk, ref, kind, properties, labels, category_pks, members in rows]

    def render_table(self, graph: Any, plan: Any, *, filters: Any = None, order: Any = None, pagination: Any = None) -> list[Any]:
        sql, params = compile_table_plan_sql(self, plan, graph=graph, filters=filters, order=order, pagination=pagination)
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

    def _category_ids_jsonb(self, var: str) -> str:
        """The vertex's category pks as a sorted jsonb array — the label rows (RFC 0019)."""
        return f"(SELECT COALESCE(jsonb_agg(l.category_pk ORDER BY l.category_pk), '[]'::jsonb) FROM {self._label_table()} l WHERE l.vertex_id = {var}.id AND l.category_pk IS NOT NULL)"

    def _prop_jsonb(self, var: str, key: str, params: dict[str, Any], slot: str) -> str:
        """The jsonb expression for a record property — column-backed for the identity trio."""
        key = self.validate_key(key)
        if key == "id":
            return f"to_jsonb({var}.ref::text)"
        if key == "category_ids":
            return self._category_ids_jsonb(var)
        if key == "type":
            return f"to_jsonb({var}.kind)"
        params[f"k_{slot}"] = key
        return f"({var}.properties -> %(k_{slot})s)"

    def _prop_text(self, var: str, key: str, params: dict[str, Any], slot: str) -> str:
        """The text expression for a record property, unwrapped (no jsonb quotes)."""
        key = self.validate_key(key)
        if key == "id":
            return f"{var}.ref::text"
        if key == "category_ids":
            return f"{self._category_ids_jsonb(var)}::text"
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
            if key == "category_ids":
                return f"EXISTS (SELECT 1 FROM {self._label_table()} l WHERE l.vertex_id = {var}.id AND l.category_pk IS NOT NULL)"
            params[f"k_{slot}"] = key
            # Present-and-not-json-null, which is what `e.key IS NOT NULL` meant.
            return f"(({var}.properties -> %(k_{slot})s) IS NOT NULL AND ({var}.properties -> %(k_{slot})s) <> 'null'::jsonb)"

        if key == "category_ids" and operator in {"EQUALS", "NOT_EQUALS", "IN", "NOT_IN"}:
            # Membership, not equality: "category_ids = 7" asks whether the
            # vertex is drawn under category 7, which is what every caller of
            # the old scalar `category_id` meant (RFC 0019).
            values = list(predicate.value) if isinstance(predicate.value, (list, tuple, set)) else [predicate.value]
            params[f"v_{slot}"] = [int(value) for value in values]
            clause = f"EXISTS (SELECT 1 FROM {self._label_table()} l WHERE l.vertex_id = {var}.id AND l.category_pk = ANY(%(v_{slot})s))"
            return clause if operator in {"EQUALS", "IN"} else f"NOT ({clause})"

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
# The namespace: compiling a NamespaceSpec to DDL.
# ---------------------------------------------------------------------------

#: The uniform property set every vertex element exposes. Identical across
#: labels on purpose: an unlabelled pattern variable spans all labels, so
#: `COLUMNS (v.__props)` must compile whatever the variable binds to.
_VERTEX_ELEMENT_PROPERTIES = "id AS __vid, ref::text AS __ref, label AS __label, category_pk AS __category_id, kind AS __kind, properties AS __props"
_EDGE_ELEMENT_PROPERTIES = "id AS __eid, properties AS __eprops"


def compile_namespace_ddl(projector: TableProjector, spec: Any) -> list[str]:
    """The DDL statements that build one graph's namespace from its spec.

    `CREATE SCHEMA`, one `CREATE VIEW` per element table, one
    `CREATE PROPERTY GRAPH`. No bind parameters — Postgres DDL takes none — so
    the interpolations are: quoted identifiers, quoted label literals read from
    this database's own `Category` rows (never client input), and integer pks
    cast through `int()`. The caller wraps these with the `DROP SCHEMA` that
    makes the rebuild wholesale.
    """
    schema = _quote_ident(spec.schema_name)
    graph_pk = int(spec.graph_pk)
    vertex_table = projector._vertex_table()
    edge_table = projector._edge_table()
    label_table = projector._label_table()

    statements = [f"CREATE SCHEMA {schema}"]

    # A vertex element table is the vertices drawn under one category — the
    # label rows say which (RFC 0019), so a vertex drawn under two categories
    # is a row of two element tables. That is what SQL/PGQ allows and what
    # `MATCH (a IS "Pyramidal")` and `MATCH (a IS "Excitatory")` both finding
    # the same cell means. Each row carries *its* label and category, so an
    # unlabelled pattern variable still binds one (label, category) per row.
    for vertex in spec.vertices:
        statements.append(
            f"CREATE VIEW {schema}.{_quote_ident(vertex.view_name)} AS "
            f"SELECT v.id, v.ref, l.label, l.category_pk, v.kind, v.properties "
            f"FROM {vertex_table} v JOIN {label_table} l ON l.vertex_id = v.id "
            f"WHERE v.graph_id = {graph_pk} AND l.category_pk = {int(vertex.category_pk)}"
        )

    for edge in spec.edges:
        statements.append(
            f"CREATE VIEW {schema}.{_quote_ident(edge.view_name)} AS "
            f"SELECT e.id, e.source_id, e.target_id, e.properties "
            f"FROM {edge_table} e "
            f"JOIN {label_table} s ON s.vertex_id = e.source_id "
            f"JOIN {label_table} t ON t.vertex_id = e.target_id "
            f"WHERE e.graph_id = {graph_pk} AND e.label = {_quote_literal(edge.label)} "
            f"AND s.category_pk = {int(edge.source_pk)} AND t.category_pk = {int(edge.target_pk)}"
        )

    vertex_views = {int(vertex.category_pk): vertex.view_name for vertex in spec.vertices}
    vertex_clauses = [
        f"{schema}.{_quote_ident(vertex.view_name)} AS {_quote_ident(vertex.view_name)} KEY (id) "
        f"LABEL {_quote_ident(vertex.label)} PROPERTIES ({_VERTEX_ELEMENT_PROPERTIES})"
        for vertex in spec.vertices
    ]
    edge_clauses = [
        f"{schema}.{_quote_ident(edge.view_name)} AS {_quote_ident(edge.view_name)} KEY (id) "
        f"SOURCE KEY (source_id) REFERENCES {_quote_ident(vertex_views[int(edge.source_pk)])} (id) "
        f"DESTINATION KEY (target_id) REFERENCES {_quote_ident(vertex_views[int(edge.target_pk)])} (id) "
        f"LABEL {_quote_ident(edge.label)} PROPERTIES ({_EDGE_ELEMENT_PROPERTIES})"
        for edge in spec.edges
    ]

    property_graph = f"CREATE PROPERTY GRAPH {schema}.graph"
    if vertex_clauses:
        property_graph += " VERTEX TABLES (" + ", ".join(vertex_clauses) + ")"
    if edge_clauses:
        property_graph += " EDGE TABLES (" + ", ".join(edge_clauses) + ")"
    statements.append(property_graph)

    return statements


# ---------------------------------------------------------------------------
# Saved table queries: compiling a plan to SQL.
# ---------------------------------------------------------------------------


#: The exposed-column suffixes every node variable carries out of its
#: GRAPH_TABLE — the uniform vertex element properties, one column each.
#: `__label`/`__category_id` are **singular here on purpose**: a pattern
#: variable binds one row of one element table, and an element table is one
#: category's view of the drawing (RFC 0019) — a vertex drawn under two
#: categories is two rows, each carrying its own label, so a rendered table's
#: `category_id` is the category the *match* went through, not the vertex's
#: whole set (that is `category_ids` on the drawn record).
_NODE_COLUMN_SUFFIXES = ("__vid", "__ref", "__label", "__category_id", "__kind", "__props")


def compile_table_plan_sql(projector: TableProjector, plan: Any, *, graph: Any = None, filters: Any = None, order: Any = None, pagination: Any = None) -> tuple[str, dict[str, Any]]:
    """Compile a `TableQueryPlan` (plus a render-time filter/order/page) to SQL.

    The execution path is the graph's **namespace**: each match path becomes one
    ``GRAPH_TABLE`` over the per-graph property graph (PostgreSQL 19 has no
    comma-joined path patterns in one clause), combined off a seed row —
    `CROSS JOIN` for a required path, `LEFT JOIN (…) ON TRUE` for an optional
    one, which is `MATCH` versus `OPTIONAL MATCH`; paths share no variables, so
    the product is exactly what separate `MATCH` clauses meant. Structure:

        SELECT <aliases> FROM (
            SELECT <return exprs>                       -- the plan's returns
            FROM (SELECT 1) AS _one
            CROSS JOIN GRAPH_TABLE ("g…".graph MATCH <path> COLUMNS (…)) AS _p0
            LEFT JOIN (SELECT * FROM GRAPH_TABLE (…)) AS _p1 ON TRUE
            WHERE <plan predicates over exposed columns> -- the plan's wheres
        ) AS _t
        WHERE <render filter on an alias>               -- renderGraphTable(filters:)
        ORDER BY <alias> / OFFSET / LIMIT               -- (order:, pagination:)

    Every client **value** is still a bind parameter. Labels are the one thing
    that cannot be: SQL/PGQ labels are identifiers, so with a `graph` in scope a
    plan's label strings are resolved against the namespace's declared labels
    (`graph_engine.namespace.declared_labels`) and the *category row's own
    value* is interpolated, quoted — never the client's bytes; an unknown label
    is refused by name, an honest upgrade over binding a parameter that matches
    nothing. Without a `graph` (save-time validation) the compile is structural:
    labels are length-guarded and quoted permissively, and nothing executes.

    A whole-node return is rebuilt as the drawn record —
    ``{id, label, properties}`` — so a saved query's rows look the same as any
    other read of the drawing.
    """
    from graph_engine.query_ir import is_identifier, sanitize_identifier

    params: dict[str, Any] = {}
    matches = list(getattr(plan, "matches", []) or [])
    if not matches:
        raise ValueError("A table query plan needs at least one match path")

    vertex_labels: frozenset[str] | None = None
    edge_labels: frozenset[str] | None = None
    if graph is not None:
        from graph_engine.namespace import declared_labels

        vertex_labels, edge_labels = declared_labels(graph)
        graph_ref = f"{_quote_ident(str(graph.age_name))}.graph"
    else:
        graph_ref = '"__unbound__".graph'

    def quote_label(label: str, declared: frozenset[str] | None, what: str) -> str:
        label = str(label)
        if "\x00" in label or len(label.encode()) > 63:
            raise ValueError(f"Invalid {what} label {label!r}.")
        if declared is not None and label not in declared:
            raise ValueError(f"Unknown {what} label {label!r}: this graph declares {', '.join(sorted(declared)) or 'none'}.")
        return _quote_ident(label)

    path_nodes: dict[str, dict[str, str]] = {}
    default_path_node: dict[str, str] = {}
    node_home: dict[str, str] = {}
    join_clauses: list[str] = []
    where_parts: list[str] = []

    for path_index, path in enumerate(matches):
        path_key = path.title or f"path_{path_index}"
        path_alias = f"_p{path_index}"
        path_nodes[path_key] = {}
        if not path.nodes:
            raise ValueError(f"Match path '{path_key}' requires at least one node")

        node_vars: list[str] = []
        for node_index, node in enumerate(path.nodes):
            var_name = sanitize_identifier(f"{path_key}_{node}", f"n_{path_index}_{node_index}")
            node_vars.append(var_name)
            path_nodes[path_key][str(node)] = var_name
            node_home[var_name] = path_alias
        default_path_node[path_key] = node_vars[0]

        labels = list(getattr(path, "node_categories", None) or [])
        pattern_parts: list[str] = []
        for node_index, var in enumerate(node_vars):
            label = labels[node_index] if node_index < len(labels) else None
            if label:
                pattern_parts.append(f"({var} IS {quote_label(label, vertex_labels, 'node')})")
            else:
                pattern_parts.append(f"({var})")
            if node_index < len(node_vars) - 1:
                rel_index = node_index
                relation = None
                if path.relations and rel_index < len(path.relations) and path.relations[rel_index]:
                    relation = str(path.relations[rel_index])
                edge = f"[IS {quote_label(relation, edge_labels, 'edge')}]" if relation else "[]"
                direction_out = True
                if path.relation_directions and rel_index < len(path.relation_directions):
                    direction_out = bool(path.relation_directions[rel_index])
                pattern_parts.append(f"-{edge}->" if direction_out else f"<-{edge}-")

        columns = ", ".join(f'{var}.{suffix} AS "{var}{suffix}"' for var in node_vars for suffix in _NODE_COLUMN_SUFFIXES)
        graph_table = f"GRAPH_TABLE ({graph_ref} MATCH {''.join(pattern_parts)} COLUMNS ({columns}))"
        if path.optional:
            join_clauses.append(f"LEFT JOIN (SELECT * FROM {graph_table}) AS {path_alias} ON TRUE")
        else:
            join_clauses.append(f"CROSS JOIN {graph_table} AS {path_alias}")

    def column(var: str, suffix: str) -> str:
        return f'{node_home[var]}."{var}{suffix}"'

    def prop_jsonb(var: str, key: str, slot: str) -> str:
        key = projector.validate_key(key)
        if key == "id":
            return f"to_jsonb({column(var, '__ref')})"
        if key == "category_id":
            return f"to_jsonb({column(var, '__category_id')})"
        if key == "type":
            return f"to_jsonb({column(var, '__kind')})"
        params[f"k_{slot}"] = key
        return f"({column(var, '__props')} -> %(k_{slot})s)"

    def prop_text(var: str, key: str, slot: str) -> str:
        key = projector.validate_key(key)
        if key == "id":
            return column(var, "__ref")
        if key == "category_id":
            return f"{column(var, '__category_id')}::text"
        if key == "type":
            return column(var, "__kind")
        params[f"k_{slot}"] = key
        return f"({column(var, '__props')} ->> %(k_{slot})s)"

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
                prop_jsonb(var, where.property, slot),
                prop_text(var, where.property, f"{slot}t"),
                operator,
                where.value,
                params,
                slot,
            )
        )

    def node_record(var: str) -> str:
        return (
            f"jsonb_build_object('id', {column(var, '__vid')}, 'label', {column(var, '__label')}, "
            f"'properties', coalesce({column(var, '__props')}, '{{}}'::jsonb) || "
            f"jsonb_build_object('id', {column(var, '__ref')}, 'category_id', {column(var, '__category_id')}, 'type', {column(var, '__kind')}))"
        )

    return_parts: list[str] = []
    aliases: list[str] = []
    for index, ret in enumerate(getattr(plan, "returns", []) or []):
        var = resolve(ret.path, ret.node, "return statement")
        requested = getattr(ret, "alias", None)
        if ret.property:
            if not is_identifier(ret.property):
                raise ValueError(f"Invalid property key '{ret.property}'.")
            alias = sanitize_identifier(requested or f"{ret.path}_{ret.node or 'node'}_{ret.property}_{index}", f"c_{index}")
            return_parts.append(f"{prop_jsonb(var, ret.property, f'r{index}')} AS \"{alias}\"")
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
