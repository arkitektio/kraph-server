"""
Graph Materialization Module

This module handles the creation of Django database models from a GraphDefinitionModel.
It creates EntityCategory, RelationCategory, NaturalEventCategory, and GraphSchema
instances from the schema definition.
"""

import hashlib
import json
import logging
from typing import Optional
from pydantic import BaseModel, Field

from .input_models import DerivationType, GraphDefinitionInput
from .projection import Projector
from core import models
from authentikate.models import Organization, Membership, User

logger = logging.getLogger(__name__)


def compute_definition_hash(definition: "GraphDefinitionInput | dict") -> str:
    """
    Compute a stable hash of a graph definition, for versioning.

    Accepts either the pydantic input or the JSON dict stored on
    `GraphSchema.definition`, because both spellings of the same schema must hash
    identically — otherwise a schema would appear to change simply by being read
    back out of the database. Dict input is dumped with sorted keys for the same
    reason.

    Args:
        definition: The graph definition, as a model or as its JSON form

    Returns:
        A short SHA256 digest
    """
    if hasattr(definition, "model_dump_json"):
        json_str = definition.model_dump_json(exclude_none=True)
    else:
        json_str = json.dumps(_strip_none(definition), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(json_str.encode()).hexdigest()[:16]


def _strip_none(value: object) -> object:
    """Drop null values so a dict hashes like `model_dump_json(exclude_none=True)`."""
    if isinstance(value, dict):
        return {k: _strip_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_strip_none(item) for item in value]
    return value


def compute_properties_hash(properties: list) -> str:
    """
    Compute a stable hash of property definitions for versioning.

    Args:
        properties: List of property definition dicts

    Returns:
        SHA256 hash string
    """
    sorted_props = sorted(properties, key=lambda p: p.get("key", ""))
    json_str = json.dumps(sorted_props, sort_keys=True, default=str)
    return hashlib.sha256(json_str.encode()).hexdigest()[:16]


def edge_property_problems(owner: str, property_definitions: list | None) -> list[str]:
    """Why an edge cannot carry the properties declared on it. Empty if none were.

    Shared by `validate_derivation_rules`, which checks a whole schema before
    materializing it, and by the three `create_*_category` mutations, which take
    an edge definition one at a time and never reach that function. Both surfaces
    accept the same input, so both have to refuse it — a guard on only one of
    them would just move the silent empty result to the other.
    """
    if not property_definitions:
        return []

    return [f"{owner}.{prop.key}: an edge carries no derived properties. `project_edges` writes only `category_id` and `__assertion_count`, so a rule declared here would never run. Roll the value up onto one of the endpoints instead." for prop in property_definitions]


def validate_derivation_rules(definition: GraphDefinitionInput) -> None:
    """Reject derived properties the state vector cannot compute.

    Runs before anything is written, so an unsatisfiable schema fails at
    materialization rather than producing categories whose properties silently
    never populate. That silence is the failure mode this whole milestone exists
    to remove: rules with no metric key used to render as `WHERE m.key = null`,
    which never matches, so the property stayed unset and any test asserting on it
    passed vacuously.

    Structures are resolved dynamically at write time, so a schema never
    enumerates them and there is no positive list to check a source against.
    What the schema *does* enumerate is its entity and event kinds — and naming
    one of those as a rollup source is the mistake worth catching, so that is
    what gets passed down as the forbidden set.
    """
    from graph_engine.aggregate import UnsupportedRule, validate_rule

    entity_and_event_keys = {entity.key for entity in definition.extensions.entities}
    entity_and_event_keys |= {event.key for event in definition.extensions.events}

    problems: list[str] = []

    def check(owner: str, property_definitions: list) -> None:
        for prop in property_definitions:
            # A property with no rule naming a source is not expressible. There
            # is no mutation that sets one, `project` writes only derived values,
            # and the read path resolves only derived values — so it was declared,
            # stored nowhere, and readable through nothing, while
            # `indexed_property_keys` still admitted it to the filterable set and
            # let a Cypher predicate against it match silently. `id` is exempt:
            # it is the node's identity, written by `create_entity` itself.
            if prop.key != "id" and (prop.rule is None or not getattr(prop.rule, "source_node", None)):
                problems.append(f"{owner}.{prop.key}: a property needs a `rule` naming a `source_node` to be computable. Nothing writes a property directly — record a metric against a structure that informs this node and give the property a rule that rolls it up.")
                continue
            if prop.derivation != DerivationType.ROLLUP or prop.rule is None:
                continue
            try:
                validate_rule(prop.rule, forbidden_sources=entity_and_event_keys)
            except UnsupportedRule as error:
                problems.append(f"{owner}.{prop.key}: {error}")

    def check_edge(owner: str, property_definitions: list) -> None:
        """An edge carries no derived properties at all, so refuse every one.

        `projector.project_edges` writes `category_id` and `__assertion_count`
        onto a relationship and stops; measurements are not drawn as AGE edges at
        all, only read back from their `Link` rows. No derivation rule has ever
        run for an edge category — so a rule declared on one is not "computed
        later", it is never computed, and the property reads as permanently
        absent.

        This used to fall through `check` above, which accepts any property
        carrying a well-formed rule. The result was that the API accepted,
        *validated* and stored a rule nothing would execute, and the client got a
        valid schema and an empty property with no error at any point — the
        silent-empty-result this function exists to eliminate, one layer over
        from where it was first found.

        Refusing rather than warning, for the same reason a rule-less node
        property is refused: an unsatisfiable schema should fail where it is
        declared. If edges gain derived properties later, this is the guard to
        remove — and `project_edges` is where the work would go, needing a state
        grain keyed on the proposition rather than on the entity.
        """
        problems.extend(edge_property_problems(owner, property_definitions))

    for entity in definition.extensions.entities:
        check(entity.key, entity.property_definitions)
    for event in definition.extensions.events:
        check(event.key, event.properties)

    # Relations, structure relations and measurements are edges. They are checked
    # by a different rule, not a stricter version of the same one — see
    # `check_edge`.
    for relation in definition.extensions.relations:
        check_edge(relation.key, relation.properties)
    for structure_relation in definition.extensions.structure_relations:
        check_edge(structure_relation.key, structure_relation.properties)
    for measurement in definition.extensions.measurements:
        check_edge(measurement.key, measurement.properties)

    if problems:
        raise ValueError("Schema has derivation rules that cannot be computed:\n  - " + "\n  - ".join(problems))


def materialize(
    definition: GraphDefinitionInput,
    projector: Projector | None = None,
    user: User | None = None,
    organization: Organization | None = None,
    membership: Membership | None = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    backfill: bool = False,
) -> models.Graph:
    """
    Materialize a graph based on the provided graph definition.

    This creates all database models from the schema definition:
    - Graph: The root graph container
    - EntityCategory: For each entity definition
    - RelationCategory: For each relation definition
    - NaturalEventCategory: For each event definition
    - GraphSchema: The schema definition

    Args:
        definition: GraphDefinitionModel containing the graph schema definition
        projector: The projection kind the new view is drawn in (default: the table projector)
        name: Optional name for the graph (defaults to "graph_{hash}")
        description: Optional description for the graph
        user: Optional user for the graph (required for production)
        organization: Optional organization for the graph (required for production)
        membership: Optional membership for the graph (required for production)
        backfill: Draw the evidence this graph's words already admit. Off by
            default because it is O(the organization's evidence) and synchronous;
            a caller who knows the organization has history worth showing asks for
            it. Without it a new view over old evidence comes up empty until
            someone runs `manage.py reproject`.

    Returns:
        The materialized Graph instance with all related models created
    """

    # Fail before writing anything if the schema asks for a derivation that
    # cannot be computed.
    validate_derivation_rules(definition)

    # Compute schema hash for versioning
    schema_hash = compute_definition_hash(definition)

    # Generate name if not provided
    if name is None:
        name = f"graph_{schema_hash}"

    # The projection handle is random and assigned by the model default — see
    # `core.models.new_projection_handle` for why it is neither derived from the
    # name nor accepted from anyone.
    graph = models.Graph.objects.create(
        name=name,
        description=description or f"Graph materialized from schema v{definition.system_version}",
        user=user,
        organization=organization,
        membership=membership,
        rules=[rule.model_dump(mode="json") for rule in definition.rules],
    )

    # The projection kind this view is drawn in.
    if projector is None:
        from graph_engine.projection.table import TableProjector

        projector = TableProjector()

    # For the table kind this is a no-op — the namespace is the graph key on the
    # rows — but the call stays: it is the protocol's word for "make the place
    # this view's drawing lives in", and another kind may need one.
    projector.create_namespace(graph)

    # One schema change, not one per category row. Without suspending, the
    # post_save signal would emit a version for every category created below and
    # the history would describe insertion order rather than user intent.
    from graph_engine import versioning

    with versioning.suspended():
        _materialize_categories(graph, definition, user)

    # The projection's bookkeeping row. A view that is not backfilled over evidence
    # it already admits is honestly `NEEDS_BACKFILL` — its cursor reads 0 and its
    # lag is the whole log — until somebody runs `reproject`. A view that admits
    # nothing yet is consistent from the start: every claim that comes is drawn by
    # the write path.
    from evidence import selector as selector_module
    from graph_engine import watermark

    admits_history = selector_module.instances_for(graph).exists()
    if backfill or not admits_history:
        watermark.mark_consistent(graph, through_seq=watermark.max_seq(organization), schema_hash=watermark.active_schema_hash(graph))
    else:
        watermark.projection_for(graph)  # created in its default state: NEEDS_BACKFILL

    if backfill:
        # `project_all`, not `rebuild`. The namespace was created five lines up and
        # is empty, so there is nothing to drop; and `rebuild` ends with
        # `refold_state(organization)`, which re-folds every metric in the
        # organization — not something one new view is entitled to do to statistics
        # its siblings are reading.
        from graph_engine import projector as projector_module
        from graph_engine.controller import GraphController

        counts = projector_module.project_all(GraphController(projector=projector), graph)
        # `unclassified` too: a backfill that drew nothing and one whose every
        # candidate was refused by a definition are indistinguishable from the
        # `Graph` row this returns, and the second is the one worth knowing about.
        logger.info(
            "graph #%s: backfilled %s node(s) and %s edge(s) from existing evidence; %s admitted by no category.",
            graph.pk,
            counts["nodes"],
            counts["edges"],
            counts["unclassified"],
        )

    return graph


def _materialize_categories(graph, definition: GraphDefinitionInput, user) -> None:
    """Create every category the definition declares, plus the initial schema.

    Each category declares one of the organization's terms, minted here if this is
    the first graph to use the word. That is the join the evidence log names: a
    claim says "AIS", and every view with a category for "AIS" can read it.
    """
    from core import enums as core_enums
    from evidence import writer as evidence_writer

    organization = graph.organization

    def term_for(kind, key):
        return evidence_writer.ensure_term(organization, kind, key)

    # Create EntityCategories
    for entity_def in definition.extensions.entities:
        models.EntityCategory.objects.create_from_entity_definition(
            graph=graph,
            definition=entity_def,
        )

    # Create RelationCategories
    for relation_def in definition.extensions.relations:
        source_def = relation_def.source.model_dump(mode="json")
        target_def = relation_def.target.model_dump(mode="json")

        # Get properties from materialization config if present
        property_defs = []

        models.RelationCategory.objects.create(
            graph=graph,
            term=term_for(core_enums.CategoryKindChoices.RELATION, relation_def.key),
            age_name=relation_def.key.upper(),
            key=relation_def.key,
            label=relation_def.key,
            description=getattr(relation_def, "description", None) or "",
            source_definition=source_def,
            target_definition=target_def,
            property_definitions=[p.model_dump(mode="json") for p in relation_def.properties],
        )

    # Create StructureRelationCategories
    #
    # `extensions.structure_relations` and `extensions.measurements` were parsed
    # and then dropped on the floor: a schema could declare either one and no
    # category was ever created, so `createStructureRelation` and
    # `createMeasurement` had no term to name and the fields were decoration.
    for structure_relation_def in definition.extensions.structure_relations:
        models.StructureRelationCategory.objects.create(
            graph=graph,
            term=term_for(core_enums.CategoryKindChoices.STRUCTURE_RELATION, structure_relation_def.key),
            age_name=structure_relation_def.key.upper(),
            key=structure_relation_def.key,
            label=structure_relation_def.key,
            description=getattr(structure_relation_def, "description", None) or "",
            source_definition=structure_relation_def.source.model_dump(mode="json"),
            target_definition=structure_relation_def.target.model_dump(mode="json"),
            property_definitions=[p.model_dump(mode="json") for p in structure_relation_def.properties],
        )

    # Create MeasurementCategories
    for measurement_def in definition.extensions.measurements:
        models.MeasurementCategory.objects.create(
            graph=graph,
            term=term_for(core_enums.CategoryKindChoices.MEASUREMENT, measurement_def.key),
            age_name=measurement_def.key.upper(),
            key=measurement_def.key,
            label=measurement_def.key,
            description=getattr(measurement_def, "description", None) or "",
            source_definition=measurement_def.source.model_dump(mode="json"),
            target_definition=measurement_def.target.model_dump(mode="json"),
            property_definitions=[p.model_dump(mode="json") for p in measurement_def.properties],
        )

    # Create NaturalEventCategories
    for event_def in definition.extensions.events:
        property_defs = [p.model_dump(mode="json") for p in event_def.properties]
        props_hash = compute_properties_hash(property_defs)

        # Map inputs/outputs to source/target roles
        source_roles = [p.model_dump(mode="json") for p in event_def.inputs]
        target_roles = [p.model_dump(mode="json") for p in event_def.outputs]

        models.NaturalEventCategory.objects.create(
            graph=graph,
            term=term_for(core_enums.CategoryKindChoices.NATURAL_EVENT, event_def.key),
            age_name=event_def.key,
            # Set like every other category kind. Events were the one kind that
            # left `key` null, so `filter(key=...)` — how the rest of the codebase
            # finds a category — could never find an event, and
            # `snapshot_definition` emitted events whose key was None.
            key=event_def.key,
            label=event_def.key,
            description=getattr(event_def, "description", None) or "",
            property_definitions=property_defs,
            schema_hash=props_hash,
            source_entity_roles=source_roles,
            target_entity_roles=target_roles,
        )

    # The initial schema version. `activate()` is the only path that sets
    # is_active, and a partial unique constraint enforces one active schema per
    # graph — the old code hardcoded index=1 and is_active=True and never called
    # activate at all, so a second materialization would have produced two active
    # schemas.
    schema = models.GraphSchema(
        graph=graph,
        version=definition.system_version,
        index=None,
        definition=definition.model_dump(mode="json"),
        created_by=user,
        is_active=False,
    )
    schema.save()
    schema.activate()
