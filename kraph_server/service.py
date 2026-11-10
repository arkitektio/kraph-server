"""kraph as a service of the hub: the todo, pairs-query, run and model structures it hosts, and the signals it sends rekuest.

What is hosted and signalled is declared once, as data, in ``kraph_server.contract`` (``HOSTS``);
this module binds it to the models and to what computes their descriptors. Todos are product
state (C7), never evidence: no graph object is hosted here.

Saves and deletes signal by themselves (``model_signal``). What a save of the row does not see
is restored by the writer (``todos/resolvers.py``): an object ticked without its item moving
column (the item's counts), bulk writes, a list reassigned.
"""

from arkitekt_service.service import Service, organization_of
from django.db.models.signals import pre_save

from core import models as core_models
from datasets import logic as dataset_logic
from datasets import models as dataset_models
from kraph_server.contract import contract
from todos import models

service = Service("kraph", hosts=contract.description.hosts, description="The knowledge graph, and the organization's projects and todo lists.")


def _item_descriptors(item: models.TodoItem) -> dict:
    counts = item.structures.values_list("status", flat=True)
    statuses = list(counts)
    return {
        "@kraph/status": item.status,
        "@kraph/done": sum(1 for status in statuses if status == models.TodoStatus.DONE),
        "@kraph/total": len(statuses),
        "@kraph/list": str(item.list_id),
        "@kraph/project": str(item.list.project_id),
        "@kraph/assignee": item.assignee or item.list.assignee,
    }


def _object_descriptors(row: models.TodoItemStructure) -> dict:
    return {
        "@kraph/identifier": row.identifier,
        "@kraph/object": row.object,
        "@kraph/status": row.status,
        "@kraph/done_by": row.done_by,
        "@kraph/item": str(row.item_id),
        "@kraph/list": str(row.item.list_id),
        "@kraph/project": str(row.item.list.project_id),
    }


todo_item = service.structure(models.TodoItem, "@kraph/todoitem", describe=_item_descriptors)
todo_object = service.structure(models.TodoItemStructure, "@kraph/todoitemstructure", describe=_object_descriptors, whole=lambda row: row.item)
# A pairs query (an insight): created and edited through this proxy, so its descriptors follow
# its plan's ends; `restore_descriptors` fills in queries from before.
pairs_query = service.structure(core_models.GraphPairsQuery, "@kraph/pairsquery", describe=dataset_logic.pairs_query_descriptors)
# A run is never edited, so its descriptors are fixed at its one save.
pairs_run = service.structure(dataset_models.PairsQueryRun, "@kraph/pairsrun", describe=dataset_logic.pairs_run_descriptors)
# A model's descriptors read the dataset it cites, which is never edited either.
trained_model = service.structure(dataset_models.TrainedModel, "@kraph/model", describe=dataset_logic.model_descriptors)

# A save is announced only when it changes what a trigger can test. Every save is UPDATED to
# `model_signal`, so without this a Done item dragged within its column, renamed or rescheduled
# would tell every "item finished" trigger again. The row's descriptors as the database held them
# before the save are kept on the instance; a `restore` (no save) always passes: it only emits
# when it changed something.
_BEFORE = "_descriptors_before_save"


def _keep_before(sender, instance, raw: bool = False, **_) -> None:
    if raw or instance.pk is None:
        return
    setattr(instance, _BEFORE, type(instance)._base_manager.filter(pk=instance.pk).values_list("stored_descriptors", flat=True).first())


def _changed(instance, kind: str) -> bool:
    if kind != "UPDATED" or not hasattr(instance, _BEFORE):
        return True
    return getattr(instance, _BEFORE) != instance.stored_descriptors


pre_save.connect(_keep_before, sender=models.TodoItem, weak=False, dispatch_uid="kraph:todoitem:before")
pre_save.connect(_keep_before, sender=models.TodoItemStructure, weak=False, dispatch_uid="kraph:todoitemstructure:before")

item_signal = service.model_signal(todo_item, organization=organization_of("list.project.organization"), when=_changed)
object_signal = service.model_signal(todo_object, organization=organization_of("item.list.project.organization"), when=_changed)
