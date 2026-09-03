"""Writer-level claim helpers: who said what, and when.

The GraphQL helpers (`tests/writes.py`) speak as the request's context, which is
right for most tests and useless for these: a definition binds *subjects* and
*times*, so its tests need claims by named annotators at chosen moments.
`Assertion.asserted_at` is settable on purpose (`evidence/writer.py`) — belief
time is a fact about the claim, not about ingest.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from core import models as core_models
from evidence import models as evidence_models
from evidence import writer


def classify(graph: core_models.Graph, ref: str, category: core_models.Category, subject: str, asserted_at: datetime | None = None) -> Any:
    """One annotator's claim that a node is of a category, optionally back-dated."""
    assertion = writer.create_assertion(graph.organization, subject=subject, app_id="pytest", asserted_at=asserted_at)
    return writer.create_link(
        graph.organization,
        kind=evidence_models.Link.Kind.CLASSIFIES,
        source_ref=ref,
        target_ref=str(category.term_id),
        assertion=assertion,
        term=category.term,
    )


def retract_classifications(graph: core_models.Graph, ref: str) -> None:
    """Withdraw every standing classification of a node, as a claim.

    Through `writer.retract`, not a queryset `.update(stands=False)`. That used to
    work because `Link` carried its own cached answer, so a test could flip the
    projection with no `Standing` behind it — a shape nothing structurally prevented
    application code from copying. The column is gone and standing is folded from
    the log, so withdrawing a claim now means making one.
    """
    assertion = writer.create_assertion(graph.organization, subject="pytest", app_id="pytest")
    links = evidence_models.Link.objects.for_organization(graph.organization).filter(kind=evidence_models.Link.Kind.CLASSIFIES, source_ref=ref)
    for link in links:
        writer.retract(graph.organization, link, assertion)


# --- helpers for per-category trust (RFC 0009) -------------------------------


def _assertion(organization: Any, subject: str, app_id: str = "pytest", asserted_at: datetime | None = None) -> Any:
    return writer.create_assertion(organization, subject=subject, app_id=app_id, asserted_at=asserted_at)


def mint(organization: Any, word: str, subject: str, *, app_id: str = "pytest", asserted_at: datetime | None = None, kind: str = "ENTITY") -> str:
    """One annotator's observation: a fresh instance claimed under `word`, with
    the CLASSIFIES claim the same assertion carries. Returns the node ref."""
    term = writer.ensure_term(organization, kind, word)
    assertion = _assertion(organization, subject, app_id, asserted_at)
    node = evidence_models.Instance.objects.create_for_organization(
        organization=organization,
        kind=getattr(evidence_models.Instance.Kind, kind),
        term=term,
        assertion=assertion,
    )
    writer.create_link(organization, kind=evidence_models.Link.Kind.CLASSIFIES, source_ref=str(node.pk), target_ref=str(term.pk), assertion=assertion, term=term)
    return str(node.pk)


def relate(organization: Any, word: str, source_ref: str, target_ref: str, subject: str, *, app_id: str = "pytest", asserted_at: datetime | None = None) -> Any:
    """One annotator's relation claim under the organization's `word`."""
    term = writer.ensure_term(organization, "RELATION", word)
    assertion = _assertion(organization, subject, app_id, asserted_at)
    return writer.create_link(organization, kind=evidence_models.Link.Kind.RELATION, source_ref=str(source_ref), target_ref=str(target_ref), assertion=assertion, term=term)


def participate(organization: Any, event_word: str, entity_ref: str, event_ref: str, subject: str, *, role: str = "a", app_id: str = "pytest", asserted_at: datetime | None = None, output: bool = False, term_kind: str = "NATURAL_EVENT") -> Any:
    """One annotator's participation claim: entity → event, under the event's word."""
    term = writer.ensure_term(organization, term_kind, event_word)
    assertion = _assertion(organization, subject, app_id, asserted_at)
    kind = evidence_models.Link.Kind.PARTICIPATES_AS_OUTPUT if output else evidence_models.Link.Kind.PARTICIPATES_AS_INPUT
    return writer.create_link(organization, kind=kind, source_ref=str(entity_ref), target_ref=str(event_ref), assertion=assertion, term=term, role=role)


def retract_node(organization: Any, ref: str, subject: str, *, app_id: str = "pytest", asserted_at: datetime | None = None) -> Any:
    """One annotator's position that a node no longer exists."""
    assertion = _assertion(organization, subject, app_id, asserted_at)
    return writer.record_standing_for_ref(organization, target_type="node", target_id=str(ref), stands=False, assertion=assertion)


def measure(
    organization: Any,
    node_ref: str,
    *,
    structure_identifier: str = "ROI",
    obj: str,
    key: str,
    value: Any,
    value_kind: str = "FLOAT",
    subject: str,
    app_id: str = "pytest",
    asserted_at: datetime | None = None,
    measured_at: datetime | None = None,
    inform_subject: str | None = None,
    inform_asserted_at: datetime | None = None,
) -> Any:
    """A measurement against a structure that informs `node_ref`.

    The INFORMS link is its own claim, by `inform_subject` (default: the
    measurer) — trust in the routing and trust in the number are separable.
    """
    structure_kind = writer.ensure_structure_kind(organization, structure_identifier)
    assertion = _assertion(organization, subject, app_id, asserted_at)
    structure = writer.ensure_structure(organization, structure_kind, obj, assertion)
    metric_kind = writer.ensure_metric_kind(organization, structure_kind, key, value_kind)
    metric = writer.record_metric(organization, structure, metric_kind, key=key, value=value, assertion=assertion, measured_at=measured_at)
    inform_assertion = _assertion(organization, inform_subject or subject, app_id, inform_asserted_at or asserted_at)
    writer.create_link(organization, kind=evidence_models.Link.Kind.INFORMS, source_ref=str(structure.pk), target_ref=str(node_ref), assertion=inform_assertion)
    return metric


def structure(organization: Any, obj: str, subject: str, *, identifier: str = "ROI", app_id: str = "pytest") -> str:
    """A structure row for an external datum, as one assertion. Returns its pk."""
    kind = writer.ensure_structure_kind(organization, identifier)
    row = writer.ensure_structure(organization, kind, obj, _assertion(organization, subject, app_id))
    return str(row.pk)


def relate_structures(organization: Any, word: str, source_structure: str, target_structure: str, subject: str, *, app_id: str = "pytest", asserted_at: datetime | None = None) -> Any:
    """One annotator's structure-relation claim under the organization's `word`."""
    term = writer.ensure_term(organization, "STRUCTURE_RELATION", word)
    assertion = _assertion(organization, subject, app_id, asserted_at)
    return writer.create_link(organization, kind=evidence_models.Link.Kind.STRUCTURE_RELATION, source_ref=str(source_structure), target_ref=str(target_structure), assertion=assertion, term=term)


def measure_between(organization: Any, word: str, source_structure: str, entity_ref: str, subject: str, *, app_id: str = "pytest", asserted_at: datetime | None = None) -> Any:
    """One annotator's measurement claim: structure describes entity, under `word`."""
    term = writer.ensure_term(organization, "MEASUREMENT", word)
    assertion = _assertion(organization, subject, app_id, asserted_at)
    return writer.create_link(organization, kind=evidence_models.Link.Kind.MEASUREMENT, source_ref=str(source_structure), target_ref=str(entity_ref), assertion=assertion, term=term)
