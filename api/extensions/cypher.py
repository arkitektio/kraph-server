from contextvars import ContextVar
from strawberry.extensions import SchemaExtension
from graph_engine.engine.protocol import CypherEngine

cypher_engine: ContextVar = ContextVar("cypher_engine", default=None)


def get_current_cypher_engine() -> CypherEngine:
    """Retrieve the current CypherEngine from context."""
    return cypher_engine.get()


class CypherEngineExtension(SchemaExtension):
    """Strawberry extension to manage CypherEngine context per operation."""

    def __init__(self, engine: CypherEngine, *args, **kwargs) -> None:
        """Initialize with a CypherEngine instance."""
        super().__init__(*args, **kwargs)
        self.engine: CypherEngine = engine

    def on_operation(self):
        """An operation"""
        t1 = cypher_engine.set(self.engine)

        yield
        cypher_engine.reset(t1)

        print("GraphQL operation end")
