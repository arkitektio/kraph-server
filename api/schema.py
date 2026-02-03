"""
GraphQL Schema for the API.

This module assembles the complete GraphQL schema from queries,
mutations, and subscriptions.
"""
import strawberry
from strawberry.extensions import QueryDepthLimiter
from typing import Optional

from .queries import Query
from .mutations import Mutation
from .subscriptions import Subscription


# Create the schema with subscription support
schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    subscription=Subscription,
    extensions=[
        QueryDepthLimiter(max_depth=10),
    ],
)


def create_schema(
    max_depth: int = 10,
    debug: bool = False,
    include_subscriptions: bool = True,
) -> strawberry.Schema:
    """
    Create a configured GraphQL schema for the graph engine.
    
    Args:
        max_depth: Maximum query depth (default 10)
        debug: Enable debug mode
        include_subscriptions: Whether to include subscriptions (default True)
        
    Returns:
        Configured Strawberry schema
    """
    extensions = [
        QueryDepthLimiter(max_depth=max_depth),
    ]
    
    if include_subscriptions:
        return strawberry.Schema(
            query=Query,
            mutation=Mutation,
            subscription=Subscription,
            extensions=extensions,
        )
    else:
        return strawberry.Schema(
            query=Query,
            mutation=Mutation,
            extensions=extensions,
        )


# Schema introspection helpers
def get_schema_sdl() -> str:
    """Get the GraphQL Schema Definition Language (SDL) for this schema."""
    return str(schema)


def print_schema():
    """Print the schema SDL to stdout."""
    print(get_schema_sdl())
