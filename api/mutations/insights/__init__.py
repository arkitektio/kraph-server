"""Saved queries and plots.

One saved-query kind: the graph **table** query, saved as a plan
(`graph_engine/query_ir.py`). The node/edge families and the nodes/pairs/path
kinds had create/update/delete/archive mutations and no execution path anywhere;
they went with the contract becoming a plan.
"""

from .graph import (
    archive_graph_table_query,
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
    "create_scatter_plot",
    "update_scatter_plot",
    "delete_scatter_plot",
]
