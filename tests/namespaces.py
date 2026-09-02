"""Catalog-level assertions about a graph's namespace.

Tests assert on the namespace the way an operator would meet it: through the
Postgres catalogs and `GRAPH_TABLE` itself, never by importing the projection
internals. The `graph_table` helper interpolates the graph's handle — which is
a generated identifier, not client input — and nothing else.
"""

from __future__ import annotations

from typing import Any

from django.db import connection


def schema_exists(name: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", [str(name)])
        return cursor.fetchone() is not None


def property_graph_labels(schema: str) -> set[str]:
    """Every label the schema's property graph declares."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT pgl.pgllabel
              FROM pg_propgraph_label pgl
              JOIN pg_class c ON c.oid = pgl.pglpgid
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE c.relkind = 'g' AND c.relname = 'graph' AND n.nspname = %s
            """,
            [str(schema)],
        )
        return {row[0] for row in cursor.fetchall()}


def graph_table(graph: Any, body: str, params: list[Any] | None = None) -> list[tuple[Any, ...]]:
    """Run one GRAPH_TABLE query against a graph's namespace and return its rows.

    `body` is everything inside the parentheses after the graph reference —
    `MATCH … COLUMNS (…)` — written by the test itself.
    """
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT * FROM GRAPH_TABLE ("{graph.age_name}".graph {body})', params or [])
        return list(cursor.fetchall())
