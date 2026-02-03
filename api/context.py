"""
Context utilities for the API.

This module provides context factories and utilities for integrating
the graph controller with the GraphQL request context.
"""
from dataclasses import dataclass
from typing import Protocol
from graph_engine.controller import GraphController
from graph_engine.engine.protocol import CypherEngine, GraphProtocol


class GraphEngineContext(Protocol):
    """Protocol for context objects that provide graph engine access."""
    graph_controller: GraphController


@dataclass
class GraphEngineContextData:
    """
    Context data for graph engine requests.
    
    This should be included in your GraphQL context to provide
    access to the graph controller.
    """
    graph_controller: GraphController
    
    @classmethod
    def create(
        cls,
        engine: CypherEngine,
        graph: GraphProtocol,
    ) -> "GraphEngineContextData":
        """Create context data from an engine and graph."""
        controller = GraphController(engine=engine, graph=graph)
        return cls(graph_controller=controller)


def get_controller_from_context(info) -> GraphController:
    """
    Extract the graph controller from a Strawberry Info context.
    
    Args:
        info: Strawberry Info object
        
    Returns:
        GraphController instance
        
    Raises:
        AttributeError: If controller not found in context
    """
    if hasattr(info.context, 'graph_controller'):
        return info.context.graph_controller
    
    if hasattr(info.context, 'request') and hasattr(info.context.request, 'graph_controller'):
        return info.context.request.graph_controller
    
    raise AttributeError(
        "GraphController not found in context. "
        "Ensure your context factory sets 'graph_controller' on the context object."
    )


def create_context_factory(engine: CypherEngine, graph: GraphProtocol):
    """
    Create a context factory function for use with Strawberry.
    
    Args:
        engine: The CypherEngine to use
        graph: The GraphProtocol to use
        
    Returns:
        A context factory function
        
    Example:
        ```python
        from strawberry.django.views import AsyncGraphQLView
        from api.context import create_context_factory
        
        context_factory = create_context_factory(engine, graph)
        
        class MyGraphQLView(AsyncGraphQLView):
            async def get_context(self, request, response):
                base_context = await super().get_context(request, response)
                graph_context = context_factory()
                base_context.graph_controller = graph_context.graph_controller
                return base_context
        ```
    """
    def factory():
        return GraphEngineContextData.create(engine, graph)
    return factory
