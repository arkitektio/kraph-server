"""Writes to projects. Every write fetches its row through the request's organization first."""

import strawberry
from kante.types import Info

from api.context import get_active_organization
from projects import inputs, models, types


def fetch_project(info: Info, pk: int) -> models.Project:
    """The project ``pk`` of the request's organization, or an error naming it."""
    project = models.Project.objects.filter(pk=pk, organization=get_active_organization(info)).first()
    if project is None:
        raise ValueError(f"No project with id {pk} in this organization")
    return project


def create_project(info: Info, input: inputs.CreateProjectInput) -> types.Project:
    model = input.to_pydantic()
    return models.Project.objects.create(
        organization=get_active_organization(info),
        name=model.name,
        description=model.description,
        creator=info.context.request.user,
    )


def update_project(info: Info, input: inputs.UpdateProjectInput) -> types.Project:
    model = input.to_pydantic()
    project = fetch_project(info, model.id)
    project.name = model.name
    project.description = model.description
    project.save()
    return project


def delete_project(info: Info, input: inputs.ProjectIdInput) -> strawberry.ID:
    model = input.to_pydantic()
    fetch_project(info, model.id).delete()
    return strawberry.ID(str(model.id))
