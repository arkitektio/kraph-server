from typing import cast

import strawberry
from kante.types import Info

from api import inputs, types
from api.extensions.cypher import get_current_cypher_engine
from core import models
from graph_engine import materialize


def create_graph(
    info: Info,
    input: inputs.CreateGraphInput,
) -> types.Graph:
    """GraphQL mutation wrapper for creating graph."""

    model = input.to_pydantic()  # Validate input with Pydantic models

    cypher = get_current_cypher_engine()

    graph = materialize.materialize(
        definition=model.definition,
        engine=cypher,
        user=info.context.request.user,
        organization=info.context.request.organization,
        name=model.name,
        description=model.description,
        membership=info.context.request.membership,
    )

    return graph
