from itertools import chain
import strawberry
from typing import Optional, List, Any
import re


# Factor out pagination logic into a separate function
def paginate_querysets(
    *querysets: Any,
    offset: int = 0,
    limit: int = 100,
):

    items = []
    remaining_limit = limit  # How many more items we need to fetch
    current_offset = offset  # Start at the initial offset

    # Loop through each queryset
    for qs in querysets:
        qs_count = qs.count()  # Get the total number of items in the current queryset

        # If the current offset is greater than the queryset size, skip this queryset
        if current_offset >= qs_count:
            current_offset -= qs_count
            continue

        # Calculate how many items to fetch from this queryset
        qs_items = qs[current_offset : current_offset + max(0, remaining_limit)]
        current_offset = (
            0  # After processing the first queryset, reset offset for the next one
        )

        # Append the fetched items to the results
        items.extend(qs_items)

        # Update the remaining limit after fetching from this queryset
        remaining_limit -= len(qs_items)

        # If we've filled the required limit, break the loop
        if remaining_limit <= 0:
            break

    # Return the paginated items and the total count
    return items


def node_id_to_graph_name(node_id: str) -> str:
    return str(node_id.split(":")[0])


def node_id_to_graph_id(node_id: str) -> str:
    return int(node_id.split(":")[1])


# re for the scalar string in format "@{exernal_name}/{scalar_name_without_spaces_and_only_alphanumber_with_underscores_and_hypens}"
scalar_string_re = re.compile(
    r"@(?P<external_name>[a-zA-Z0-9_]+)/(?P<scalar_name>[a-zA-Z0-9_]+):(?P<entity_id>[a-zA-Z0-9_]+)"
)


def scalar_string_to_graph_name(scalar_string: str) -> tuple[str, str, str]:
    """Parse a scalar string into its components.

    The scalar string is expected to be in the format:
    "@external_name/scalar_name:entity_id".

    The function will extract the external name, scalar name, and entity ID from the string.

    Params:
        scalar_string (str): The scalar string to parse.

    Returns:
        tuple: A tuple containing the graph name, the trimme identifier, and the last id

    """

    assert "@" in scalar_string, f"Invalid scalar string: {scalar_string}"
    assert "/" in scalar_string, f"Invalid scalar string: {scalar_string}"
    assert ":" in scalar_string, f"Invalid scalar string: {scalar_string}"
    assert scalar_string.count("@") == 1, f"Invalid scalar string: {scalar_string}"
    assert scalar_string.count("/") == 1, f"Invalid scalar string: {scalar_string}"
    assert scalar_string.count(":") == 1, f"Invalid scalar string: {scalar_string}"

    match = scalar_string_re.match(scalar_string)
    assert match, f"Invalid scalar string: {scalar_string}"

    external_name = match.group("external_name")
    scalar_name = match.group("scalar_name")
    entity_id = match.group("entity_id")

    identifier = scalar_string.split(":")[0]

    return (
        f"{external_name}_{scalar_name}".replace("-", "_").upper(),
        identifier,
        entity_id,
    )


def is_keyword(age_name) -> bool:
    """
    Check if the edge is a keyword.
    """
    keywords = [
        "describes",
        "measures",
    ]
    return age_name.lower() in keywords
