from kante.types import Info
import strawberry
from core import types, models, age, inputs, scalars, enums
import uuid
import datetime
import re


@strawberry.input
class MeasurementInput:
    structure: scalars.StructureString
    graph: strawberry.ID
    valid_from: datetime.datetime | None = None
    valid_to: datetime.datetime | None = None


@strawberry.input
class DeleteMeasurementInput:
    id: strawberry.ID


# re for the scalar string in format "@{exernal_name}/{scalar_name_without_spaces_and_only_alphanumber_with_underscores_and_hypens}"
scalar_string_re = re.compile(r"@(?P<external_name>[a-zA-Z0-9_]+)/(?P<scalar_name>[a-zA-Z0-9_]+)")



def scalar_string_to_graph_name(scalar_string: str) -> str:

    assert "@" in scalar_string, f"Invalid scalar string: {scalar_string}"
    assert "/" in scalar_string, f"Invalid scalar string: {scalar_string}"
    assert scalar_string.count("@") == 1, f"Invalid scalar string: {scalar_string}"
    assert scalar_string.count("/") == 1, f"Invalid scalar string: {scalar_string}"


    match = scalar_string_re.match(scalar_string)
    assert match, f"Invalid scalar string: {scalar_string}"

    external_name = match.group("external_name")
    scalar_name = match.group("scalar_name")

    return f"{external_name}_{scalar_name}".replace("-", "_").upper()



def create_measurement(
    info: Info,
    input: MeasurementInput,
) -> types.Entity:
    
    graph = models.Graph.objects.get(id=input.graph)



    x = scalar_string_to_graph_name(input.structure)

    structure_ontology, _ = models.Ontology.objects.get_or_create(name="Structures", defaults={"description": "Ontology for structures"})
    expression, _ = models.Expression.objects.update_or_create(label=x, ontology=structure_ontology,  defaults=dict(kind=enums.ExpressionKind.STRUCTURE,))
    linked_expression, _ = models.LinkedExpression.objects.update_or_create(expression=expression, graph=graph, defaults=dict(age_name=expression.age_name))


    id = age.create_age_entity(graph.age_name,linked_expression.age_name, name=input.structure)

    return types.Entity(_value=id)



def delete_measurement(
    info: Info,
    input: DeleteMeasurementInput,
) -> strawberry.ID:
    raise NotImplementedError("Not implemented yet")
    return input.id

