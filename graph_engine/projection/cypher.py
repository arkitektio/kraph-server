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

    def render(self, graph: Any, query: str, params: Mapping[str, Any]) -> list[Any]:
        return list(self.engine.execute(graph, query, dict(params)))
