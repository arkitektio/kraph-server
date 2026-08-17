"""Comment query resolvers.

A comment is a claim, so these read the way `instance(id:)` and `link(id:)` do:
the evidence row itself, authorized from what the id points at, never from a
tenant the client names. `commentsFor` and `myMentions` mirror lok's komment
queries so a lok client can move over field-for-field.
"""

from typing import List

import strawberry
from kante.types import Info

from api import context, types
from evidence import models as evidence_models
from graph_engine import scalars


def comment(info: Info, id: scalars.GraphID) -> types.Comment:
    """One remark, as the log has it."""
    controller = context.get_controller()
    return controller._resolve_comment(str(id), info)  # type: ignore[return-value]


def comments_for(info: Info, identifier: str, object: strawberry.ID) -> List[types.Comment]:
    """Every remark about one external datum, newest first, resolved ones included.

    Addressed the way lok addresses a comment — `(identifier, object)` — which is
    a structure's identity, so this is `Structure.comments` for callers holding
    the datum's address rather than a structure id. A datum nobody has pointed at
    yet has no structure and therefore an empty discussion, which is an answer
    rather than an error.
    """
    organization = context.get_active_organization(info)
    structure = evidence_models.Structure.objects.for_organization(organization).filter(identifier=identifier, object=str(object)).first()
    if structure is None:
        return []
    return list(evidence_models.Comment.objects.for_organization(organization).filter(structure=structure).select_related("assertion").order_by("-created_at"))  # type: ignore[arg-type]


def my_mentions(info: Info) -> List[types.Comment]:
    """Every remark that mentions the caller, newest first.

    Matched on the caller's subject id — the same string the write path put into
    `mentions` when it walked the descendant tree, and the same one
    `Assertion.subject` records.
    """
    organization = context.get_active_organization(info)
    subject = str(info.context.request.user.id)
    return list(evidence_models.Comment.objects.for_organization(organization).filter(mentions__contains=[subject]).select_related("assertion").order_by("-created_at"))  # type: ignore[arg-type]
