from core import models, types, age, inputs
from .parser import render_cypher_template


def pairs(graph_query: models.GraphQuery, check_exists: bool = True, filters: inputs.GraphQueryFilters | None = None, pagination: inputs.GraphQueryPagination | None = None, order: inputs.GraphQueryOrder | None = None) -> types.Pairs:
    tgraph = graph_query.graph


    print("Called")

    tgraph = graph_query.graph

    rendered_query, params = render_cypher_template(graph_query.query, filters=filters, pagination=pagination, order=order)

    # First set the timeout
    real_query = f"""
    SELECT *
    FROM cypher(%s, $$
        {rendered_query}
    $$) as (n agtype, r agtype, m agtype);
    """

    print(real_query)

    pairs = []

    with age.graph_cursor() as cursor:
        cursor.execute(
            real_query,
            [tgraph.age_name],
        )
        all_results = cursor.fetchall()

        print("The result", all_results)

        # Convert AGTYPE (JSON string) to Python dict

        for result in all_results:
            pairs.append(
                types.Pair(
                    source=types.entity_to_node_subtype(age.vertex_ag_to_retrieved_entity(tgraph.age_name, result[0])),
                    edge=types.entity_to_node_subtype(age.edge_ag_to_retrieved_relation(tgraph.age_name, result[1])),
                    target=types.entity_to_node_subtype(age.vertex_ag_to_retrieved_entity(tgraph.age_name, result[2])),
                )
            )

        if check_exists:
            if not pairs:
                raise ValueError("No pairs found in the query result")

    return types.Pairs(pairs=pairs, graph=tgraph)
