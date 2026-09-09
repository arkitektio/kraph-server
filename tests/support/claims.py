"""Writer-level claim helpers: who said what, and when.

The GraphQL helpers (`tests/writes.py`) speak as the request's context, which is
right for most tests and useless for these: a definition binds *subjects* and
*times*, so its tests need claims by named annotators at chosen moments.
`Assertion.asserted_at` is settable on purpose (`evidence/writer.py`) — belief
time is a fact about the claim, not about ingest. `observed_at` is the other
axis (RFC 0015): when the world was as the claim says; every helper takes it
and leaves it at the assertion's time when not given. `confidence` (RFC 0016)
is the claimant's own number in [0, 1], None when they gave none.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from core import models as core_models
from evidence import models as evidence_models
from evidence import writer


def classify(graph: core_models.Graph, ref: str, category: core_models.Category, subject: str, asserted_at: datetime | None = None, *, observed_at: datetime | None = None, confidence: float | None = None) -> Any:
    """One annotator's claim that a node is of a category, optionally back-dated."""
    assertion = writer.create_assertion(graph.organization, subject=subject, app_id="pytest", asserted_at=asserted_at)
    return writer.create_link(
        graph.organization,
        kind=evidence_models.Link.Kind.CLASSIFIES,
        source_ref=ref,
        target_ref=str(category.term_id),
        assertion=assertion,
        term=category.term,
        observed_at=observed_at,
        confidence=confidence,
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


def mint(organization: Any, word: str, subject: str, *, app_id: str = "pytest", asserted_at: datetime | None = None, observed_at: datetime | None = None, confidence: float | None = None, kind: str = "ENTITY") -> str:
    """One annotator's observation: a fresh instance claimed under `word`, with
    the CLASSIFIES claim the same assertion carries. Returns the node ref.
    `observed_at` lands on both, as the controller writes them."""
    term = writer.ensure_term(organization, kind, word)
    assertion = _assertion(organization, subject, app_id, asserted_at)
    node = writer.create_instance(organization, kind=getattr(evidence_models.Instance.Kind, kind), term=term, assertion=assertion, observed_at=observed_at, confidence=confidence)
    writer.create_link(organization, kind=evidence_models.Link.Kind.CLASSIFIES, source_ref=str(node.pk), target_ref=str(term.pk), assertion=assertion, term=term, observed_at=observed_at, confidence=confidence)
    return str(node.pk)


def relate(organization: Any, word: str, source_ref: str, target_ref: str, subject: str, *, app_id: str = "pytest", asserted_at: datetime | None = None, observed_at: datetime | None = None, confidence: float | None = None) -> Any:
    """One annotator's relation claim under the organization's `word`."""
    term = writer.ensure_term(organization, "RELATION", word)
    assertion = _assertion(organization, subject, app_id, asserted_at)
    return writer.create_link(organization, kind=evidence_models.Link.Kind.RELATION, source_ref=str(source_ref), target_ref=str(target_ref), assertion=assertion, term=term, observed_at=observed_at, confidence=confidence)


def participate(
    organization: Any, event_word: str, entity_ref: str, event_ref: str, subject: str, *, role: str = "a", app_id: str = "pytest", asserted_at: datetime | None = None, observed_at: datetime | None = None, confidence: float | None = None, output: bool = False, term_kind: str = "NATURAL_EVENT"
) -> Any:
    """One annotator's participation claim: entity → event, under the event's word."""
    term = writer.ensure_term(organization, term_kind, event_word)
    assertion = _assertion(organization, subject, app_id, asserted_at)
    kind = evidence_models.Link.Kind.PARTICIPATES_AS_OUTPUT if output else evidence_models.Link.Kind.PARTICIPATES_AS_INPUT
    return writer.create_link(organization, kind=kind, source_ref=str(entity_ref), target_ref=str(event_ref), assertion=assertion, term=term, role=role, observed_at=observed_at, confidence=confidence)


def same(organization: Any, left_ref: str, right_ref: str, subject: str, *, app_id: str = "pytest", asserted_at: datetime | None = None, observed_at: datetime | None = None, confidence: float | None = None) -> Any:
    """One annotator's claim that two observations are one individual, folded
    into the organization-grain cache as the controller folds it."""
    from evidence import identity

    assertion = _assertion(organization, subject, app_id, asserted_at)
    link = writer.create_link(organization, kind=evidence_models.Link.Kind.SAME_AS, source_ref=str(left_ref), target_ref=str(right_ref), assertion=assertion, observed_at=observed_at, confidence=confidence)
    identity.merge(organization, str(left_ref), str(right_ref))
    return link


def different(organization: Any, left_ref: str, right_ref: str, subject: str, *, app_id: str = "pytest", asserted_at: datetime | None = None, observed_at: datetime | None = None, confidence: float | None = None) -> Any:
    """One annotator's claim that two observations are two individuals (RFC
    0019), folded into the organization-grain cache as the controller folds it."""
    from evidence import identity

    assertion = _assertion(organization, subject, app_id, asserted_at)
    link = writer.create_link(organization, kind=evidence_models.Link.Kind.DIFFERENT_FROM, source_ref=str(left_ref), target_ref=str(right_ref), assertion=assertion, observed_at=observed_at, confidence=confidence)
    identity.separate(organization, str(left_ref), str(right_ref))
    return link


def retract_link(organization: Any, link: Any, subject: str, *, app_id: str = "pytest", asserted_at: datetime | None = None, at: datetime | None = None) -> Any:
    """One annotator's position that a link claim no longer holds."""
    assertion = _assertion(organization, subject, app_id, asserted_at)
    return writer.record_standing_for_ref(organization, target_type="link", target_id=str(link.pk), stands=False, assertion=assertion, at=at)


def retract_node(organization: Any, ref: str, subject: str, *, app_id: str = "pytest", asserted_at: datetime | None = None, at: datetime | None = None, confidence: float | None = None) -> Any:
    """One annotator's position that a node no longer exists — `at` is when
    that took effect in the world (`Standing.at`), not when it was said."""
    assertion = _assertion(organization, subject, app_id, asserted_at)
    return writer.record_standing_for_ref(organization, target_type="node", target_id=str(ref), stands=False, assertion=assertion, at=at, confidence=confidence)


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
    observed_at: datetime | None = None,
    confidence: float | None = None,
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
    metric = writer.record_metric(organization, structure, metric_kind, key=key, value=value, assertion=assertion, observed_at=observed_at, confidence=confidence)
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


async def ensure_kind(graph: Any, identifier: str = "roi_test") -> Any:
    """The organization's kind for this datum identifier. No graph is involved —
    kinds are organization vocabulary — the graph only names the tenant."""
    kind, _ = await evidence_models.StructureKind.all_objects.aget_or_create(organization=graph.organization, identifier=identifier)
    return kind


def only_instance(graph: Any) -> Any:
    """The one instance the view's words admit — for tests that wrote exactly one."""
    from evidence import selector as selector_module

    return evidence_models.Instance.objects.for_organization(graph.organization).filter(term__in=selector_module.term_ids_for(graph)).get()


def structure_row(organization: Any, kind: Any, assertion: Any, object_id: str = "roi-1") -> Any:
    """A structure row to hang measurements off, written directly."""
    return evidence_models.Structure.objects.create_for_organization(organization=organization, kind=kind, identifier="@mikro/roi", object=object_id, assertion=assertion)


def metric_row(organization: Any, structure: Any, kind: Any, assertion: Any, *, value: float, observed_at: datetime, asserted_at: datetime) -> Any:
    """One measurement with both time axes set explicitly, written directly."""
    from core.enums import ValueKind

    return evidence_models.Metric.objects.create_for_organization(organization=organization, structure=structure, kind=kind, key="vector_length", value_kind=ValueKind.FLOAT.value, value_num=value, observed_at=observed_at, asserted_at=asserted_at, assertion=assertion)
