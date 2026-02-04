from core import models, types, inputs


def pairs(
    node_query: models.NodeQuery,
    node_id: str,
    filters: inputs.NodeQueryFilters | None = None , pagination: inputs.NodeQueryPagination | None = None, order: inputs.NodeQueryOrder | None = None
) -> types.Pairs:

    tgraph = node_query.graph
    query = node_query.query

    raise NotImplementedError("Pairs view is not implemented yet")
