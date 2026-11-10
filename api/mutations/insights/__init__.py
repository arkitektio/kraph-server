"""Saved queries and plots.

Two saved-query kinds, each saved as a plan (`graph_engine/query_ir.py`): the graph
**table** query, and the **pairs** query whose runs are training sets. The node/edge
families and the old nodes/pairs/path kinds had create/update/delete/archive mutations
and no execution path anywhere; they went with the contract becoming a plan.
"""

from .graph import (
    archive_graph_table_query,
    create_graph_pairs_query,
    delete_graph_pairs_query,
    update_graph_pairs_query,
    create_graph_table_query,
    delete_graph_table_query,
    update_graph_table_query,
)
from .plots import (
    create_scatter_plot,
    delete_scatter_plot,
    update_scatter_plot,
)

__all__ = [
    "create_graph_table_query",
    "update_graph_table_query",
    "delete_graph_table_query",
    "archive_graph_table_query",
    "create_graph_pairs_query",
    "update_graph_pairs_query",
    "delete_graph_pairs_query",
    "create_scatter_plot",
    "update_scatter_plot",
    "delete_scatter_plot",
]
