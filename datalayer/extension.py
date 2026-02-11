from typing import Generator
from strawberry.extensions import SchemaExtension

from datalayer.datalayer import datalayer
from datalayer.datalayer import Datalayer


class DatalayerExtension(SchemaExtension):
    """A datalayer extension for Strawberry GraphQL that manages the datalayer context during GraphQL operations. It sets up a new datalayer context at the beginning of each operation and resets it at the end, ensuring that the datalayer is properly managed throughout the lifecycle of a GraphQL request."""

    def on_operation(self) -> Generator[None, None, None]:
        """Set up a new datalayer context at the beginning of a GraphQL operation and reset it at the end."""
        t1 = datalayer.set(Datalayer())

        yield
        datalayer.reset(t1)
