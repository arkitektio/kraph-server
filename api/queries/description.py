import strawberry
"""INFORMS claim query resolvers.

`descriptions(graph:)` is gone. It matched ``(m:Metric)-[r]->(s:Structure)``, and
`graph_engine/vocab.py` records that `Structure` and `Metric` are labels the
*reader* looks for and the writer never produces — structures and metrics stopped
being vertices entirely. So it could only ever return empty, which is the same
defect the `assertion`/`assertions` queries were deleted for.

What it was reaching for is answered from the evidence base and reads better
there: `Structure.informs` gives the nodes a structure is evidence for, and
`Entity.connections` gives the INFORMS claims reaching a node — both over the
whole component, neither needing a graph.
"""

from kante.types import Info

from api import context, types
from evidence import models as evidence_models


def description(info: Info, id: strawberry.ID) -> types.Description:
    """Fetch one description edge by the id of the claim that made it.

    Resolved from the `Link` row, not from Apache AGE. The id a client holds is
    that row's primary key — `RetrievedEdge.unique_id` returns it for every
    row-backed edge, which is all of them — and this used to split it on the first
    hyphen to recover a graph name and an integer AGE edge id. Given a uuid that
    yielded a graph named after its first segment and `int()` over the rest:
    `invalid literal for int() with base 10`, on the very id the API had just
    handed out.

    It could not be made to work by parsing harder. An AGE edge carries no claim
    id and cannot: `project_edges` merges every assertion of one proposition onto
    a single edge, which is the point — agreement is countable in the evidence and
    a traversal still sees one connection.
    """
    controller = context.get_controller()

    edge = controller.get_relation_by_id(str(id), info=info, kind=evidence_models.Link.Kind.INFORMS)
    if edge is None:
        raise ValueError(f"Description edge with ID {id} not found")

    return types.Description(_value=edge)
