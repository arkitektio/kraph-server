"""Comment mutation resolvers.

The port of lok's komment writes, restated as evidence. `createComment` becomes
`commentOnStructure` — named for the act, like every write here — and the two
lok left unimplemented (`replyToComment`, `resolveComment`) arrive as what they
always were underneath: a reply is a comment whose input names a `parent`, and
resolving is a `Standing(stands=False)`, which is the same claim withdrawing
your own remark makes — the assertion records whose position it is.
"""

from kante.types import Info

from api import context, inputs, types


def comment_on_structure(
    info: Info,
    input: inputs.CommentOnStructureInput,
) -> types.AssertedComment:
    """Record a remark about an external datum, minting its structure if new.

    One act, one assertion — commenting on a datum nobody has pointed at yet
    introduces the structure and the remark together, the way `assertMetricValue`
    mints the structure for a first measurement. A reply names `parent` and must
    stay on its parent's thread.
    """
    controller = context.get_controller()
    organization = context.get_active_organization(info)

    return types.AssertedComment(
        _value=controller.comment_on_structure(
            organization=organization,
            payload=input.to_pydantic(),
            info=info,
        )
    )


def retract_comment(
    info: Info,
    input: inputs.RetractCommentInput,
) -> types.AssertedComment:
    """Claim a remark no longer stands — resolved by a reviewer or withdrawn by its author.

    One operation for both readings, deliberately: each is somebody's position
    that the remark no longer stands, and the standing's assertion records whose.
    The row survives; `Comment.resolved` folds to true.
    """
    controller = context.get_controller()
    model = input.to_pydantic()
    return types.AssertedComment(_value=controller.retract_comment(comment_id=str(model.id), info=info, at=model.at, confidence=model.confidence))


def attest_comment(
    info: Info,
    input: inputs.AttestCommentInput,
) -> types.AssertedComment:
    """Claim a remark stands again — reopening, as new evidence rather than an undo.

    Both positions stay on the record, newest first, exactly as they do for an
    entity that was retracted and re-attested.
    """
    controller = context.get_controller()
    model = input.to_pydantic()
    return types.AssertedComment(_value=controller.attest_comment(comment_id=str(model.id), info=info, at=model.at, confidence=model.confidence))
