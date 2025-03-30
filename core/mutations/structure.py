from kante.types import Info
import strawberry
from core import types, models, age, inputs, scalars, enums, manager
import uuid
import datetime
import re


@strawberry.input
class StructureInput:
    structure: scalars.StructureString
    graph: strawberry.ID 
    context: inputs.ContextInput | None = strawberry.field(
        default=None, description="The context of the measurement"
    )


@strawberry.input
class DeleteStructureInput:
    id: scalars.NodeID


# re for the scalar string in format "@{exernal_name}/{scalar_name_without_spaces_and_only_alphanumber_with_underscores_and_hypens}"
scalar_string_re = re.compile(
    r"@(?P<external_name>[a-zA-Z0-9_]+)/(?P<scalar_name>[a-zA-Z0-9_]+):(?P<entity_id>[a-zA-Z0-9_]+)"
)


def scalar_string_to_graph_name(scalar_string: str) -> str:

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


def create_structure(
    info: Info,
    input: StructureInput,
) -> types.Structure:

    graph = models.Graph.objects.get(id=input.graph)

    age_name, identifier, object_id = scalar_string_to_graph_name(input.structure)

    category, created = models.StructureCategory.objects.get_or_create(
        age_name=manager.build_structure_age_name(identifier),
        graph=graph,
        defaults=dict(
            identifier=identifier,
        ),
    )

    structure = age.create_age_structure(
        category,
        object_id,
    )


    return types.Structure(_value=structure)


def delete_structure(
    info: Info,
    input: DeleteStructureInput,
) -> strawberry.ID:

    raise NotImplementedError("Not implemented yet")
