import json
import logging
import re
from typing import Iterable, Optional, Dict, Any, List

from kante.types import Info
from graph_engine import input_models
from graph_engine.input_models import (
    GraphDefinitionInput,
)
import uuid

from graph_engine.input_models import (
    MetricInput,
    ProvenanceContext,
    RelationInput,
)
from graph_engine.engine.protocol import CypherEngine
from graph_engine.retrieved import (
    RetrievedMetric,
    RetrievedNode,
    RetrievedEdge,
    RetrievedGraphTableRender,
    RetrievedStructure,
)
from graph_engine import results, retrieved
from authentikate.models import Membership
from core import enums, models
from graph_engine import input_models as inputs
from graph_engine import scalars
from django.db import transaction
from evidence import models as evidence_models
from evidence import claims as claims_module
from evidence import identity as identity_module
from evidence import selector as selector_module
from evidence import state as state_module
from evidence import writer

logger = logging.getLogger(__name__)


def _provenance_claims(request: Any) -> dict[str, Any]:
    """The action half of an assertion's provenance, from the request's token.

    `AuthentikateExtension` verifies the Rekuest provenance token and attaches it
    to the kante context — `request.provenance`, and `set_extension("provenance")`
    for the same object. So the claims are already there to be read; nothing here
    needs `KoherentExtension`, which only mirrors the same token into a contextvar
    for `koherent`'s own history signals.

    Returns empty when the request carried no token. That is the ordinary case for
    a human at a keyboard, and it must stay a claim like any other.

    **`action_name` gets no value, and that is not an oversight.** A provenance
    token attests *causation* — which assignation ran (`tsk`), under which agent,
    over which arguments (`ahs`) — and carries no human-readable name for the
    action anywhere in the chain; neither does `koherent.Task`, which is built
    from the same claims. So the `action_names` branch of every selector filter
    still has no source. Filter on `action_id` instead, which is real.

    The raw token is deliberately **not** stored. It is a single-use credential,
    and an evidence row outlives every reason to keep one.
    """
    provenance = None
    try:
        provenance = request.get_extension("provenance")
    except (AttributeError, ValueError):
        provenance = getattr(request, "_provenance", None)

    if provenance is None:
        return {}

    actor = getattr(provenance, "act", None)

    return {
        "action_id": provenance.tsk,
        "action_args": {
            # What the run was given. `ahs` is the hash of the canonicalized
            # arguments and `aha` the algorithm that produced it, so a verifier
            # can recompute it years later — which is the whole point of keeping
            # it beside the claim rather than trusting a log line.
            "args_hash": provenance.ahs,
            "args_hash_algorithm": provenance.aha,
            # The causal chain, so "what else did this run touch" and "who
            # ultimately asked for this" stay answerable from the assertion alone.
            "task": provenance.tsk,
            "parent_task": provenance.ptk,
            "root_task": provenance.rtk,
            "assigner": provenance.rcb,
            "caller": provenance.sub,
            "agent": getattr(actor, "sub", None),
            "agent_client_id": getattr(actor, "cid", None),
            "issuer": provenance.iss,
            "token_id": provenance.jti,
        },
    }


# `extract_node_id` / `extract_graph_id` used to sit here. They split an id on its
# first hyphen (or colon) to recover a graph name and an **integer Apache AGE
# vertex id**, from back when identity was the composite `{graph}:{vertex_id}`.
#
# Identity is a bare uuid now, and a uuid contains hyphens — so `extract_graph_id`
# handed back the uuid's *first segment* as a graph name and never raised. Their
# last five call sites were the `ids` filter of a Cypher-backed edge listing,
# where the resulting comparison against `age_name` was always false and the
# filter quietly answered "no matches" to ids the API had just issued. Those
# queries read `evidence.Link` now; see `api/queries/_edges.py`.


def _extract_props(raw_node: Any) -> Dict[str, Any]:
    """Extract properties from an AGE node, handling both dict and nested formats."""
    if isinstance(raw_node, dict):
        if "properties" in raw_node:
            return raw_node["properties"]
        return raw_node
    return {}


class GraphController:
    """Controller for interacting with the graph database."""

    def __init__(self, engine: CypherEngine, subject: str | None = None, app_id: str | None = None) -> None:
        """The GraphController is initialized with a CypherEngine instance for executing queries, and optional context for provenance tracking."""
        self.engine = engine
        self.subject = subject
        self.app_id = app_id

    def create_universal_id(self) -> scalars.GraphID:
        """Mint a durable identity for a node or an edge — a bare uuid.

        Typed `GraphID` because that is what every id in this API is now. It was
        `GlobalID`, a scalar whose two GraphQL fields required a vertex property
        nothing ever wrote.
        """
        return scalars.GraphID(str(uuid.uuid4()))

    def _create_assertion(self, organization: Any, context: ProvenanceContext) -> evidence_models.Assertion:
        """Record who is making this change, in the relational evidence base.

        Assertions used to be AGE vertices, one per graph, which meant the same
        claim had to be re-asserted in every projection that wanted to see it.
        They are organization-scoped rows now; the graph is only how we learn
        which organization the request is acting for.
        """
        return writer.create_assertion(
            organization,
            subject=context.subject,
            app_id=context.app_id,
            action_id=context.action_id,
            action_name=context.action_name,
            action_args=context.action_args or {},
        )

    def _provenance_from_info(self, info: Info) -> ProvenanceContext:
        """Who is making this change, and under which run.

        `subject` and `app_id` say *who*. The rest says *what caused it*, and comes
        from the Rekuest provenance token that `AuthentikateExtension` verifies and
        attaches to the kante context — no `KoherentExtension` and no
        `ProvenanceField` involved. `koherent` mirrors the same token into a
        contextvar for its history signals, and mounts that audit Django rows use
        `ProvenanceField` for that; evidence does not, because for instance data
        the `Assertion` *is* the provenance and two systems over the same rows
        would eventually disagree.

        **Fails open.** A request without a provenance header is unprovenanced,
        not unauthorized — a human labelling an ROI in the web annotator is not
        running an action, and refusing their claim for want of an assignation id
        would be refusing a fact on a bookkeeping technicality.
        """
        request = info.context.request

        user = getattr(request, "user", None)
        client = getattr(request, "client", None)

        if not user:
            raise ValueError("No authenticated user found in context")

        return ProvenanceContext(
            subject=str(user.id),
            app_id=str(client.id) if client else "unknown",
            **_provenance_claims(request),
        )

    def _ensure_query_access(self, graph: models.Graph, info: Info | None = None) -> None:
        """Check the caller may read through this view.

        It used to be `if info is None: return`, an unused local, and `return True`
        from a function annotated `-> None` — so every read that relied on it for
        tenancy had none, and the two API resolvers with no check of their own
        (`entities`, `renderGraphTable`) read any organization's rows by guessing a
        primary key.

        A graph belongs to one organization and the claims it draws belong to that
        organization, so the check is the same one `_assert_can_access` makes about a
        row: authorization comes from what the id points at, never from the request,
        because the client names a primary key and never names a tenant.
        """
        self._assert_can_access(graph.organization, info)

    def ensure_structure_kind(self, organization: Any, identifier: str) -> evidence_models.StructureKind:
        """The organization's term for a kind of external datum.

        Takes no graph and consults no permission. `@mikro/roi` is an identifier
        owned by the service that produced the datum, so there is nothing here to
        approve — and refusing a measurement because no graph had declared the
        term would be refusing a fact about the world on a bookkeeping
        technicality.
        """
        return writer.ensure_structure_kind(organization, identifier)

    def ensure_metric_kind(
        self,
        organization: Any,
        structure_kind: evidence_models.StructureKind,
        key: str,
        value_kind: Any,
    ) -> evidence_models.MetricKind:
        """The organization's term for a kind of measurement.

        The value kind is required and comes from the caller. Nothing here
        guesses it — see `writer.ensure_metric_kind`.
        """
        return writer.ensure_metric_kind(organization, structure_kind, key, value_kind)

    def ensure_term(self, organization: Any, kind: Any, key: str) -> evidence_models.Term:
        """The organization's word for a kind of thing.

        Takes no graph, for the same reason `ensure_structure_kind` does not: a
        claim names a word, and whether any view has declared a category for that
        word is a question about the views, asked when they are drawn. A write that
        insisted on a declared word could not state a fact the schema had not
        anticipated, which is the thing an evidence log exists to allow.

        ``kind`` is a `core.enums.CategoryKindChoices` value — that is what
        `Term.kind` holds, and it is deliberately **not** the same enum as
        `Instance.Kind` or `Link.Kind`, which are lowercase and narrower. A write
        supplies both: the word's kind here, and the row's kind where the row is
        made.
        """
        return writer.ensure_term(organization, kind, key)

    def _materialize_supporting_evidence(
        self,
        organization: Any,
        supporting_evidence: list[Any],
        assertion: evidence_models.Assertion,
        info: Info,
    ) -> tuple[list[tuple[Any, evidence_models.StructureKind, evidence_models.Structure]], list[evidence_models.Metric]]:
        """Write the structures and metrics backing a creation into Postgres.

        The shared path for `create_entity` and `create_event`. Nothing here
        touches AGE any more: structures and metrics are the base relation, and the
        caller separately projects whatever it needs into the graph.

        Takes the organization rather than a graph because that is all it ever
        used one for. Structures and metrics are organization-scoped evidence;
        there was never a projection in this function to name.
        """
        materialized_evidence: list[tuple[Any, evidence_models.StructureKind, evidence_models.Structure]] = []
        recorded_metrics: list[evidence_models.Metric] = []

        for evidence in supporting_evidence:
            structure_kind = self.ensure_structure_kind(organization, evidence.identifier)
            structure = writer.ensure_structure(
                organization,
                kind=structure_kind,
                object=evidence.object,
                assertion=assertion,
            )

            for measurement in evidence.metrics:
                metric_kind = self.ensure_metric_kind(
                    organization,
                    structure_kind,
                    measurement.key,
                    measurement.value_kind,
                )
                metric = writer.record_metric(
                    organization,
                    structure,
                    metric_kind,
                    key=measurement.key,
                    value=measurement.value,
                    assertion=assertion,
                    unit=measurement.unit,
                    confidence=measurement.confidence,
                    confidence_type=measurement.confidence_type,
                    measured_at=measurement.timestamp,
                )
                recorded_metrics.append(metric)

            materialized_evidence.append((evidence, structure_kind, structure))

        # Deliberately not folded into the state vector here. These metrics roll
        # up through INFORMS links that the caller has not created yet — the
        # entity does not exist at this point — so folding now would find no
        # entity to attribute them to and silently derive nothing.
        return materialized_evidence, recorded_metrics

    def create_entity(
        self,
        organization: Any,
        term: evidence_models.Term,
        payload: inputs.EntityInput,
        info: Info,
    ) -> results.Asserted:
        """Claim that an entity exists, and that it is of a word.

        Names a **term**, not a graph's category for one. Creating an entity is a
        claim about the world — "there is an AIS here" — and the organization is who
        holds it. Which views draw it is answered afterwards, by their own rules,
        and may be several or none.

        It used to take an `EntityCategory`, and so a graph, which it reduced to
        that category's term and its graph's organization before writing anything.
        The effect was that a fact could not be stated until some view had been
        built to hold it, and that the caller's choice of view leaked into a claim
        that says nothing about views.

        Args:
            organization: Whose evidence this is — the request's active organization
            term: The organization's word for what is being claimed
            payload: The entity input, including any supporting evidence
            info: Strawberry info, for provenance
        """
        supporting_evidence = payload.supporting_evidence or []

        # Evidence first, in one transaction. AGE cannot join a Django
        # transaction — the engine runs on independent cursors — so the two
        # stores commit separately by construction. That asymmetry is deliberate
        # rather than a bug to compensate for: evidence is the source of truth,
        # so a failure after this commit leaves durable evidence with no
        # projection, and `reproject` (M3) picks it up. Do not "fix" this by
        # deleting the evidence when the AGE write fails.
        with transaction.atomic():
            assertion = self._create_assertion(organization, self._provenance_from_info(info))
            materialized_evidence, recorded_metrics = self._materialize_supporting_evidence(
                organization=organization,
                supporting_evidence=supporting_evidence,
                assertion=assertion,
                info=info,
            )

        # The entity's own uuid, and nothing else. Never the AGE vertex id —
        # those are assigned by AGE and change when a graph is dropped and
        # replayed, so keying evidence on one would leave every link dangling
        # after precisely the operation `reproject` performs. And no graph
        # prefix either: which views show this entity is a question their
        # derivation rules answer, not something its name decides.
        ref_id = self.create_universal_id()
        claim_ref = str(ref_id)

        with transaction.atomic():
            # That an entity exists is itself a claim, so it is evidence. Without
            # this row an entity with no metrics yet would simply vanish on
            # rebuild, and `reproject` could not honestly reconstruct the graph.
            #
            # **Written before the vertex, and that ordering is load-bearing.**
            # AGE cannot join a Django transaction, so one of the two orderings
            # has to be the recoverable one. This way a crash in between leaves
            # evidence with no projection, which `reproject` fixes. The other way
            # round left a vertex the log had never heard of — still queryable,
            # still resolvable to a ref, so relations could be written naming a
            # node that did not exist, and those links then dangled forever.
            evidence_models.Instance.objects.create_for_organization(
                organization=organization,
                id=claim_ref,
                kind=evidence_models.Instance.Kind.ENTITY,
                term=term,
                assertion=assertion,
            )

            # What kind of thing this is, as a claim. The term on the row above
            # stays as the originating one — `rebuild` still needs a word to fall
            # back on for a node nothing has classified — but it is no longer the
            # only answer, which is what lets a second annotator disagree without
            # having to create a second entity.
            writer.create_link(
                organization,
                kind=evidence_models.Link.Kind.CLASSIFIES,
                source_ref=claim_ref,
                target_ref=str(term.pk),
                assertion=assertion,
                term=term,
            )

            # Which structures justify this entity is a claim about the world and
            # outlives any graph built from it, so the INFORMS link is evidence.
            for _, _, structure in materialized_evidence:
                writer.create_link(
                    organization,
                    kind=evidence_models.Link.Kind.INFORMS,
                    source_ref=str(structure.pk),
                    target_ref=claim_ref,
                    assertion=assertion,
                )

            # Now that the links exist, the metrics have somewhere to roll up to.
            for metric in recorded_metrics:
                state_module.merge(metric, [claim_ref])

            # "This is AIS 6": the same act that minted the instance also says
            # which instance it is. Inside this transaction and under this
            # assertion, because a set of claims made together by one actor is
            # one assertion — and `Assertion.action_id`, the field that would tie
            # two calls back together, is never populated.
            for other_ref in getattr(payload, "same_as", ()) or ():
                self._claim_same_instance(organization, claim_ref, str(other_ref), assertion, info)

        # And only now the projection — into **every** view that declares the word
        # this entity was claimed under. Two graphs that both declare "AIS" both
        # contain it, so drawing it in one would leave the other disagreeing with
        # its own replay: `rebuild` reads the same claims and would create the
        # vertex there too.
        #
        # `reproject_node` is what `rebuild` uses per node, so a fresh entity and
        # a replayed one cannot differ.
        from graph_engine import projector

        node = evidence_models.Instance.objects.for_organization(organization).select_related("term").get(pk=claim_ref)
        for target_graph in projector.graphs_for_refs(organization, [claim_ref]):
            projector.reproject_node(self, target_graph, node)

        # Read back *after* every projection, not inside the loop: `drawings` is
        # where the claim stands once the act is complete.
        return results.Asserted.of(assertion, node, self.drawings_for_instance(node))

    # ===================================================================
    # Projection
    # ===================================================================

    def project_entities(self, graph: models.Graph, instance_refs: List[str]) -> int:
        """Recompute derived properties for the named entities.

        The replacement for the old per-fact recalculation. Batched by design: a
        bulk ingest emits one dirty set and one projection pass, where the
        previous scheme re-derived once per metric.
        """
        from graph_engine import projector

        return projector.project(self, graph, instance_refs)

    def project_refs(self, organization: Any, instance_refs: List[str]) -> int:
        """Recompute the named entities, whichever graphs they belong to.

        Which graphs those are is a question for the evidence base — refs are
        bare uuids, so there is no prefix to read it off. A ref that belongs to
        no graph simply contributes nothing: it is an edge ref, or a node whose
        graph has been deleted, and evidence outlives the projections built from
        it by design.
        """
        from graph_engine import projector

        projected = 0
        for graph, refs in projector.graphs_for_refs(organization, instance_refs).items():
            projected += projector.project(self, graph, refs)
        return projected

    def project_from_structures(self, organization: Any, structure_ids: List[Any]) -> int:
        """Recompute every entity in the organization these structures are evidence for.

        Spans graphs deliberately. Evidence is shared, so a measurement has to
        reach every projection that reads it — refreshing only the graph the
        caller happened to name is what left second projections stale.
        """
        from graph_engine import projector

        return self.project_refs(organization, projector.refs_informed_by(organization, structure_ids))

    def rebuild_projection(self, graph: models.Graph) -> Dict[str, int]:
        """Drop this graph's AGE namespace and replay it from evidence."""
        from graph_engine import projector

        return projector.rebuild(self, graph)

    def backfill_category(self, category: models.Category) -> Dict[str, int]:
        """Draw the evidence a newly declared category admits.

        Declaring a word widens a view: claims made under that word before the
        category existed are already in the evidence base, and nothing had drawn
        them because no rule of this graph reached them. This is how they arrive
        without waiting for a `reproject`.

        **A defined category needs the whole graph rebuilt; a primitive one does
        not.** A category with an empty `definition` admits nodes by the word they
        were claimed under, and `(graph, key)` is unique — so it can only add
        vertices that were not there, which `project_all` does by `MERGE`. A
        `definition`, though, can capture nodes another category is already drawing
        (`asserted_as` may name words this graph declares elsewhere), and moving a
        vertex between labels is exactly what Apache AGE cannot do in place. Only
        `rebuild` moves a label honestly.

        The counts come back to the caller and are also logged, including
        `unclassified`. A backfill that drew nothing and one that drew nothing
        *because every candidate was refused by a definition* look identical from
        the mutation's result — which returns the category row, not a report — so
        the number that distinguishes them has to be somewhere.
        """
        from graph_engine import projector

        if selector_module.asserted_as_keys(category.definition):
            counts = self.rebuild_projection(category.graph)
        else:
            counts = projector.project_all(self, category.graph)

        logger.info(
            "%s: backfilled '%s' — %s node(s), %s edge(s), %s admitted by no category.",
            category.graph.age_name,
            category.key,
            counts.get("nodes"),
            counts.get("edges"),
            counts.get("unclassified"),
        )
        return counts

    def rematerialize_category(self, category: models.Category, retired_keys: Iterable[str] = ()) -> int:
        """Redraw the vertices of a category whose properties have just changed.

        The counterpart of :meth:`backfill_category`: that one runs when a *word*
        is declared and widens what the graph draws, this one when the *rules* for
        a word change and the drawing is now wrong. Both exist because the
        projection is the answer — under the old split, where a read folded the
        definition at query time, neither was needed and editing properties was
        free.

        `retired_keys` names what the previous definition owned. The caller has to
        supply it, because by the time the category row is saved the old
        definition is gone — nothing versions it (see the audit's Tier 2), so the
        snapshot has to be taken before the write.
        """
        from graph_engine import projector

        return projector.rematerialize_category(self, category.graph, category, retired_keys=retired_keys)

    def archive_node(self, node_id: Any, info: Info) -> results.Asserted:
        """Retract a node — an entity or an event — by its uuid.

        One path for all three node kinds. The event archivers each had their own
        copy of this inline in `api/mutations/`, with the target type hardcoded to
        a different string, which is how `_lifecycle_state_for_entity` came to
        filter on `"entity"` alone and silently never see an archived event.

        The node is resolved in Postgres, so this no longer needs a graph handed
        to it and no longer reads the projection to find out what it is
        retracting.
        """
        from graph_engine import projector

        node = self._resolve_instance(node_id, info)
        organization = node.organization

        # One transaction. The assertion and the claim it explains were two
        # separate statements, so a failure between them left an assertion
        # claiming nothing and an entity that was never retracted.
        with transaction.atomic():
            assertion = self._create_assertion(organization, self._provenance_from_info(info))
            writer.retract(organization, node, assertion)

        # The vertex goes **after** the claim commits, and the ordering is the
        # point. AGE cannot join a Django transaction, so one of the two failure
        # directions has to be the recoverable one. This way a crash in between
        # leaves the log saying "retracted" and a vertex still standing, which
        # `reproject` fixes. The other way round would delete a vertex with no
        # claim behind it, and the next replay would put it straight back.
        for graph, refs in projector.graphs_for_refs(organization, [node.ref]).items():
            projector.unproject(self, graph, refs)

        # Read back rather than assumed empty. A retraction is folded under each
        # graph's own selector, so a view that does not count this subject still
        # draws the node — see `results` and the `archive_node` note in
        # `docs/rfcs/0003-undrawn-nodes.md`.
        return results.Asserted.of(assertion, node, self.drawings_for_instance(node))

    def attest_node(self, node_id: Any, info: Info) -> results.Asserted:
        """Claim that a node exists.

        Not "un-archive": there is no state to reverse. Somebody is saying the
        thing is there, which is evidence of exactly the same kind as somebody
        saying it is not — and the two can stand side by side, with each graph's
        selector deciding which it counts.
        """
        from graph_engine import projector

        node = self._resolve_instance(node_id, info)
        organization = node.organization

        with transaction.atomic():
            assertion = self._create_assertion(organization, self._provenance_from_info(info))
            writer.attest(organization, node, assertion)

        for graph in projector.graphs_for_refs(organization, [node.ref]):
            projector.reproject_node(self, graph, node)

        return results.Asserted.of(assertion, node, self.drawings_for_instance(node))

    def archive_entity(self, node_id: Any, info: Info) -> results.Asserted:
        """Retract an entity by its uuid."""
        return self.archive_node(node_id, info)

    # `_stamp_projection` and `_lifecycle_state_for_node` are gone, along with
    # `_get_entity_category_for_local_id`, which existed only to feed them.
    #
    # They wrote `__lifecycle_state` onto a vertex. There is no such property any
    # more, and there cannot be: the graph holds what the evidence says exists,
    # so a vertex that is present is a vertex that stands. A flag saying otherwise
    # could only ever contradict the thing it sat on — and nothing read it, so a
    # retracted entity stayed listable and remained a legal relation endpoint.
    #
    # The remaining stamps (`__schema_version`, `__last_derived`) belong to
    # `projector.project`, which is the writer that derives them.

    # `list_entities_informed_by_structure(graph=…)` used to sit here: the `INFORMS`
    # links in SQL, then the named nodes fetched out of one graph's projection, on the
    # grounds that "entities are still projection-scoped". Its only caller was
    # `api.queries.entity.entities_informed_by`, which was named by no field on `Query`
    # and so was unreachable — and which compensated for the graph argument by looping
    # every graph in the organization and concatenating, listing a node once per view
    # that declared its word. Both are gone. The direction that is wired,
    # `get_informing_structures`, takes a node and no graph, which is the grain an
    # `INFORMS` claim is at.

    # `get_node(node_id)` used to sit here — `projected_instance` over
    # `_resolve_instance`, answering with *some* view's drawing for a caller that
    # named no view. The singular node fetchers take a `graph` now and go through
    # `api.queries._nodes.one_in_graph`, the same membership-then-drawing path the
    # list queries use, so "which view's numbers am I looking at" has one answer.

    def get_structure(
        self,
        organization: Any,
        identifier: str,
        object: str,
        info: Info | None = None,
    ) -> retrieved.RetrievedStructure:
        """The structure for one external datum, by `(identifier, object)`.

        Takes the **organization**, not a graph. A structure is idempotent by
        `(organization, identifier, object)` and has no vertex in any projection,
        so a graph argument selected nothing — it only narrowed *authorization* to
        one view of a row that belongs to the tenant. Its sibling
        `list_structures` was de-graphed for the same reason, with the note that
        "listing them does not need a kind any more than it needs a graph".
        """
        self._assert_can_access(organization, info)

        structure = evidence_models.Structure.objects.for_organization(organization).filter(identifier=identifier, object=object).first()
        if structure is None:
            raise ValueError(f"Structure not found with identifier {identifier} and object {object}")

        return retrieved.RetrievedStructure.from_row(self, structure)

    def get_informing_structures(
        self,
        node: evidence_models.Instance,
        info: Info | None = None,
    ) -> List[retrieved.RetrievedStructure]:
        """Every structure that is evidence for a node.

        Takes the **node**, not a graph. INFORMS is organization-grain — ingest
        names no projection — so which view you happened to ask through never
        changed the answer, and the caller had to pick one to satisfy the
        signature. It used `_graph_for_node`, which returns an arbitrary declarer,
        so a node drawn by three views was answered "through" whichever had the
        lowest category id.
        """
        organization = node.organization
        self._assert_can_access(organization, info)

        structure_ids = claims_module.standing(
            evidence_models.Link.objects.for_organization(organization).filter(
                kind=evidence_models.Link.Kind.INFORMS,
                target_ref=node.ref,
            ),
            "link",
        ).values_list("source_ref", flat=True)

        structures = evidence_models.Structure.objects.for_organization(organization).filter(pk__in=list(structure_ids))
        return [retrieved.RetrievedStructure.from_row(self, row) for row in structures]

    def create_structure(
        self,
        organization: Any,
        identifier: str,
        payload: inputs.StructureInput,
        info: Info,
    ) -> results.Asserted:
        """
        Create a structure, or return the existing one for the same datum.

        Idempotent by `(identifier, object)` within the organization, so two
        projections that reference the same external object converge on one row
        instead of each getting a private copy.

        Returns:
            RetrievedStructure with the created structure info
        """
        with transaction.atomic():
            assertion = self._create_assertion(organization, self._provenance_from_info(info))
            structure_kind = self.ensure_structure_kind(organization, identifier)
            structure = writer.ensure_structure(
                organization,
                kind=structure_kind,
                object=payload.object,
                assertion=assertion,
            )
            for metric in payload.metrics or []:
                self._record_metric(organization, structure, metric, info=info, assertion=assertion)

        self.project_from_structures(organization, [structure.pk])
        # No drawings, ever: a structure lives only in the relational evidence
        # base and has no AGE presence at all. The absence is structural, which
        # is why the GraphQL result type for structures omits the field rather
        # than always answering `[]`.
        return results.Asserted.of(assertion, structure)

    def record_metric(
        self,
        organization: Any,
        identifier: str,
        object: str,
        metric: MetricInput,
        info: Info,
    ) -> results.Asserted:
        """Ensure a structure exists and record one measurement against it, as one act.

        The resolver used to call `create_structure` and then `create_metric`,
        which minted **two** assertions in two transactions and projected twice —
        for what is, to the caller, a single claim. Two assertions cannot be put
        back together afterwards: `Assertion.action_id`, the field that would tie
        them, is never populated.
        """
        with transaction.atomic():
            assertion = self._create_assertion(organization, self._provenance_from_info(info))
            structure_kind = self.ensure_structure_kind(organization, identifier)
            structure = writer.ensure_structure(
                organization,
                kind=structure_kind,
                object=object,
                assertion=assertion,
            )
            recorded = self._record_metric(organization, structure, metric, info=info, assertion=assertion)

        self.project_from_structures(organization, [structure.pk])
        return results.Asserted.of(assertion, recorded)

    def _assert_can_access(self, organization: Any, info: Info | None) -> None:
        """Check the caller may act for this organization.

        Evidence rows are identified by a globally unique primary key, so the
        client never has to name a tenant — but that means authorization cannot
        come from the request either. It comes from the row: find what the id
        points at, then check the caller belongs to *its* organization. Skipping
        this is a cross-tenant read, which is precisely the guarantee we gave up
        by leaving per-graph AGE namespaces.
        """
        if info is None:
            return

        user = getattr(info.context.request, "user", None)
        if user is None:
            raise PermissionError("Cannot access evidence without an authenticated user")

        if not Membership.objects.filter(user=user, organization=organization, blocked=False).exists():
            raise PermissionError("You are not allowed to access this organization's evidence")

    def get_structure_for_identifier(
        self,
        organization: Any,
        identifier: str,
        object: str,
    ) -> evidence_models.Structure:
        """Resolve a structure row by its organization-scoped identity."""
        structure = evidence_models.Structure.objects.for_organization(organization).filter(identifier=identifier, object=object).first()
        if structure is None:
            raise ValueError(f"Structure not found for {identifier}:{object}")
        return structure

    def _resolve_structure(self, structure_id: str, info: Info | None = None, organization: Any = None) -> evidence_models.Structure:
        """Fetch a structure by evidence primary key, then authorize against its organization.

        ``organization`` is the tenant the write is being made in; see
        `_resolve_instance` for why membership alone is not enough once the write's
        organization comes from the request rather than from this row.
        """
        # all_objects, not objects: the organization is what we are *looking up*
        # here, so it cannot also be the filter. The `_assert_can_access` call
        # below is what makes that safe, and no use of `all_objects` is
        # acceptable without one.
        structure = evidence_models.Structure.all_objects.filter(pk=structure_id).first()
        if structure is None:
            raise ValueError(f"Structure not found with id {structure_id}")
        self._assert_can_access(structure.organization, info)
        self._assert_same_organization(structure.organization, organization, f"Structure '{structure_id}'")
        return structure

    def _record_metric(
        self,
        organization: Any,
        structure: evidence_models.Structure,
        metric_input: MetricInput,
        *,
        info: Info,
        assertion: evidence_models.Assertion,
    ) -> evidence_models.Metric:
        """Append one measurement, resolving its term from the organization.

        No graph. The question this used to have to answer — "whose schema does a
        metric recorded through graph B resolve against, when graph A introduced
        the structure?" — stops existing once the term belongs to the
        organization. There is one term, and both graphs see it.

        The caller states the value kind; nothing infers it. Once the kind became
        part of a term's identity, inferring would have decided identity by
        ``type(value)`` — `45` minting an INT term and `45.2` a FLOAT one under
        one key — and the paths that could not declare would have had no way to
        name a term when a key had more than one.
        """
        metric_kind = self.ensure_metric_kind(
            organization,
            structure.kind,
            metric_input.key,
            metric_input.value_kind,
        )
        metric = writer.record_metric(
            organization,
            structure,
            metric_kind,
            key=metric_input.key,
            value=metric_input.value,
            assertion=assertion,
            unit=metric_input.unit,
            confidence=metric_input.confidence,
            confidence_type=metric_input.confidence_type,
            measured_at=metric_input.timestamp,
        )

        # Fold into the statistics immediately. O(1), reads no prior metrics, and
        # spans every graph in the organization that has an entity this structure
        # informs — writing the derived values onto those graphs is a separate,
        # batched step.
        from graph_engine import projector

        state_module.merge(metric, projector.refs_informed_by(organization, [structure.pk]))
        return metric

    def archive_structure(
        self,
        structure_id: str,
        info: Info,
    ) -> results.Asserted:
        """Retract a structure by writing a lifecycle event against it."""
        structure = self._resolve_structure(structure_id, info)
        organization = structure.organization

        with transaction.atomic():
            assertion = self._create_assertion(organization, self._provenance_from_info(info))
            writer.retract(organization, structure, assertion)

        return results.Asserted.of(assertion, structure)

    def update_structure(
        self,
        structure_id: str,
        payload: inputs.StructureInput,
        info: Info,
    ) -> results.Asserted:
        """Append metrics to an existing structure.

        A structure's `(identifier, object)` is its identity, so `object` is
        **immutable** and repointing it is rejected. The original plan called for
        a supersede assertion here, but a supersede is incoherent under the
        uniqueness constraint: a row with a different `object` is not a new
        version of this datum, it is a different datum. Pointing at the wrong ROI
        is fixed by creating the right structure and archiving the wrong one,
        which keeps both facts on the record.
        """
        structure = self._resolve_structure(structure_id, info)
        organization = structure.organization

        if payload.object and payload.object != structure.object:
            raise ValueError(f"A structure's object is immutable: {structure.identifier}:{structure.object} cannot become {structure.identifier}:{payload.object}. Create the correct structure and archive this one instead.")

        with transaction.atomic():
            assertion = self._create_assertion(organization, self._provenance_from_info(info))
            for metric in payload.metrics or []:
                self._record_metric(organization, structure, metric, info=info, assertion=assertion)

        self.project_from_structures(organization, [structure.pk])
        return results.Asserted.of(assertion, structure)

    def create_event(
        self,
        organization: Any,
        term: evidence_models.Term,
        node_kind: Any,
        payload: inputs.NaturalEventInput,
        info: Info,
    ) -> results.Asserted:
        """Claim that an event happened, of a word, with these participants.

        Shared by natural and protocol events, as it always was — but the kind of
        event is now an argument rather than something sniffed out of the category's
        Python class. `create_protocol_event` never existed; the protocol mutation
        called this and the kind was inferred by
        `isinstance(category, models.ProtocolEventCategory)`, which the caller
        already knew and could simply say.

        Roles are claims, not schema: `mapping.role` goes into `Link.role` as the
        caller names it. Nothing here checks it against an event category's declared
        roles, and nothing did before — whether a role means anything is a question
        each view answers when it draws the event.

        Args:
            organization: Whose evidence this is
            term: The organization's word for this kind of event
            node_kind: `Instance.Kind.NATURAL_EVENT` or `Instance.Kind.PROTOCOL_EVENT`
            payload: The event input, with its participants and supporting evidence
            info: Strawberry info, for provenance
        """
        supporting_evidence = payload.supporting_evidence or []

        # Evidence first, in one transaction. See the note in `create_entity`
        # about why the AGE write deliberately sits outside it.
        with transaction.atomic():
            assertion = self._create_assertion(organization, self._provenance_from_info(info))
            materialized_evidence, recorded_metrics = self._materialize_supporting_evidence(
                organization=organization,
                supporting_evidence=supporting_evidence,
                assertion=assertion,
                info=info,
            )

        # The uuid, not the AGE vertex id and not a graph-prefixed composite —
        # for the same reasons entities are; see `create_entity`, which also
        # explains why the vertex is written after the `Instance` row rather than
        # before it.
        event_ref = str(self.create_universal_id())

        # Resolved before the transaction: a bad entity id should fail before any
        # evidence is written, not after the node row has committed.
        participations = [(evidence_models.Link.Kind.PARTICIPATES_AS_INPUT, mapping) for mapping in payload.inputs]
        participations += [(evidence_models.Link.Kind.PARTICIPATES_AS_OUTPUT, mapping) for mapping in payload.outputs]
        resolved = [(kind, mapping.role, self._node_ref(mapping.entity_id, info, organization=organization)) for kind, mapping in participations]

        with transaction.atomic():
            evidence_models.Instance.objects.create_for_organization(
                organization=organization,
                id=event_ref,
                kind=node_kind,
                term=term,
                assertion=assertion,
            )

            writer.create_link(
                organization,
                kind=evidence_models.Link.Kind.CLASSIFIES,
                source_ref=event_ref,
                target_ref=str(term.pk),
                assertion=assertion,
                term=term,
            )

            for _, _, structure in materialized_evidence:
                writer.create_link(
                    organization,
                    kind=evidence_models.Link.Kind.INFORMS,
                    source_ref=str(structure.pk),
                    target_ref=event_ref,
                    assertion=assertion,
                )

            # Who took part is a claim about the world, so it is evidence like any
            # other. It was not recorded anywhere: the old Cypher bound the
            # participating entity as `ent` and never used it, `MERGE`d an unkeyed
            # role vertex every event in the graph then shared, and discarded the
            # role name — so entity-to-event participation did not exist in AGE at
            # all, and there was nothing for `rebuild` to replay.
            participation_links = [
                writer.create_link(
                    organization,
                    kind=link_kind,
                    source_ref=claim_ref,
                    target_ref=event_ref,
                    assertion=assertion,
                    term=term,
                    role=role,
                )
                for link_kind, role, claim_ref in resolved
            ]

            for metric in recorded_metrics:
                state_module.merge(metric, [event_ref])

        from graph_engine import projector

        # Every view that declares this event's word, for the reason
        # `create_entity` gives at length. `reproject_node` draws the vertex and
        # the participation edges either side of it, from the claims — so the
        # event a fresh write produces and the one a replay produces are the same.
        node = evidence_models.Instance.objects.for_organization(organization).select_related("term").get(pk=event_ref)
        for target_graph in projector.graphs_for_refs(organization, [event_ref]):
            projector.reproject_node(self, target_graph, node)

        # Not an unguarded index into a Cypher result. This used to be
        # `engine.execute(graph, …)[0]["e"]`, which raised `IndexError` — not even
        # a message — whenever the graph the caller named did not draw the event.
        # The claim was already durable at that point.
        return results.Asserted.of(assertion, node, self.drawings_for_instance(node))

    def create_metric(
        self,
        structure_id: str,
        input: MetricInput,
        info: Info,
    ) -> results.Asserted:
        """
        Append a measurement to an existing structure.

        Args:
            structure_id: The evidence primary key of the structure
            input: The measurement data
            info: Request info used to extract provenance

        Returns:
            RetrievedMetric with the created measurement info
        """
        structure = self._resolve_structure(structure_id, info)
        organization = structure.organization

        with transaction.atomic():
            assertion = self._create_assertion(organization, self._provenance_from_info(info))
            metric = self._record_metric(organization, structure, input, info=info, assertion=assertion)

        # Refresh every projection this structure is evidence for. Separate from
        # the fold above because it is batched: a bulk ingest of a thousand
        # metrics folds a thousand times (O(1) each) but projects once.
        self.project_from_structures(organization, [structure.pk])

        return results.Asserted.of(assertion, metric)

    def _resolve_metric(self, metric_id: str, info: Info | None = None) -> evidence_models.Metric:
        """Fetch a metric by evidence primary key, then authorize against its organization."""
        metric = evidence_models.Metric.all_objects.filter(pk=metric_id).first()
        if metric is None:
            raise ValueError(f"Metric not found with id {metric_id}")
        self._assert_can_access(metric.organization, info)
        return metric

    def get_metric(self, metric_id: str, info: Info | None = None) -> RetrievedMetric:
        """Read a single metric by its evidence primary key."""
        return RetrievedMetric.from_row(self, self._resolve_metric(metric_id, info))

    def get_structure_by_id(self, structure_id: str, info: Info | None = None) -> RetrievedStructure:
        """Read a single structure by its evidence primary key."""
        return RetrievedStructure.from_row(self, self._resolve_structure(structure_id, info))

    def get_metrics_for_structure_id(self, structure_id: str, info: Info | None = None) -> List[RetrievedMetric]:
        """Every un-retracted metric describing a structure, by the structure's id."""
        structure = self._resolve_structure(structure_id, info)
        metrics = writer.active_metrics_for_structures(structure.organization, [structure.pk])
        return [RetrievedMetric.from_row(self, row) for row in metrics]

    def get_metrics_for_assertion_id(self, assertion_id: str, info: Info | None = None) -> List[RetrievedMetric]:
        """Every metric recorded under one assertion, by the assertion's id.

        Unanswerable before M1: an assertion was an AGE vertex, so its id alone
        did not say which graph to look in. Organization-scoped rows have
        globally unique keys, which is what makes this a real query.
        """
        assertion = evidence_models.Assertion.all_objects.filter(pk=assertion_id).first()
        if assertion is None:
            raise ValueError(f"Assertion not found with id {assertion_id}")
        self._assert_can_access(assertion.organization, info)

        metrics = evidence_models.Metric.objects.for_organization(assertion.organization).filter(assertion_id=assertion.pk)
        return [RetrievedMetric.from_row(self, row) for row in metrics]

    def archive_metric(
        self,
        metric_id: str,
        info: Info,
    ) -> results.Asserted:
        """Retract a measurement without destroying it.

        The metric stays readable afterwards, which is the point: a derived value
        that stopped counting this measurement still has to be explainable.
        """
        metric = self._resolve_metric(metric_id, info)
        organization = metric.organization

        from graph_engine import projector

        instance_refs = projector.refs_informed_by(organization, [metric.structure_id])

        with transaction.atomic():
            assertion = self._create_assertion(organization, self._provenance_from_info(info))
            result = writer.retract(organization, metric, assertion)
            if result.moved:
                # Remove the contribution from the statistics too, or the derived
                # value would keep counting evidence that has been retracted.
                #
                # Guarded on the *transition*, because archiving twice must not
                # subtract twice — `state.retract` is a delta, not an idempotent
                # operation. The guard used to read `metric.stands`, a mutable
                # column on the log row, and the log paid for it: a second
                # annotator's concurring retraction was suppressed entirely so
                # that this line would not fire twice. Now both claims are
                # recorded and only the fold is conditional.
                state_module.retract(metric, instance_refs)

        self.project_from_structures(organization, [metric.structure_id])
        # The retracted metric itself, not its id. Returning a bare string forced
        # the resolver to read the row back to build a payload, which is how
        # `archive_metric` came to report a metric fetched *after* the retraction
        # under an assertion it had no handle on.
        return results.Asserted.of(assertion, metric)

    def update_metric(
        self,
        payload: inputs.SupersedeMetricValueInput,
        info: Info,
    ) -> results.Asserted:
        """Correct a measurement by retracting it and asserting a new one.

        Never an in-place edit. Both the original claim and the correction stay
        on the record, under separate assertions, so `as_of` can still recover
        what was believed before the revision.
        """
        metric = self._resolve_metric(str(payload.id), info)
        organization = metric.organization
        structure = metric.structure

        metric_input = MetricInput(
            key=payload.key,
            value=payload.value,
            value_kind=payload.value_kind,
            confidence=payload.confidence,
            confidence_type=payload.confidence_type,
            unit=payload.unit,
            timestamp=payload.timestamp,
        )

        from graph_engine import projector

        instance_refs = projector.refs_informed_by(organization, [structure.pk])

        with transaction.atomic():
            assertion = self._create_assertion(organization, self._provenance_from_info(info))
            writer.retract(organization, metric, assertion)
            # The old value stops counting, so its contribution has to come out of
            # the statistics before the replacement goes in.
            state_module.retract(metric, instance_refs)
            replacement = self._record_metric(organization, structure, metric_input, info=info, assertion=assertion)

        self.project_from_structures(organization, [structure.pk])
        # One assertion covers both halves — the retraction and the replacement
        # are one corrective act, which is why they share a transaction.
        return results.Asserted.of(assertion, replacement)

    def link_structure_to_entity(
        self,
        structure_id: str,
        entity_id: scalars.GraphID,
        info: Info,
    ) -> results.Asserted:
        """Assert that a structure is evidence for an entity.

        Reinstated here as a *pure evidence write* — it was removed from the
        schema in M0 because the old implementation raised a `NameError` before
        doing anything. Which structures justify an entity is a claim about the
        world, so the link is evidence and outlives any graph projected from it.

        Attaching evidence after the fact must move the derived value, so the
        structure's existing metrics are folded into the entity's statistics and
        the entity is re-projected. Without that, the link would be recorded and
        the value would silently stay where it was until something else touched
        it.
        """
        structure = self._resolve_structure(structure_id, info)
        organization = structure.organization

        # The client names the entity by its composite id, whose second half is
        # an AGE vertex id. Recording that verbatim — which this used to do —
        # keyed the link and every state row it folded under a ref no projection
        # ever reads: `project` resolves entities by `Instance.ref`, which is always
        # the uuid form. The rows were written, nothing found them, and the
        # derived value silently never moved.
        #
        # Scoped to the structure's organization, because the two ends are
        # authorized independently: a caller belonging to both tenants passes the
        # membership check on either row, so without this the INFORMS link could
        # say one organization's ROI is evidence for another's cell.
        claim_ref = self._node_ref(entity_id, info, organization=organization)

        with transaction.atomic():
            assertion = self._create_assertion(organization, self._provenance_from_info(info))
            writer.create_link(
                organization,
                kind=evidence_models.Link.Kind.INFORMS,
                source_ref=str(structure.pk),
                target_ref=claim_ref,
                assertion=assertion,
            )

            for metric in writer.active_metrics_for_structures(organization, [structure.pk]):
                state_module.merge(metric, [claim_ref])

        # Just this entity. The structure's other dependents saw no change in
        # their statistics, so fanning out to them would re-derive values that
        # cannot have moved.
        self.project_refs(organization, [claim_ref])
        return results.Asserted.of(assertion, structure)

    # ===================================================================
    # Edges — relations, structure relations and measurements
    #
    # All three are claims, so all three are evidence. They differ only in what
    # their endpoints are, and that decides whether the claim has a projection:
    # entities are AGE vertices, so a relation projects to an edge; structures
    # are Postgres rows, so a structure relation and a measurement have nothing
    # to draw an edge between and live purely in the evidence base.
    # ===================================================================

    # `classify` used to sit here — the singular form of `classify_nodes`, taking a
    # `models.Category` and rebuilding that category's graph alone. Nothing called
    # it: the batch form superseded it, and a batch of one is the singular form.
    # It is not worth porting to terms to keep an unreachable second answer to
    # "which views does a relabel move".

    def assert_participation(
        self,
        event_id: scalars.GraphID,
        entity_id: scalars.GraphID,
        role: str,
        is_input: bool,
        info: Info,
    ) -> results.Asserted:
        """Claim that an entity took part in an event, in a role.

        Additive. Who took part is as contestable as anything else — a second
        observer reading the same timelapse may say a different cell went into
        that division — and until this existed the only way to say so was
        `updateNaturalEvent`, which archived the event and created a new one. A
        disagreement about a participant produced a different *event*.
        """
        organization = self._resolve_instance(event_id, info).organization

        event_ref = self._node_ref(event_id, info, organization=organization)
        claim_ref = self._node_ref(entity_id, info, organization=organization)

        node = evidence_models.Instance.objects.for_organization(organization).filter(id=event_ref).select_related("term").first()
        if node is None:
            raise ValueError(f"No event with ref '{event_ref}'")
        if node.kind == evidence_models.Instance.Kind.ENTITY:
            raise ValueError("Participation is a claim about an event; the target of this one is an entity.")

        kind = evidence_models.Link.Kind.PARTICIPATES_AS_INPUT if is_input else evidence_models.Link.Kind.PARTICIPATES_AS_OUTPUT

        with transaction.atomic():
            assertion = self._create_assertion(organization, self._provenance_from_info(info))
            link = writer.create_link(
                organization,
                kind=kind,
                source_ref=claim_ref,
                target_ref=event_ref,
                assertion=assertion,
                term=node.term,
                role=role,
            )

        # Every view that draws the event, not one of them. `_graph_for_ref` used
        # to pick "an arbitrary one of the declarers" here, so a second view of the
        # same event kept a participation edge nobody had retracted and nobody had
        # drawn until its next rebuild.
        self._reproject_participation_everywhere(organization, claim_ref, event_ref, kind, role)
        return results.Asserted.of(assertion, link, self.drawings_for_edge(link))

    # ===================================================================
    # Batch claims
    #
    # A set of claims made together by one actor in one act **is one
    # assertion**. Making them one at a time fragments that act into N
    # assertions with nothing to reassemble them — `Assertion.action_id`, the
    # field that would, is never populated. So these are not sugar over the
    # singular forms; they are the shape the provenance model already wants,
    # and `create_entity` has always used it internally.
    #
    # Every one follows the same three steps, which `create_natural_event`
    # demonstrates: resolve every reference *before* the transaction so a bad id
    # fails before anything is written; mint one assertion and write everything
    # under it; project once, targeted.
    # ===================================================================

    def assert_participations(
        self,
        event_id: scalars.GraphID,
        participants: list[Any],
        info: Info,
    ) -> results.Asserted:
        """Claim that several entities took part in one event, as one act."""
        if not participants:
            return []

        organization = self._resolve_instance(event_id, info).organization
        event_ref = self._node_ref(event_id, info, organization=organization)

        node = evidence_models.Instance.objects.for_organization(organization).filter(id=event_ref).select_related("term").first()
        if node is None:
            raise ValueError(f"No event with ref '{event_ref}'")
        if node.kind == evidence_models.Instance.Kind.ENTITY:
            raise ValueError("Participation is a claim about an event; the target of this one is an entity.")

        resolved = [
            (
                evidence_models.Link.Kind.PARTICIPATES_AS_INPUT if participant.is_input else evidence_models.Link.Kind.PARTICIPATES_AS_OUTPUT,
                participant.role,
                self._node_ref(participant.entity, info, organization=organization),
            )
            for participant in participants
        ]

        with transaction.atomic():
            assertion = self._create_assertion(organization, self._provenance_from_info(info))
            links = [
                writer.create_link(
                    organization,
                    kind=kind,
                    source_ref=claim_ref,
                    target_ref=event_ref,
                    assertion=assertion,
                    term=node.term,
                    role=role,
                )
                for kind, role, claim_ref in resolved
            ]

        for kind, role, claim_ref in resolved:
            self._reproject_participation_everywhere(organization, claim_ref, event_ref, kind, role)

        # **One** result, not one per participant. The batch is a single act by a
        # single actor, which is exactly what one assertion means — returning a
        # list of results would have repeated that assertion N times and claimed
        # N acts had happened.
        return results.Asserted(
            assertion=assertion,
            subjects=tuple(links),
            drawings=tuple(drawing for link in links for drawing in self.drawings_for_edge(link)),
        )

    def classify_nodes(
        self,
        organization: Any,
        classifications: list[Any],
        info: Info,
    ) -> results.Asserted:
        """Claim that several nodes are of a word, as one act.

        Each claim names the word the caller means and the node it is about. The
        word's *kind* is not the caller's to choose: it comes from the node, so a
        classification cannot claim an `ENTITY` word about an event. Stating it
        would let a client write a `CLASSIFIES` link that no category is ever keyed
        on — a successful write nothing can read.

        Which label each graph then shows is a separate question, answered at
        projection time by whichever of its categories are defined — see
        `projector.resolve_categories`.
        """
        if not classifications:
            return []

        # `_resolve_instance` refuses a node outside this organization, which is what
        # keeps a batch within one tenant. The old body checked the same thing by
        # comparing the *categories'* graphs against each other — "A batch of
        # classifications must stay within one organization." — and that check went
        # with the categories; this is the same guarantee stated against the rows
        # the claims are actually about.
        resolved: list[tuple[evidence_models.Term, str, evidence_models.Instance]] = []
        for classification in classifications:
            node = self._resolve_instance(classification.node, info, organization=organization)
            term = self.ensure_term(organization, enums.TERM_KIND_FOR_NODE_KIND[str(node.kind)], classification.term)
            resolved.append((term, node.ref, node))

        # Every view that draws any of these nodes, before the claims land and
        # after. Both, because a word this batch introduces may be declared by a
        # view that did not hold the node at all — classifying can *widen* the set
        # of views a node appears in, and the new view needs drawing as much as the
        # old ones need correcting.
        from graph_engine import projector

        refs = [ref for _, ref, _ in resolved]
        graphs = {graph.pk: graph for graph in projector.graphs_for_refs(organization, refs)}
        before = self._resolved_labels(list(graphs.values()), refs)

        with transaction.atomic():
            assertion = self._create_assertion(organization, self._provenance_from_info(info))
            for term, node_ref, _ in resolved:
                writer.create_link(
                    organization,
                    kind=evidence_models.Link.Kind.CLASSIFIES,
                    source_ref=node_ref,
                    target_ref=str(term.pk),
                    assertion=assertion,
                    term=term,
                )

        graphs.update({graph.pk: graph for graph in projector.graphs_for_refs(organization, refs)})

        # A concurring claim moves nothing, and must cost nothing. Only a label
        # that actually changed needs a rebuild, because Apache AGE has no
        # relabel — a vertex has to be dropped and recreated to carry a different
        # one, and `rebuild` is the operation that does that honestly.
        after = self._resolved_labels(list(graphs.values()), refs)
        for graph in graphs.values():
            if before.get(graph.pk) != after.get(graph.pk):
                self.rebuild_projection(graph)
            else:
                projector.project(self, graph, refs)

        # Drawings collected strictly **after** the rebuild loop above. A
        # classification can move a label, and moving one means dropping and
        # replaying the whole graph — so reading drawings any earlier would
        # report vertices that no longer exist.
        nodes = [node for _, _, node in resolved]
        return results.Asserted(
            assertion=assertion,
            subjects=tuple(nodes),
            drawings=tuple(drawing for node in nodes for drawing in self.drawings_for_instance(node)),
        )

    def _resolved_labels(self, graphs: list[models.Graph], refs: list[str]) -> dict[Any, dict[str, str]]:
        """Which category each of these nodes currently projects as, per graph.

        Takes the graphs and the refs separately because a node's views are no
        longer something the caller named — they are computed, and the same ref has
        to be asked of every view that might hold it.
        """
        from graph_engine import projector

        labels: dict[Any, dict[str, str]] = {}
        for graph in graphs:
            nodes = list(evidence_models.Instance.objects.for_organization(graph.organization).filter(id__in=refs).select_related("term"))
            categories, _ = projector.resolve_categories(graph, nodes)
            labels[graph.pk] = {ref: category.age_name for ref, category in categories.items()}
        return labels

    def get_instance_by_ref(self, graph: models.Graph, ref: str) -> retrieved.RetrievedNode:
        """Read a projected node back by its durable ref."""
        node_uuid = str(ref)
        result = self.engine.execute(graph, "MATCH (n) WHERE n.id = $nid RETURN n", {"nid": node_uuid})
        if not result:
            raise ValueError(f"No projected node for ref '{ref}'")
        return RetrievedNode.from_node(self, result[0]["n"], graph_name=graph.age_name)

    def drawn_instances(self, graph: models.Graph, refs: list[str]) -> dict[str, retrieved.RetrievedNode]:
        """How this graph draws each of these nodes, keyed by ref. Missing means undrawn.

        One query for the batch, where `get_instance_by_ref` is one per node — the
        difference between a page of claims costing one round-trip and costing a
        hundred. A ref with no vertex simply does not appear: which nodes a view
        holds is decided from the claims (`projector.refs_in_graph`), and whether it
        has drawn them yet is a separate question this answers.
        """
        if not refs:
            return {}

        result = self.engine.execute(graph, "MATCH (n) WHERE n.id IN $nids RETURN n", {"nids": [str(ref) for ref in refs]})
        drawn: dict[str, retrieved.RetrievedNode] = {}
        for row in result:
            node = RetrievedNode.from_node(self, row["n"], graph_name=graph.age_name)
            drawn[node.unique_id] = node
        return drawn

    def retract_links(self, link_ids: list[str], info: Info) -> results.Asserted:
        """Retract several link claims as one act.

        Retraction is a claim too, so withdrawing a set of them is one assertion
        for the same reason asserting a set of them is.

        **Takes `Link` primary keys, which is what its name now says.** It was
        `archive_claims(claim_ids=…)`, and both halves misled: the ids are links
        rather than `Standing` rows, and `archive_*` is the verb this codebase
        replaced with `retract_*` everywhere else on the instance paths.

        An empty batch is refused rather than answered with an empty list. The
        result is now the assertion this call made, and a call that retracts
        nothing makes none — there is no honest thing to hand back, and minting
        an assertion that claims nothing would put a row in the log for an act
        that did not happen.
        """
        if not link_ids:
            raise ValueError("Retracting an empty set of claims is not an act; pass at least one link id.")

        links = [self.resolve_edge_link(str(link_id), info) for link_id in link_ids]
        organization = links[0].organization
        if any(link.organization_id != organization.pk for link in links):
            raise ValueError("A batch of retractions must stay within one organization.")

        with transaction.atomic():
            assertion = self._create_assertion(organization, self._provenance_from_info(info))
            for link in links:
                writer.retract(organization, link, assertion)

        # Rebuilds are collected across the whole batch and run once each at the
        # end. A retracted classification can move a label, and only `rebuild` moves
        # one — but a rebuild drops and replays a whole graph and refolds the
        # organization's state, so doing it per link would make M retractions across
        # N views M×N of them. The edge branches are already targeted and stay inline.
        pending_rebuilds: dict[Any, models.Graph] = {}
        for link in links:
            self._reproject_claim(organization, link, pending_rebuilds=pending_rebuilds)

        for graph in pending_rebuilds.values():
            self.rebuild_projection(graph)

        # After the deferred rebuilds, for the same reason `classify_nodes` reads
        # its drawings last: a rebuild drops and replays a whole graph.
        return results.Asserted(
            assertion=assertion,
            subjects=tuple(links),
            drawings=tuple(drawing for link in links for drawing in self.drawings_for_edge(link)),
        )

    def _reproject_claim(
        self,
        organization: Any,
        link: evidence_models.Link,
        pending_rebuilds: dict[Any, models.Graph] | None = None,
    ) -> None:
        """Bring whatever a retracted claim was projected as back in line.

        Every branch fans out over the views that draw the claim's endpoints. Each
        used to take `_graph_for_ref`'s arbitrary single graph, which meant a
        retraction was honoured in one view and silently ignored in every other one
        declaring the same word — the projection there kept an edge, or a label,
        that no standing claim supported.

        ``pending_rebuilds``, when given, collects the graphs a classification
        retraction needs rebuilt instead of rebuilding them here, so a batch pays
        for each graph once rather than once per claim. Called without it — the
        single-claim paths — it rebuilds immediately.
        """
        if link.kind == evidence_models.Link.Kind.RELATION:
            self._reproject_proposition_everywhere(organization, str(link.source_ref), str(link.target_ref), link.term_id)
        elif link.kind in (evidence_models.Link.Kind.PARTICIPATES_AS_INPUT, evidence_models.Link.Kind.PARTICIPATES_AS_OUTPUT):
            self._reproject_participation_everywhere(organization, str(link.source_ref), str(link.target_ref), link.kind, link.role)
        elif link.kind == evidence_models.Link.Kind.CLASSIFIES:
            # A retracted classification can move a label, and only `rebuild`
            # can move one — in each view that had drawn the node.
            from graph_engine import projector

            for graph in projector.graphs_for_refs(organization, [str(link.source_ref)]):
                if pending_rebuilds is None:
                    self.rebuild_projection(graph)
                else:
                    pending_rebuilds.setdefault(graph.pk, graph)
        elif link.kind == evidence_models.Link.Kind.SAME_AS:
            # Nothing to un-draw either — a sameness claim has no edge — but the
            # *component* may have split, and every view drawing any member is
            # showing what is now possibly two things as one. The members are read
            # before the fold is rebuilt, because afterwards they are no longer
            # one component to enumerate.
            members = identity_module.component_refs(organization, [str(link.source_ref)])[str(link.source_ref)]
            identity_module.retract(organization, link)
            identity_module.recompute(organization, identity_module.canonical_for(organization, str(link.source_ref)))
            self._reproject_instances(organization, members)
        elif link.kind == evidence_models.Link.Kind.INFORMS:
            # Nothing to un-draw — an INFORMS link has no edge — but the derived
            # values it fed have to stop counting it.
            self.project_refs(organization, [str(link.target_ref)])

    def archive_participation(
        self,
        participation_id: str,
        info: Info,
    ) -> results.Asserted:
        """Retract one claim that an entity took part in an event.

        The edge survives as long as another live claim still states the same
        participation — the point of keeping claims separate from the thing they
        agree on.
        """
        link = self.resolve_edge_link(participation_id, info)
        if link.kind not in (evidence_models.Link.Kind.PARTICIPATES_AS_INPUT, evidence_models.Link.Kind.PARTICIPATES_AS_OUTPUT):
            raise ValueError(f"Link {participation_id} is a {link.kind}, not a participation")

        organization = link.organization

        with transaction.atomic():
            assertion = self._create_assertion(organization, self._provenance_from_info(info))
            writer.retract(organization, link, assertion)

        self._reproject_participation_everywhere(organization, str(link.source_ref), str(link.target_ref), link.kind, link.role)
        # Drawings read back, not assumed empty: the edge survives wherever
        # another live claim still states the same participation, which is the
        # point of keeping claims separate from the thing they agree on.
        return results.Asserted.of(assertion, link, self.drawings_for_edge(link))

    def _reproject_participation(
        self,
        graph: models.Graph,
        organization: Any,
        claim_ref: str,
        event_ref: str,
        kind: str,
        role: str | None,
    ) -> None:
        """Bring one participation edge back in line with the claims behind it."""
        from graph_engine import projector

        survivors = list(
            claims_module.standing(
                evidence_models.Link.objects.for_organization(organization).filter(
                    kind=kind,
                    source_ref=claim_ref,
                    target_ref=event_ref,
                    role=role,
                ),
                "link",
            ).select_related("term")
        )

        if survivors:
            projector.project_participation(self, graph, survivors)
            return

        node = evidence_models.Instance.objects.for_organization(organization).filter(id=event_ref).first()
        if node is None:
            return

        # This graph's category for the event's term — the edge label is a
        # property of the view, even though which two labels it picks between is
        # a property of the kind.
        category = projector.categories_by_term(graph).get(node.term_id)
        if category is None:
            return

        category = category.as_kind()
        is_input = kind == evidence_models.Link.Kind.PARTICIPATES_AS_INPUT
        label = category.AGE_INPUT_EDGE if is_input else category.AGE_OUTPUT_EDGE
        pattern = f"(entity)-[r:{label}]->(event)" if is_input else f"(event)-[r:{label}]->(entity)"

        entity_uuid = str(claim_ref)
        event_uuid = str(event_ref)

        # Nothing claims this participation any more, so the edge states nothing.
        # It goes rather than lingering behind a flag: `rebuild` would not
        # recreate it, and a projection that disagrees with a replay is the
        # failure this layer exists to prevent.
        self.engine.execute(
            graph,
            f"""
            MATCH {pattern}
            WHERE entity.id = $entity_uuid AND event.id = $event_uuid AND r.role = $role
            DELETE r
            """,
            {"entity_uuid": entity_uuid, "event_uuid": event_uuid, "role": role},
        )

    def _assert_same_organization(self, actual: Any, expected: Any, what: str) -> None:
        """Refuse a reference that belongs to a different tenant than the write.

        Separate from `_assert_can_access`, which asks "may this caller reach that
        row" — a question about the *user*. This asks "does that row belong here",
        a question about the *claim*. Both are needed, and only the first existed:
        every write derived its organization from the row it was handed, so the two
        could not disagree. Now the organization comes from the request and they can.
        """
        if expected is None:
            return

        # Both sides must be `Organization` rows, and the comparison must be on a
        # primary key that exists. `getattr(x, "pk", None)` on two non-rows returns
        # `None == None` and lets everything through — a guard that passes silently
        # when miswired is worse than no guard, because it reads as one.
        actual_pk = getattr(actual, "pk", None)
        expected_pk = getattr(expected, "pk", None)
        if actual_pk is None or expected_pk is None:
            raise TypeError(f"Organization guard needs two Organization rows, got {actual!r} and {expected!r}")

        if actual_pk != expected_pk:
            raise PermissionError(f"{what} belongs to another organization; a claim cannot reach across tenants.")

    def _resolve_instance(self, node_id: Any, info: Info | None = None, organization: Any = None) -> evidence_models.Instance:
        """Find the node a client named, and check the caller may reach it.

        **Identity resolves in Postgres, never through the projection.** A node
        id is a world-unique uuid, so this is a primary-key lookup — where it
        used to be `get_node_by_local_id`, which read an Apache AGE vertex and
        took its identity off a vertex property. That made the cache the
        authority on identity: a vertex that existed without a `Instance` row still
        resolved, and every `Link` written against it named something the log had
        never heard of.

        `all_objects`, not `objects`: the organization is what we are looking up,
        so it cannot also be the filter. `_assert_can_access` is what makes that
        safe, and no use of `all_objects` is acceptable without one.

        ``organization`` is the tenant the *write* is being made in, and passing it
        is how a write says its references have to live there too. Membership alone
        is not enough: a user who belongs to two organizations passes
        `_assert_can_access` for rows in either, so a claim written in one could
        name nodes in the other — a `Link` invisible to every query scoped to its
        own endpoints, and unfindable afterwards. That was unreachable while the
        write took its organization *from* the row it was given; it became reachable
        the moment the organization started coming from the request.
        """
        node = evidence_models.Instance.all_objects.filter(pk=str(node_id)).select_related("term", "organization").first()
        if node is None:
            raise ValueError(f"No node with id '{node_id}'")
        self._assert_can_access(node.organization, info)
        self._assert_same_organization(node.organization, organization, f"Node '{node_id}'")
        return node

    def _graphs_for_endpoints(self, organization: Any, *refs: str) -> list[models.Graph]:
        """Every view that draws either end of an edge.

        The replacement for `_graph_for_ref` on the write paths that correct an
        edge. That returned "an arbitrary one of the declarers", which was
        defensible only while the caller also named a graph and the two agreed;
        with the graph gone from the write surface, an arbitrary choice would
        silently leave the other views holding a stale edge until their next
        rebuild.

        A graph holding only one endpoint is included and costs nothing: the
        projection's `MATCH (s) … MATCH (t)` finds no pair and merges no edge.
        """
        from graph_engine import projector

        # One call over every ref, not one per ref. `graphs_for_refs` runs an
        # organization-wide `Category` scan to build the term→graphs map, and
        # `_reproject_claim` calls this once per link inside `retract_links` — so
        # asking per ref would make an N-claim retraction 2N full scans, which is
        # exactly what building that map in a single pass was meant to avoid.
        # It already orders by primary key.
        return list(projector.graphs_for_refs(organization, [str(ref) for ref in refs]))

    def _reproject_proposition_everywhere(
        self,
        organization: Any,
        source_ref: str,
        target_ref: str,
        term_id: Any,
    ) -> None:
        """Correct this proposition's edge in every view that draws it."""
        for graph in self._graphs_for_endpoints(organization, source_ref, target_ref):
            self._reproject_proposition(graph, organization, source_ref, target_ref, term_id)

    def _reproject_participation_everywhere(
        self,
        organization: Any,
        claim_ref: str,
        event_ref: str,
        kind: str,
        role: str | None,
    ) -> None:
        """Correct this participation's edge in every view that draws it."""
        for graph in self._graphs_for_endpoints(organization, claim_ref, event_ref):
            self._reproject_participation(graph, organization, claim_ref, event_ref, kind, role)

    def _claim_same_instance(
        self,
        organization: Any,
        left_ref: str,
        right_ref: str,
        assertion: evidence_models.Assertion,
        info: Info | None = None,
    ) -> evidence_models.Link:
        """Record that two entities are one thing, and fold it.

        **Entities only.** A structure is a pointer to an external datum, already
        idempotent by `(identifier, object)`, so two structures are never "the
        same" — a claim that says so is either meaningless or is really a claim
        about the entities they inform. `_resolve_instance` refuses anything that is
        not a node, and the kind check refuses events, which have their own
        identity through the protocol that produced them.

        Refusing a self-claim rather than folding it: a node is trivially itself,
        so the claim carries no information, and letting it through would put a
        row in the log that no reader can act on.
        """
        left = self._resolve_instance(left_ref, info, organization=organization)
        right = self._resolve_instance(right_ref, info, organization=organization)

        for node in (left, right):
            if str(node.kind) != str(evidence_models.Instance.Kind.ENTITY):
                raise ValueError(f"Only entities can be claimed the same; node {node.pk} is a {node.kind}.")

        if str(left.pk) == str(right.pk):
            raise ValueError("A node is already itself; there is nothing to claim.")

        link = writer.create_link(
            organization,
            kind=evidence_models.Link.Kind.SAME_AS,
            source_ref=str(left.pk),
            target_ref=str(right.pk),
            assertion=assertion,
        )

        # Fold immediately, in the same transaction as the claim. The alternative
        # — writing the claim and folding later — is what lets the fold and the
        # log disagree, which is the failure `State` already had once.
        identity_module.merge(organization, str(left.pk), str(right.pk))
        return link

    def assert_same_instance(self, organization: Any, instance_refs: list[Any], info: Info) -> results.Asserted:
        """Claim that several already-recorded instances are one thing.

        Every pair among them, under **one** assertion: the caller is making one
        statement ("these are all the same cell"), and recording it as N
        assertions would fragment one act into several with nothing to reassemble
        them.

        Pairwise rather than star-shaped around the first id, because sameness has
        no primary — picking one as the hub would make it canonical by accident of
        argument order, which is exactly what the lowest-uuid rule in
        `evidence.identity` exists to avoid.
        """
        refs = [str(ref) for ref in instance_refs]
        if len(set(refs)) < 2:
            raise ValueError("Claiming sameness needs at least two distinct entities.")

        with transaction.atomic():
            assertion = self._create_assertion(organization, self._provenance_from_info(info))
            links = [self._claim_same_instance(organization, refs[0], other, assertion, info) for other in refs[1:]]

        # Every view drawing any member may now draw the component differently, so
        # each member is reprojected — the same fan-out a classification does.
        self._reproject_instances(organization, refs)

        return results.Asserted(
            assertion=assertion,
            subjects=tuple(links),
            drawings=(),
        )

    def retract_same_instance(self, claim_id: str, info: Info) -> results.Asserted:
        """Withdraw one sameness claim, and rebuild whatever it may have held together.

        A retraction can split a component in two, and union-find cannot un-union
        — so `identity.retract` flags and `identity.recompute` rebuilds, the same
        division of labour `state.retract` and `state.recompute` already use.
        """
        link = self.resolve_edge_link(claim_id, info)
        if link.kind != evidence_models.Link.Kind.SAME_AS:
            raise ValueError(f"Claim {claim_id} is a {link.kind}, not a sameness claim")

        organization = link.organization

        with transaction.atomic():
            assertion = self._create_assertion(organization, self._provenance_from_info(info))
            writer.retract(organization, link, assertion)

        # The rebuild and the reprojection are `_reproject_claim`'s SAME_AS
        # branch, shared with `retractLinks` so a sameness claim withdrawn in a
        # batch and one withdrawn alone cannot diverge.
        self._reproject_claim(organization, link)

        return results.Asserted.of(assertion, link, ())

    def _reproject_instances(self, organization: Any, refs: list[str]) -> None:
        """Redraw these nodes in every view that holds them."""
        from graph_engine import projector

        nodes = list(evidence_models.Instance.objects.for_organization(organization).filter(pk__in=refs).select_related("term"))
        for node in nodes:
            for graph in projector.graphs_for_refs(organization, [node.ref]):
                projector.reproject_node(self, graph, node)

    # `projected_instance` used to sit here: `drawings_for_instance(node)[0].node`,
    # falling back to `RetrievedNode.from_row` when nothing drew the claim. The
    # fallback's insight survives — being drawn nowhere is not an error, and the
    # from_row shape is what `nodes(graph:)` returns for an admitted-but-undrawn
    # node — but `[0]` handed back an arbitrary view's drawing for a caller that
    # named no view, which is exactly the lossiness `drawings_for_instance` below
    # exists to avoid. Its last caller was `get_node`, gone for the same reason.

    def drawings_for_instance(self, node: evidence_models.Instance) -> tuple[results.NodeDrawing, ...]:
        """Every view that draws this node, as it draws it.

        Replaces `projected_instance`, which asked the same views in the same order
        and returned the **first** that answered — so a node drawn in three views
        reported one, and which one depended on primary-key order. Nothing about
        the claim explained the difference, because the difference was not about
        the claim.

        Read back from the projection rather than derived from what the write
        path did, so this reports what is actually drawn. That matters most for
        retraction, where the two do not currently agree.

        `except ValueError: continue` is the ordinary path, not an error case: a
        view declares the word but its `definition` refused this node, so it is
        not drawn there. That is the whole reason `drawings` is a list.
        """
        from graph_engine import projector

        drawings: list[results.NodeDrawing] = []
        for graph in projector.graphs_for_refs(node.organization, [node.ref]):
            try:
                projected = self.get_instance_by_ref(graph, node.ref)
            except ValueError:
                continue

            # The category the **vertex** carries, not the one a resolver would
            # pick now. `projector.create_vertex` writes `category_id` as it
            # draws, so this is the drawing's own account of itself.
            category = models.Category.objects.filter(pk=projected.category_id).first()
            if category is None:
                logger.warning(
                    "%s draws node %s under category_id %s, which no longer exists; reporting no drawing there.",
                    graph.age_name,
                    node.pk,
                    projected.category_id,
                )
                continue

            drawings.append(results.NodeDrawing(graph=graph, category=category, node=projected))

        return tuple(drawings)

    def drawings_for_edge(self, link: evidence_models.Link) -> tuple[results.EdgeDrawing, ...]:
        """Every view that draws this link, as it draws it.

        Empty is a common and correct answer, with three ordinary causes: no view
        declares the claim's word, an endpoint is missing from the projection, or
        the link is of a kind that has **no AGE edge at all** — measurements and
        structure relations, per `docs/LOG.md`. For those two the emptiness is
        structural rather than circumstantial.
        """
        from graph_engine import projector

        drawings: list[results.EdgeDrawing] = []
        for graph in projector.graphs_for_refs(link.organization, [str(link.source_ref), str(link.target_ref)]):
            drawn = self.drawn_edge(graph, link)
            if drawn is None:
                continue

            category = projector.categories_by_term(graph).get(link.term_id)
            if category is None:  # pragma: no cover - `drawn_edge` already returned None in this case
                continue

            drawings.append(results.EdgeDrawing(graph=graph, category=category, edge=drawn))

        return tuple(drawings)

    def _category_for_term(self, term_id: Any, graph: models.Graph | None = None) -> models.Category | None:
        """How a graph draws a word — its category for that term.

        With a graph, this view's answer. Without one, any view's: some callers
        return an edge that has no projection at all (structure relations,
        measurements) and only need the term's shape for the API. `None` is an
        ordinary answer, meaning no graph declares a category for this word.

        "Any view's" is the **lowest-id** one, not whichever the database happened
        to return, so two callers asking the same question get the same answer.

        It no longer decides what a *write* reports: a write returns `drawings`,
        where every category arrives attached to the graph that actually drew the
        claim. This is left for the edge payloads, which need the term's shape for
        the API even when nothing draws them — see `create_measurement`.
        """
        queryset = models.Category.objects.filter(term_id=term_id)
        if graph is not None:
            queryset = queryset.filter(graph=graph)
        return queryset.order_by("pk").first()

    def retrieved_edge(self, link: evidence_models.Link, category: models.Category | None = None) -> RetrievedEdge:
        """One claim, in the edge-shaped form the API reads.

        The read counterpart of the `RetrievedEdge.from_link(...)` call the write
        paths make, and the same shape: `row_id` is set, so `unique_id` is the
        claim's primary key and the id round-trips through the singular fetcher.
        The list queries used to build their own `RetrievedEdge` with no `row_id`
        and hand out `{age_name}:{vertex_id}` instead.

        ``category`` is passed when the caller already holds one — a category-keyed
        list has it in hand and would otherwise pay `_category_for_term` per row.
        """
        return RetrievedEdge.from_link(self, link, category=category if category is not None else self._category_for_term(link.term_id))

    def _node_ref(self, node_id: Any, info: Info | None = None, organization: Any = None) -> str:
        """Check a client-supplied node id and hand back the ref evidence stores.

        Which is the id itself — the client already holds the durable identity,
        so there is nothing to translate. What remains is worth keeping: this
        refuses an id that names no node, so a `Link` can never be written
        against something the log does not have — and, given an ``organization``,
        one that belongs to a different tenant than the claim being written.
        """
        return self._resolve_instance(node_id, info, organization=organization).ref

    def create_relation(
        self,
        organization: Any,
        term: evidence_models.Term,
        payload: RelationInput,
        info: Info,
    ) -> results.Asserted:
        """Assert that a relation holds between two entities.

        "This axon synapses onto that soma" is a claim, and claims are the thing
        a second lab disputes — so a relation is evidence, not graph structure.
        The `Link` row is the fact; the AGE edge is a projection of it, and
        `rebuild` replays the one from the other.

        Deliberately not deduplicated. Two subjects asserting the same relation
        are two rows, which is what makes agreement countable; the projection
        collapses them onto the single edge a traversal expects and records how
        many claims stand behind it.

        Names a term, so the edge is drawn in **every** view declaring the word —
        not only the one whose category the caller happened to hold. Endpoint
        category pairs are not checked here and never were; the
        `MaterializedRelationEdge` cross-product that might have looked like a
        guard was a read surface, and is gone (RFC 0001 §6).
        """
        source_ref = self._node_ref(payload.source_id, info, organization=organization)
        target_ref = self._node_ref(payload.target_id, info, organization=organization)

        # Evidence first, in one transaction — the same asymmetry `create_entity`
        # documents at length. AGE cannot join a Django transaction, so a failure
        # after this commit leaves durable evidence with no projection, which
        # `reproject` fixes. Do not "fix" it by deleting the evidence.
        with transaction.atomic():
            assertion = self._create_assertion(organization, self._provenance_from_info(info))
            _, recorded_metrics = self._materialize_supporting_evidence(
                organization=organization,
                supporting_evidence=payload.supporting_evidence or [],
                assertion=assertion,
                info=info,
            )
            link = writer.create_link(
                organization,
                kind=evidence_models.Link.Kind.RELATION,
                source_ref=source_ref,
                target_ref=target_ref,
                assertion=assertion,
                term=term,
            )
            self._attach_supporting_evidence(organization, link, recorded_metrics, assertion)

        # Only this proposition, not the whole graph. This used to pass
        # `active_relation_links(graph)` — every live relation there is — so one
        # new claim re-`MERGE`d every edge in the graph and N sequential calls
        # cost O(N x graph). The survivors of *this* proposition are what the
        # assertion count needs, and nothing else moved.
        self._reproject_proposition_everywhere(organization, source_ref, target_ref, term.pk)

        # The payload comes from the `Link` row, not from one graph's projection:
        # the edge is drawn in every view declaring the word, so there is no
        # single projection to prefer — and `Edge.id` is the link's primary key
        # anyway, so nothing a client can select comes from the AGE edge. Which
        # views drew it is `drawings`, where each answer keeps its graph.
        return results.Asserted.of(assertion, link, self.drawings_for_edge(link))

    def _attach_supporting_evidence(
        self,
        organization: Any,
        link: evidence_models.Link,
        recorded_metrics: list[evidence_models.Metric],
        assertion: evidence_models.Assertion,
    ) -> None:
        """Point an edge's supporting structures at the edge itself.

        The structures that justify "these two cells are connected" inform the
        *relation*, not either endpoint, so the INFORMS links target the edge's
        own durable ref. `project` skips refs with no `Instance` row, so these never
        reach node projection; folding the metrics now is what lets derived
        properties on edges become a read-side change later rather than a
        backfill.
        """
        edge_ref = self.edge_ref(link)
        for metric in recorded_metrics:
            writer.create_link(
                organization,
                kind=evidence_models.Link.Kind.INFORMS,
                source_ref=str(metric.structure_id),
                target_ref=edge_ref,
                assertion=assertion,
            )
            state_module.merge(metric, [edge_ref])

    @staticmethod
    def edge_ref(link: evidence_models.Link) -> str:
        """The durable identity of one edge assertion.

        A bare primary key, like every other evidence row. Relations are reached
        through a graph but *belong* to the organization, and naming one with a
        graph prefix would repeat the mistake `Structure` already corrected.
        """
        return str(link.pk)

    def create_structure_relation(
        self,
        organization: Any,
        term: evidence_models.Term,
        payload: RelationInput,
        info: Info,
    ) -> RetrievedEdge:
        """Assert that a relation holds between two structures.

        No projection. Structures stopped being AGE vertices in M1, so there is
        nothing here to draw an edge between — a structure relation is an
        evidence row and only an evidence row. That is not a gap: both endpoints
        are organization-scoped, so an edge in one graph's projection would be
        the wrong place to keep it.
        """
        source = self._resolve_structure(str(payload.source_id), info, organization=organization)
        target = self._resolve_structure(str(payload.target_id), info, organization=organization)

        with transaction.atomic():
            assertion = self._create_assertion(organization, self._provenance_from_info(info))
            _, recorded_metrics = self._materialize_supporting_evidence(
                organization=organization,
                supporting_evidence=payload.supporting_evidence or [],
                assertion=assertion,
                info=info,
            )
            link = writer.create_link(
                organization,
                kind=evidence_models.Link.Kind.STRUCTURE_RELATION,
                source_ref=str(source.pk),
                target_ref=str(target.pk),
                assertion=assertion,
                term=term,
            )
            self._attach_supporting_evidence(organization, link, recorded_metrics, assertion)

        # No drawings, and none possible: both endpoints are structures, which are
        # Postgres rows with no vertex, so `graphs_for_refs` returns nothing and
        # there is no edge to draw between them.
        return results.Asserted.of(assertion, link)

    def create_measurement(
        self,
        organization: Any,
        term: evidence_models.Term,
        payload: RelationInput,
        info: Info,
    ) -> RetrievedEdge:
        """Assert that a structure measures an entity, under an ontology term.

        The typed form of INFORMS: both say "this ROI is evidence for that cell",
        but a measurement also names *which* term of the schema the claim falls
        under. Writing the plain INFORMS link alongside it is not redundancy —
        `dirty()` matches on `kind=INFORMS`, so a measurement that skipped it
        would record the claim and silently never roll its metrics up.
        """
        source = self._resolve_structure(str(payload.source_id), info, organization=organization)
        target_ref = self._node_ref(payload.target_id, info, organization=organization)

        with transaction.atomic():
            assertion = self._create_assertion(organization, self._provenance_from_info(info))
            link = writer.create_link(
                organization,
                kind=evidence_models.Link.Kind.MEASUREMENT,
                source_ref=str(source.pk),
                target_ref=target_ref,
                assertion=assertion,
                term=term,
            )
            writer.create_link(
                organization,
                kind=evidence_models.Link.Kind.INFORMS,
                source_ref=str(source.pk),
                target_ref=target_ref,
                assertion=assertion,
            )
            for metric in writer.active_metrics_for_structures(organization, [source.pk]):
                state_module.merge(metric, [target_ref])

        self.project_refs(organization, [target_ref])
        # No drawings: a measurement's source is a structure, and nothing projects
        # a MEASUREMENT link to an AGE edge. What it *does* move is the target
        # entity's derived properties, which is what `project_refs` above did.
        return results.Asserted.of(assertion, link)

    def resolve_edge_link(self, edge_id: str, info: Info | None = None) -> evidence_models.Link:
        """Find the edge assertion a client named, and check it may be reached."""
        link = evidence_models.Link.all_objects.filter(pk=edge_id).first()
        if link is None:
            raise ValueError(f"No edge found with ID {edge_id}")
        self._assert_can_access(link.organization, info)
        return link

    def edge_term(self, link: evidence_models.Link) -> evidence_models.Term:
        """The word an edge claim was stated under.

        `Link.term` is nullable because `INFORMS` names no word — it says "this
        structure is evidence for that node" and nothing about what either is. So
        the update paths, which restate an existing claim under the same word, have
        to say what they mean when there is none rather than passing `None` down
        into a write.
        """
        if link.term is None:
            raise ValueError(f"Edge {link.pk} is a {link.kind}, which names no term; there is nothing to restate it under")
        return link.term

    def archive_relation(
        self,
        relation_id: str,
        info: Info,
    ) -> results.Asserted:
        """Retract one edge assertion without destroying it.

        Retracting is a claim in its own right, so it gets its own assertion and
        its own lifecycle row. The projected edge survives as long as any other
        live assertion still states the same proposition — which is the point of
        keeping assertions separate from the edge they agree on.

        Takes no graph. The edge id is the `Link` primary key, which says who may
        reach it and which views drew it; a caller-supplied graph could only be one
        of those views, and correcting one while leaving the rest is how a
        projection comes to hold an edge no standing claim supports.
        """
        from graph_engine import projector

        link = self.resolve_edge_link(relation_id, info)
        organization = link.organization

        with transaction.atomic():
            assertion = self._create_assertion(organization, self._provenance_from_info(info))
            writer.retract(organization, link, assertion)

        source_ref, target_ref, term_id = projector.proposition_key(link)
        self._reproject_proposition_everywhere(organization, source_ref, target_ref, term_id)
        # Read back, not assumed gone: the edge survives wherever another live
        # assertion still states the same proposition.
        return results.Asserted.of(assertion, link, self.drawings_for_edge(link))

    def _reproject_proposition(
        self,
        graph: models.Graph,
        organization: Any,
        source_ref: str,
        target_ref: str,
        term_id: Any,
    ) -> None:
        """Bring one edge in AGE back in line with the assertions behind it.

        Relations only. Structure relations and measurements have no projected
        edge to correct, so there is nothing here for them to do.
        """
        from graph_engine import projector

        survivors = list(
            claims_module.standing(
                evidence_models.Link.objects.for_organization(organization).filter(
                    kind=evidence_models.Link.Kind.RELATION,
                    source_ref=source_ref,
                    target_ref=target_ref,
                    term_id=term_id,
                ),
                "link",
            ).select_related("term")
        )

        if survivors:
            projector.project_edges(self, graph, survivors)
            return

        # This graph's label for the word, which is what the edge was drawn under.
        category = projector.categories_by_term(graph).get(term_id)
        if category is None:
            return

        # No live claim left, so the edge states nothing. It goes, rather than
        # lingering with a lifecycle flag: `rebuild` would not recreate it, and a
        # projection that disagrees with a replay is the failure this layer is
        # supposed to make impossible.
        source_uuid = str(source_ref)
        target_uuid = str(target_ref)
        self.engine.execute(
            graph,
            f"""
            MATCH (s)-[r:{category.age_name}]->(t)
            WHERE s.id = $src AND t.id = $tgt
            DELETE r
            """,
            {"src": source_uuid, "tgt": target_uuid},
        )

    # ===================================================================
    # Relation Query Methods
    # ===================================================================

    def get_relation_by_id(self, edge_id: str, info: Info | None = None) -> Optional[RetrievedEdge]:
        """Read one edge assertion back by its evidence id.

        Takes the `Link` primary key, not an AGE edge id. Edges are addressed by
        the claim that made them, which is the only identity that survives a
        `reproject` — and the only one structure relations and measurements have
        at all, since neither is projected.

        This used to read `self.graph` and `self.age_name`, which
        `GraphController.__init__` never assigns, so every archive mutation
        raised `AttributeError` after doing its write. Nothing caught it because
        no test reaches the relation surface.
        """
        link = evidence_models.Link.all_objects.filter(pk=edge_id).first()
        if link is None:
            return None
        self._assert_can_access(link.organization, info)
        return RetrievedEdge.from_link(self, link, category=self._category_for_term(link.term_id))

    def drawn_edge(self, graph: models.Graph, link: evidence_models.Link) -> Optional[RetrievedEdge]:
        """This link as the graph actually draws it, or `None` if it does not.

        The edge half of "where does this claim materialize". `None` is an
        ordinary answer with three ordinary causes: the view declares no category
        for the claim's word, one of the endpoints is not in this projection, or
        the link is of a kind that has no AGE edge at all (measurements and
        structure relations — see `docs/LOG.md`).

        Reads the projection rather than deriving the answer from what the write
        path *intended*, which is what makes it stay correct as the write path is
        corrected.
        """
        from graph_engine import projector

        category = projector.categories_by_term(graph).get(link.term_id)
        if category is None:
            return None

        # Label and direction from the shared helper — `project_participation`
        # draws an output participation event → entity while `participation_key`
        # stores entity → event, so a fixed `(source)-[r]->(target)` pattern here
        # would silently never match one of the two sides.
        label, reversed_edge = projector.edge_pattern_for(category, link)
        left, right = (str(link.target_ref), str(link.source_ref)) if reversed_edge else (str(link.source_ref), str(link.target_ref))

        result = self.engine.execute(
            graph,
            f"""
            MATCH (s)-[r:{label}]->(t)
            WHERE s.id = $src AND t.id = $tgt
            RETURN id(r) as id, id(s) as sid, id(t) as tid
            """,
            {"src": left, "tgt": right},
        )
        if not result:
            return None

        edge = RetrievedEdge.from_link(self, link, graph_name=graph.age_name, category=category)
        edge.edge_id = int(result[0]["id"])
        edge.left_id = int(result[0]["sid"])
        edge.right_id = int(result[0]["tid"])
        return edge

    def render_graph_table_query(
        self, graph_query: models.GraphTableQuery, filters: input_models.RenderGraphTableFilter | None = None, pagination: input_models.RenderGraphTablePagination | None = None, order: input_models.RenderGraphTableOrder | None = None, info: Info | None = None
    ) -> RetrievedGraphTableRender:
        """Render a set of nodes matching the graph query, with optional filters, pagination, and ordering."""
        self._ensure_query_access(graph_query.graph, info)
        query, params = self._compose_graph_table_query(
            graph_query.query,
            filters=filters,
            pagination=pagination,
            order=order,
        )

        result_rows = self.engine.execute(graph_query.graph, query, params)

        row_dicts: list[dict[str, Any]] = []
        column_keys = [column.get("key") for column in (graph_query.columns or []) if isinstance(column, dict) and column.get("key")]

        for row in result_rows:
            if isinstance(row, dict):
                row_dicts.append(row)
                continue

            if isinstance(row, (list, tuple)):
                mapped = {(column_keys[index] if index < len(column_keys) else f"col_{index}"): value for index, value in enumerate(row)}
                row_dicts.append(mapped)
                continue

            row_dicts.append({"value": row})

        return RetrievedGraphTableRender(
            graph_name=str(graph_query.graph.age_name),
            graph_id=int(graph_query.graph_id),
            graph_query_id=int(graph_query.id),
            rows=row_dicts,
        )

    def _compose_graph_table_query(
        self,
        base_query: str,
        filters: input_models.RenderGraphTableFilter | None = None,
        pagination: input_models.RenderGraphTablePagination | None = None,
        order: input_models.RenderGraphTableOrder | None = None,
    ) -> tuple[str, dict[str, Any]]:
        query = base_query.strip().rstrip(";")
        params: dict[str, Any] = {}

        filter_clause, filter_params = self._build_graph_table_filter_clause(filters)
        params.update(filter_params)

        if filter_clause:
            query = self._inject_graph_table_filter(query, filter_clause)

        if order:
            key = self._validate_property_key(order.key)
            direction = str(order.direction).lower()
            direction = "DESC" if direction == "desc" else "ASC"
            query = f"{query}\nORDER BY {key} {direction}"

        if pagination:
            if pagination.offset is not None and pagination.offset > 0:
                query = f"{query}\nSKIP {int(pagination.offset)}"
            if pagination.limit is not None:
                query = f"{query}\nLIMIT {int(pagination.limit)}"

        return query, params

    def _build_graph_table_filter_clause(
        self,
        filters: input_models.RenderGraphTableFilter | None,
    ) -> tuple[str, dict[str, Any]]:
        if not filters:
            return "", {}

        key = self._validate_property_key(filters.key)
        operator = str(filters.operator).upper()
        value = self._coerce_filter_value(filters.value)
        value_param = "graph_table_filter_value"

        params = {value_param: value}

        if operator in {"EQUALS", "EQ", "="}:
            return f"{key} = ${value_param}", params
        if operator in {"NOT_EQUALS", "NEQ", "!="}:
            return f"{key} <> ${value_param}", params
        if operator in {"GREATER_THAN", "GT", ">"}:
            return f"{key} > ${value_param}", params
        if operator in {"LESS_THAN", "LT", "<"}:
            return f"{key} < ${value_param}", params
        if operator in {"GREATER_OR_EQUAL", "GREATER_THAN_OR_EQUAL", "GTE", ">="}:
            return f"{key} >= ${value_param}", params
        if operator in {"LESS_OR_EQUAL", "LESS_THAN_OR_EQUAL", "LTE", "<="}:
            return f"{key} <= ${value_param}", params
        if operator == "CONTAINS":
            return f"toString({key}) CONTAINS toString(${value_param})", params
        if operator == "STARTS_WITH":
            return f"toString({key}) STARTS WITH toString(${value_param})", params
        if operator == "ENDS_WITH":
            return f"toString({key}) ENDS WITH toString(${value_param})", params
        if operator == "IN":
            return f"{key} IN ${value_param}", params
        if operator == "NOT_IN":
            return f"NOT {key} IN ${value_param}", params

        raise ValueError(f"Unsupported filter operator '{operator}'.")

    def _inject_graph_table_filter(self, query: str, filter_clause: str) -> str:
        return_matches = list(re.finditer(r"\bRETURN\b", query, flags=re.IGNORECASE))
        if not return_matches:
            return f"{query}\nWHERE {filter_clause}"

        insert_at = return_matches[-1].start()
        prefix = query[:insert_at].rstrip()
        suffix = query[insert_at:].lstrip()

        if re.search(r"\bWHERE\b", prefix, flags=re.IGNORECASE):
            prefix = f"{prefix}\nAND {filter_clause}"
        else:
            prefix = f"{prefix}\nWHERE {filter_clause}"

        return f"{prefix}\n{suffix}"

    def _validate_property_key(self, key: str) -> str:
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            raise ValueError(f"Invalid property key '{key}'.")
        return key

    def indexed_property_keys(self, category: models.Category) -> set[str]:
        """Which of a category's properties are stored on the node — now all of them.

        Every derived property is materialized, so every one is filterable and
        sortable. This used to return only the `index=True` subset, because those
        were the only ones written to Apache AGE; the rest were folded on read and
        a Cypher predicate against one matched nothing.

        The set is still computed rather than assumed, because a property with no
        derivation rule is not written by anything — `projector.is_derived` stays
        the one definition of what the projection produces.
        """
        from graph_engine.projector import is_derived

        # `id` is the one property written directly, by `create_entity` itself,
        # so it is on the node whether or not the schema declares it.
        keys = {"id"}
        keys |= {prop.key for prop in (category.defined_properties or []) if is_derived(prop)}
        return keys

    def _assert_indexed(self, key: str, indexed_keys: set[str] | None) -> str:
        """Reject filtering or sorting on a property the projection does not write.

        Much narrower than it used to be. Every *derived* property is on the node
        now, so this no longer refuses the majority of the schema — it catches a
        key that names nothing at all, where a Cypher predicate would match zero
        rows and be indistinguishable from "nothing satisfies this".
        """
        validated = self._validate_property_key(key)
        if indexed_keys is not None and validated not in indexed_keys:
            raise ValueError(f"Cannot filter or sort on '{key}': no derivation rule writes it, so it is not on the node. Properties on this category: {sorted(indexed_keys) or '(none)'}.")
        return validated

    def _validate_direction(self, direction: Any) -> str:
        """Whitelist a sort direction before it is interpolated into Cypher.

        `.upper()` is not validation. The direction reaches this from a GraphQL
        variable and lands directly in the query text, so anything other than an
        exact ASC/DESC is a Cypher injection — the same hole `_validate_property_key`
        closes for keys, left open for the clause right next to them.
        """
        value = (direction.value if hasattr(direction, "value") else str(direction)).upper()
        if value not in {"ASC", "DESC"}:
            raise ValueError(f"Invalid sort direction '{direction}'. Expected ASC or DESC.")
        return value

    def _coerce_filter_value(self, value: Any) -> Any:
        if not isinstance(value, str):
            return value

        lowered = value.lower()
        if lowered in {"true", "false"}:
            return lowered == "true"

        try:
            if "." in value:
                return float(value)
            return int(value)
        except ValueError:
            return value

    def _build_entity_where_clause(self, filters: input_models.EntityFilters | None, variable: str = "e", indexed_keys: set[str] | None = None) -> tuple[str, dict[str, Any]]:
        params: dict[str, Any] = {}
        clauses: list[str] = []

        if not filters:
            return "", params

        if filters.category:
            params["filter_category"] = filters.category
            clauses.append(f"labels({variable})[0] = $filter_category")

        if filters.ids:
            # The node's own uuid, held as a vertex property — not `id(e)`, the
            # AGE vertex id. A client's id is the durable one, and the vertex id
            # is reassigned by every reproject.
            params["filter_ids"] = [str(entity_id) for entity_id in filters.ids]
            clauses.append(f"{variable}.id IN $filter_ids")

        if filters.search:
            params["filter_search"] = filters.search
            clauses.append(f"{variable}.label CONTAINS $filter_search")

        if filters.has_property:
            key = self._assert_indexed(filters.has_property, indexed_keys)
            clauses.append(f"{variable}.{key} IS NOT NULL")

        if filters.matches:
            for index, match in enumerate(filters.matches):
                key = self._assert_indexed(match.key, indexed_keys)
                operator = match.operator.value if hasattr(match.operator, "value") else str(match.operator)
                operator = operator.upper()

                value_param = f"match_value_{index}"
                coerced_value = self._coerce_filter_value(match.value)
                field_expr = f"{variable}.{key}"

                if key == "id":
                    # Matched as the uuid string it is. The old branch tried three
                    # ways to turn an id into the integer AGE vertex id, because
                    # that is what `id(e)` compares against; there is nothing left
                    # to unpick now that a node's id is its uuid.
                    coerced_value = str(match.value)

                params[value_param] = coerced_value

                if operator in {"EQUALS", "EQ", "="}:
                    clauses.append(f"{field_expr} = ${value_param}")
                elif operator in {"NOT_EQUALS", "NEQ", "!="}:
                    clauses.append(f"{field_expr} <> ${value_param}")
                elif operator in {"GREATER_THAN", "GT", ">"}:
                    clauses.append(f"{field_expr} > ${value_param}")
                elif operator in {"LESS_THAN", "LT", "<"}:
                    clauses.append(f"{field_expr} < ${value_param}")
                elif operator in {"GREATER_OR_EQUAL", "GREATER_THAN_OR_EQUAL", "GTE", ">="}:
                    clauses.append(f"{field_expr} >= ${value_param}")
                elif operator in {"LESS_OR_EQUAL", "LESS_THAN_OR_EQUAL", "LTE", "<="}:
                    clauses.append(f"{field_expr} <= ${value_param}")
                elif operator == "CONTAINS":
                    clauses.append(f"{field_expr} CONTAINS ${value_param}")
                elif operator == "STARTS_WITH":
                    clauses.append(f"{field_expr} STARTS WITH ${value_param}")
                elif operator == "ENDS_WITH":
                    clauses.append(f"{field_expr} ENDS WITH ${value_param}")
                elif operator == "IN":
                    clauses.append(f"{field_expr} IN ${value_param}")
                elif operator == "NOT_IN":
                    clauses.append(f"NOT {field_expr} IN ${value_param}")
                else:
                    raise ValueError(f"Unsupported filter operator '{operator}'.")

        return ("WHERE " + " AND ".join(clauses)) if clauses else "", params

    def _build_entity_order_clause(self, order: list[input_models.EntityOrder] | None, variable: str = "e", indexed_keys: set[str] | None = None) -> str:
        if not order:
            return ""

        clauses = []
        for o in order:
            if o.property is not None:
                key = self._assert_indexed(o.property.key, indexed_keys)
                direction = self._validate_direction(o.property.direction)
                clauses.append(f"{variable}.{key} {direction}")
            elif o.created_at is not None:
                direction = self._validate_direction(o.created_at)
                clauses.append(f"{variable}.created_at {direction}")
            elif o.id is not None:
                direction = self._validate_direction(o.id)
                clauses.append(f"id({variable}) {direction}")
        if not clauses:
            return ""
        return f"ORDER BY {', '.join(clauses)}"

    def _build_entity_pagination_clause(self, pagination: input_models.EntityPagination | None) -> str:
        if not pagination:
            return "SKIP 0 LIMIT 200"

        offset = pagination.offset if pagination.offset is not None else 0
        limit = pagination.limit if pagination.limit is not None else 200
        return f"SKIP {offset} LIMIT {limit}"

    # `list_entities(graph=…)` used to sit here, and it was what `nodes(graph:)` and
    # `entities(entityCategoryId:)` were built on. It matched `labels(e)[0] IN
    # <this graph's entity categories>`, so it answered two questions wrongly at
    # once: *nodes* meant entities, and *entities* meant the ones the projection had
    # drawn. Both are decided from the claims now — `projector.refs_in_graph` and
    # `refs_admitted_by`, read through `api/queries/_nodes.py`.

    def list_entities_for_category(self, category: models.EntityCategory, filters: input_models.EntityFilters | None = None, pagination: input_models.EntityPagination | None = None, ordering: list[input_models.EntityOrder] | None = None, info: Info | None = None) -> List[RetrievedNode]:
        """This view's **drawing**, queried on the derived properties it has indexed.

        A drawing-scoped read, and the only honest use of one: filtering by
        `has_property` or a property match is a question about values the view
        derived, which exist nowhere else — `_assert_indexed` is what keeps it to the
        keys the schema said to index. No GraphQL field is built on it now that the
        entity lists are claim-grain; `EntityCategory.entities` answers what the
        category *admits*, which is a different question and cannot be asked of AGE.
        """
        self._ensure_query_access(category.graph, info)

        indexed_keys = self.indexed_property_keys(category)
        where_clause, filter_params = self._build_entity_where_clause(filters, variable="e", indexed_keys=indexed_keys)
        order_clause = self._build_entity_order_clause(ordering, variable="e", indexed_keys=indexed_keys)
        pagination_clause = self._build_entity_pagination_clause(pagination)

        # `WHERE true` so the filter can be appended with AND, exactly as
        # `list_entities` does. Without it this emitted `MATCH (e:X) AND ...`,
        # which is a Cypher syntax error — so filtering by category has never
        # worked, and no test passed a filter here to find out.
        query = f"""
            MATCH (e: {category.get_age_vertex_name()})
            WHERE true
            {("AND " + where_clause[len("WHERE ") :]) if where_clause else ""}
            RETURN e
            {order_clause}
            {pagination_clause}
        """

        params: dict[str, Any] = {**filter_params}
        result = self.engine.execute(category.graph, query, params)

        return [RetrievedNode.from_node(self, row["e"], graph_name=category.graph.age_name) for row in result]

    def list_structures(self, organization: Any, filters: input_models.StructureFilters | None = None, pagination: input_models.StructurePagination | None = None, ordering: list[input_models.StructureOrder] | None = None, info: Info | None = None) -> List[RetrievedStructure]:
        """List structures from the evidence base.

        Takes an organization, not a graph. A structure points at an external
        datum and is shared by every projection over that organization's
        evidence, so scoping the list to one graph would have been arbitrary.
        """
        queryset = evidence_models.Structure.objects.for_organization(organization)
        queryset = self._apply_structure_filters(queryset, filters)
        queryset = queryset.order_by(*self._structure_ordering(ordering))

        offset = pagination.offset if pagination and pagination.offset is not None else 0
        limit = pagination.limit if pagination and pagination.limit is not None else 200

        return [RetrievedStructure.from_row(self, row) for row in queryset[offset : offset + limit]]

    def _apply_structure_filters(self, queryset: Any, filters: input_models.StructureFilters | None) -> Any:
        """Translate structure filters into ORM predicates.

        Property filters resolve against *metrics*, because a structure carries
        no values of its own — it is only the thing measurements are about.
        """
        if not filters:
            return queryset

        if filters.ids:
            # Bare uuids: the `{graph}:{id}` composite this used to strip is gone
            # from every id the API hands out.
            queryset = queryset.filter(pk__in=[str(gid) for gid in filters.ids])

        if filters.category:
            queryset = queryset.filter(identifier=filters.category)

        if filters.search:
            queryset = queryset.filter(object__icontains=filters.search)

        if filters.has_property:
            queryset = queryset.filter(metrics__key=filters.has_property)

        for match in filters.matches or []:
            operator = (str(match.operator).split(".")[-1] if match.operator is not None else "EQUALS").upper()
            if operator == "NOT_IN":
                queryset = queryset.exclude(metrics__key=match.key, **self._metric_value_predicate("IN", match.value))
            else:
                queryset = queryset.filter(metrics__key=match.key, **self._metric_value_predicate(operator, match.value))

        return queryset.distinct()

    _MATCH_LOOKUPS: Dict[str, str] = {
        "EQUALS": "",
        "EQ": "",
        "=": "",
        "GREATER_THAN": "__gt",
        "GT": "__gt",
        ">": "__gt",
        "LESS_THAN": "__lt",
        "LT": "__lt",
        "<": "__lt",
        "GREATER_OR_EQUAL": "__gte",
        "GREATER_THAN_OR_EQUAL": "__gte",
        "GTE": "__gte",
        ">=": "__gte",
        "LESS_OR_EQUAL": "__lte",
        "LESS_THAN_OR_EQUAL": "__lte",
        "LTE": "__lte",
        "<=": "__lte",
        "CONTAINS": "__contains",
        "STARTS_WITH": "__startswith",
        "ENDS_WITH": "__endswith",
        "IN": "__in",
    }

    def _metric_value_predicate(self, operator: str, value: Any) -> Dict[str, Any]:
        """Build the ORM predicate for a metric value comparison.

        Picks the typed column from the value's own type. Text operators are only
        meaningful against `value_txt`, and ordering operators only against
        `value_num`, so a mismatch is rejected rather than silently matching
        nothing.
        """
        coerced = self._coerce_filter_value(value)
        column = "value_txt" if isinstance(coerced, str) else "value_bool" if isinstance(coerced, bool) else "value_num"

        if operator not in self._MATCH_LOOKUPS:
            raise ValueError(f"Unsupported filter operator '{operator}'.")

        lookup = self._MATCH_LOOKUPS[operator]
        if lookup in {"__contains", "__startswith", "__endswith"} and column != "value_txt":
            raise ValueError(f"Operator '{operator}' needs a string value, got {type(coerced).__name__}.")

        return {f"metrics__{column}{lookup}": coerced}

    def _structure_ordering(self, ordering: list[input_models.StructureOrder] | None) -> List[str]:
        """Translate structure ordering into ORM order_by terms."""
        if not ordering:
            return ["created_at"]

        terms: List[str] = []
        for order in ordering:
            # `property` is no longer a field on `StructureOrder`: it used to be
            # silently reinterpreted as ordering by `object`, which is not what
            # anyone asking for a property order meant.
            if order.created_at is not None:
                direction = order.created_at
                field = "created_at"
            elif order.id is not None:
                direction = order.id
                field = "id"
            else:
                continue
            descending = (direction.value if hasattr(direction, "value") else str(direction)).upper() == "DESC"
            terms.append(f"-{field}" if descending else field)

        return terms or ["created_at"]
