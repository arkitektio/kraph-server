"""Curating the organization's vocabulary.

A `Term` is a word the organization uses — "AIS", "Mitosis", "IS_CONNECTED_TO" —
and it is what the evidence log names. A `Category` is one graph's rule for that
word: its Apache AGE label, its `definition`, its derivation rules, its layout.
Those stay per-graph and are edited through the category mutations; this edits
the word.

Unlike `structure_kind`, there **is** a create here. Structure kinds name data
owned by another service, so `@mikro/roi` is not a curator's to declare — it is
minted the first time a measurement mentions it and there is nothing to say about
it in advance. A term is an ontology entry: somebody may well want to give "AIS" a
description and a PURL before any graph declares a category for it.

Creating one is never *required*. `writer.ensure_term` mints a term the moment a
category declares the word or a claim names it, and it is a `get_or_create` on
`(organization, kind, key)` — so a term curated in advance is found and reused
rather than duplicated.
"""

import strawberry
from kante.types import Info

from api import context, inputs, types
from datalayer import models as datalayer_models
from evidence import models as evidence_models
from ._guards import delete_or_explain


def _resolve(info: Info, term_id: str) -> evidence_models.Term:
    """Fetch a term and check the caller may act for its organization."""
    term = evidence_models.Term.all_objects.filter(id=term_id).first()
    if term is None:
        raise ValueError(f"Term not found with id {term_id}")
    context.assert_can_access_organization(info, term.organization)
    return term


def _media_store(image: str | None) -> datalayer_models.MediaStore | None:
    return datalayer_models.MediaStore.objects.get(id=image) if image else None


def create_term(info: Info, input: inputs.CreateTermInput) -> types.Term:
    """Declare one of the organization's words.

    Idempotent by `(kind, key)`, because that is the term's identity and
    `ensure_term` is what mints it everywhere else. Declaring a word that already
    exists updates its description rather than failing — a curator filling in a
    PURL for a word some ingest minted bare is the expected use, not an error.
    """
    from evidence import writer

    model = input.to_pydantic()
    organization = context.get_active_organization(info)

    if model.color:
        assert len(model.color) in (3, 4), "Color must be a list of 3 or 4 values RGBA"

    term = writer.ensure_term(organization, model.kind, model.key)

    term.label = model.label or term.label
    term.description = model.description or term.description
    term.purl = model.purl or term.purl
    term.color = model.color or term.color
    term.image = _media_store(model.image) or term.image
    term.save()

    return term


def update_term(info: Info, input: inputs.UpdateTermInput) -> types.Term:
    """Edit how a word presents itself.

    Descriptive fields only. `kind` and `key` are the term's identity, and every
    claim ever recorded points at it — renaming would silently re-point all of
    them at a different word. Correcting a mistaken word means declaring the right
    one and re-classifying, which leaves both claims on the record. The database
    refuses an identity rewrite outright (evidence migration 0016, RFC 0022), so
    this is not a convention this resolver happens to keep.
    """
    model = input.to_pydantic()
    term = _resolve(info, str(model.id))

    if model.color:
        assert len(model.color) in (3, 4), "Color must be a list of 3 or 4 values RGBA"

    term.label = model.label or term.label
    term.description = model.description or term.description
    term.purl = model.purl or term.purl
    term.color = model.color or term.color
    term.image = _media_store(model.image) or term.image
    term.save()

    return term


def delete_term(info: Info, input: inputs.DeleteTermInput) -> strawberry.ID:
    """Retire a word nothing has been claimed under.

    `Instance.term` and `Link.term` are `PROTECT`, so a word in use cannot be removed
    and the refusal names what is in the way. That guard sits here rather than on
    `Category` deliberately: a category is one view's rule and deleting it is
    free, but the word every view's claims were recorded under has to outlive
    them.

    `Category.term` is `PROTECT` too, so a word a graph still declares is also
    refused — delete the category first, which takes no evidence with it.
    """
    model = input.to_pydantic()
    delete_or_explain(
        _resolve(info, str(model.id)),
        what="this term",
        instead="Retract the claims recorded under it, and delete the categories declaring it, first.",
    )
    return model.id
