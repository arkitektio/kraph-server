"""Todo lists: work somebody is asked to do over data, ticked off object by object.

Product state (C7), not evidence. These rows are edited in place — a card moved
across the board, an image ticked — and none of it is a claim about the world, so
none of it reaches the log: no `Assertion`, no `Standing`, no `Structure` row. An
object on an item is addressed the way a comment addresses one, by
``(identifier, object)``, but it is a plain pair here: minting a `Structure` for
it would write evidence.

People are named by their ``sub`` (the string `Assertion.subject` also carries),
not by a foreign key: whoever a list is assigned to may never have called kraph,
and a sub needs no user row to be named.
"""

from arkitekt_service.service.described import Described
from django.contrib.auth import get_user_model
from django.contrib.postgres.indexes import GinIndex
from django.db import models

from projects.models import Project


class TodoStatus(models.TextChoices):
    """The board's three columns."""

    TODO = "TODO", "To do"
    DOING = "DOING", "Doing"
    DONE = "DONE", "Done"


class TodoList(models.Model):
    """One list of items, usually handed to one person (its assignee)."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="todo_lists", help_text="The project the list belongs to")
    name = models.CharField(max_length=1000, help_text="The name of the list")
    description = models.TextField(null=True, blank=True, help_text="What the list is for")
    assignee = models.CharField(max_length=1000, null=True, blank=True, help_text="The sub of the user the list is assigned to; an item can name its own")
    due_at = models.DateTimeField(null=True, blank=True, help_text="When the list is due; an item can name its own")
    creator = models.ForeignKey(get_user_model(), on_delete=models.CASCADE, related_name="todo_lists", help_text="Who made the list")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["assignee"]),
            models.Index(fields=["project", "created_at"]),
        ]

    def __str__(self) -> str:
        return self.name


class TodoItem(Described):
    """One card on the board: something to do, over the objects attached to it."""

    list = models.ForeignKey(TodoList, on_delete=models.CASCADE, related_name="items")
    title = models.CharField(max_length=1000, help_text="What is to be done")
    description = models.TextField(null=True, blank=True, help_text="More about what is to be done")
    status = models.CharField(max_length=10, choices=TodoStatus.choices, default=TodoStatus.TODO, help_text="The board column the item is in")
    position = models.PositiveIntegerField(default=0, help_text="The item's place within its column, 0 first")
    assignee = models.CharField(max_length=1000, null=True, blank=True, help_text="The sub of the user this item is assigned to; the list's assignee when not set")
    due_at = models.DateTimeField(null=True, blank=True, help_text="When the item is due; the list's due date when not set")
    creator = models.ForeignKey(get_user_model(), on_delete=models.CASCADE, related_name="todo_items", help_text="Who made the item")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "created_at"]
        indexes = [
            models.Index(fields=["list", "status", "position"]),
            # `mine` / `assignee` (an item's own assignee, else its list's) and the "recently touched" order.
            models.Index(fields=["assignee"]),
            models.Index(fields=["list", "updated_at"]),
            models.Index(fields=["due_at"]),
            # What a trigger's `requires` reads (kraph_server/service.py: `@kraph/todoitem`).
            GinIndex(fields=["stored_descriptors"], name="todo_item_desc_gin", opclasses=["jsonb_path_ops"]),
        ]

    def __str__(self) -> str:
        return self.title


class TodoItemStructure(Described):
    """An object an item is about (an image to annotate), with its own To do / Doing / Done.

    `done` mirrors `status == DONE`: the board's tick and the progress count read it.
    """

    item = models.ForeignKey(TodoItem, on_delete=models.CASCADE, related_name="structures")
    identifier = models.CharField(max_length=1000, help_text="The object's structure identifier, e.g. @mikro/image")
    object = models.CharField(max_length=1000, help_text="The object's id within its structure")
    status = models.CharField(max_length=10, choices=TodoStatus.choices, default=TodoStatus.TODO, help_text="How far along this object is")
    started_at = models.DateTimeField(null=True, blank=True, help_text="When somebody started on it")
    started_by = models.CharField(max_length=1000, null=True, blank=True, help_text="The sub of who started on it")
    done = models.BooleanField(default=False, help_text="Whether this object has been dealt with")
    done_at = models.DateTimeField(null=True, blank=True, help_text="When it was ticked")
    done_by = models.CharField(max_length=1000, null=True, blank=True, help_text="The sub of who ticked it")
    position = models.PositiveIntegerField(default=0, help_text="The object's place on the item")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position", "id"]
        constraints = [models.UniqueConstraint(fields=["item", "identifier", "object"], name="todo_item_structure_unique")]
        indexes = [
            models.Index(fields=["identifier", "object"]),
            # Progress and `_settle` count an item's objects by status.
            models.Index(fields=["item", "status"]),
            GinIndex(fields=["stored_descriptors"], name="todo_object_desc_gin", opclasses=["jsonb_path_ops"]),
        ]

    def __str__(self) -> str:
        return f"{self.identifier}:{self.object}"
