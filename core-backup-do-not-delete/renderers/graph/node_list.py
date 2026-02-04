from core import models, types, age, inputs
from .parser import render_cypher_template


def node_list(graph_query: models.GraphQuery, check_exists: bool = True, filters: inputs.GraphQueryFilters | None = None, pagination: inputs.GraphQueryPagination | None = None, order: inputs.GraphQueryOrder | None = None) -> types.NodeList:
    tgraph = graph_query.graph


    print("Called")

    tgraph = graph_query.graph

    rendered_query, params = render_cypher_template(graph_query.query, filters=filters, pagination=pagination, order=order)

    # First set the timeout
    real_query = f"""
    SELECT *
    FROM cypher(%s, $$
        {rendered_query}
    $$) as (n agtype);
    """

    print(real_query)

    nodes = []

    with age.graph_cursor() as cursor:
        cursor.execute(
            real_query,
            [tgraph.age_name],
        )
        all_results = cursor.fetchall()

        print("The result", all_results)

        # Convert AGTYPE (JSON string) to Python dict

        for result in all_results:
            nodes.append(types.entity_to_node_subtype(age.vertex_ag_to_retrieved_entity(tgraph.age_name, result[0])))
        if check_exists:
            if not nodes:
                raise ValueError("No nodes found in the query result")

    return types.NodeList(nodes=nodes, graph=tgraph)
