from api import context, inputs, types
import kante


def pin_node(
    info: kante.Info,
    input: inputs.PinNodeInput,
) -> types.Node:
    """
    Pin a node by its composite ID.

    Args:
        info: Strawberry Info context
        input: Composite ID of the node to pin (e.g., "1-abc123-def456-...")

    Returns:
        The pinned node
    """
    raise NotImplementedError("Pinning nodes is not implemented yet")
