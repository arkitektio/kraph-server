"""Running pairs queries and registering trained models. Reading them is strawberry-django's (`datasets/types.py`)."""

import strawberry
from arkitekt_datalayer.models import BigFileStore
from arkitekt_datalayer.storage import flag_orphaned, stores_orphaned_by
from django.db import transaction
from django.db.models import RestrictedError
from kante.types import Info

from api.context import get_active_organization, get_controller
from api.mutations._scoped import scoped
from core import models as core_models
from datasets import inputs, logic, models, types


def run_pairs_query(info: Info, input: inputs.RunPairsQueryInput) -> types.PairsQueryRun:
    """Run a pairs query: its answer from the view's drawing, stored with where the drawing stood.

    `scoped` before anything is read: the query id arrives from the client, and the caller
    must be able to reach its view.
    """
    model = input.to_pydantic()
    query = scoped(info, core_models.GraphPairsQuery, model.query, what="pairs query")
    return logic.run_pairs_query(get_controller(), query, name=model.name, description=model.description, creator=info.context.request.user, info=info)


def delete_pairs_query_run(info: Info, input: inputs.DeletePairsQueryRunInput) -> strawberry.ID:
    """Delete a run. A run a model was trained on stays: the model's provenance would point at nothing."""
    model = input.to_pydantic()
    run = models.PairsQueryRun.objects.filter(id=model.id, organization=get_active_organization(info)).first()
    if run is None:
        raise ValueError(f"Run {model.id} not found")
    try:
        run.delete()
    except RestrictedError as error:
        trained = sorted(str(row) for row in error.restricted_objects)
        raise ValueError(f"Run {model.id} cannot be deleted: {', '.join(trained)} were trained on it. Delete those models first") from error
    return strawberry.ID(str(model.id))


def create_model(info: Info, input: inputs.CreateModelInput) -> types.Model:
    """Register a trained model: a finished big-file upload, and the run it learned from.

    The run is given, or a pairs query is named and run here (`auto`), so every model cites
    the same kind of exact record. Everything is fetched for the active organization, and the
    store must be finished: `finishBigfileUpload` is where the server checks what arrived,
    and nothing is registered that was not.
    """
    model = input.to_pydantic()
    organization = get_active_organization(info)
    if model.trained_on is not None and model.trained_on_query is not None:
        raise ValueError("A model is trained on a run or on a pairs query, not both: give `trainedOn` or `trainedOnQuery`")

    store = BigFileStore.objects.filter(id=model.store, organization=organization).first()
    if store is None:
        raise ValueError(f"Big file store {model.store} not found")
    if not store.populated:
        raise ValueError(f"Big file store {model.store} is not finished: finish its upload before registering a model with it")

    with transaction.atomic():
        trained_on = None
        if model.trained_on is not None:
            trained_on = models.PairsQueryRun.objects.filter(id=model.trained_on, organization=organization).first()
            if trained_on is None:
                raise ValueError(f"Run {model.trained_on} not found")
        elif model.trained_on_query is not None:
            query = scoped(info, core_models.GraphPairsQuery, model.trained_on_query, what="pairs query")
            trained_on = logic.run_pairs_query(
                get_controller(),
                query,
                name=f"{query.label} for {model.name}",
                description=f"Run for the model {model.name!r}",
                auto=True,
                creator=info.context.request.user,
                info=info,
            )

        return models.TrainedModel.objects.create(
            organization=organization,
            name=model.name,
            description=model.description,
            framework=model.framework,
            trained_on=trained_on,
            store=store,
            parameters=model.parameters,
            creator=info.context.request.user,
        )


def delete_model(info: Info, input: inputs.DeleteModelInput) -> strawberry.ID:
    """Delete a model; its weights are flagged orphaned for the datalayer's purge. The run it was trained on stays.

    The datalayer's two halves straddle the delete (`arkitekt_datalayer.storage`): the stores
    it leaves behind are collected before, while the cascade is still walkable, and flagged
    after, so a delete that raises flags nothing. `purge_orphaned_stores` re-checks that
    nothing references a store before it removes the bytes.
    """
    model = input.to_pydantic()
    found = models.TrainedModel.objects.filter(id=model.id, organization=get_active_organization(info)).first()
    if found is None:
        raise ValueError(f"Model {model.id} not found")
    with transaction.atomic():
        orphaned = stores_orphaned_by(found)
        found.delete()
        flag_orphaned(orphaned)
    return strawberry.ID(str(model.id))
