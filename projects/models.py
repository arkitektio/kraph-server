"""Projects: the organization's anchor for a piece of work.

Product state (C7), not evidence — a project is named and renamed in place and
says nothing about the world, so it never reaches the log. Other apps hang their
rows off it (todo lists today; graphs are meant to follow) and point at it, never
the other way round: this app imports none of them.
"""

from authentikate.models import Organization
from django.contrib.auth import get_user_model
from django.db import models


class Project(models.Model):
    """One piece of work in an organization, e.g. one study or one round of annotation."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="projects")
    name = models.CharField(max_length=1000, help_text="The name of the project")
    description = models.TextField(null=True, blank=True, help_text="What the project is about")
    creator = models.ForeignKey(get_user_model(), on_delete=models.CASCADE, related_name="projects", help_text="Who made the project")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name
