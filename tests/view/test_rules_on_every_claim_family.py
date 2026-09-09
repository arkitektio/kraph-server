"""Rules apply to every claim family a category can be declared over (RFC 0012).

Structure relations and measurements are claims like everything else, so their
categories carry the same rule lists entities, relations and events do: the
documents that must build, the ones that must be refused, and the behaviour
each family's rules drive.
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from core import models as core_models
from evidence import models as evidence_models
from evidence import writer
from graph_engine import input_models as models
from graph_engine.materialize import materialize
from tests.support import claims, graphs, rules

DEC5 = datetime(2026, 12, 5, tzinfo=timezone.utc)


def _definition_input(*rule_dicts: dict) -> models.CategoryDefinitionInput:
    return models.CategoryDefinitionInput.model_validate(rules.definition(*rule_dicts))


def _entity_definition(key: str, definition=None, properties=()) -> models.EntityDefinitionInput:
    return models.EntityDefinitionInput(key=key, definition=definition, property_definitions=list(properties))


def _relation(key: str, definition=None) -> models.RelationDefinitionInput:
    return models.RelationDefinitionInput(key=key, source=models.EntityDescriptorInput(keys=["Cell"]), target=models.EntityDescriptorInput(keys=["Cell"]), definition=definition)


def _event(key: str, definition=None) -> models.EventDefinitionInput:
    return models.EventDefinitionInput(key=key, kind=models.EventKind.INTRINSIC, inputs=[], outputs=[], definition=definition)


def _structure_relation(key: str, definition=None) -> models.StructureRelationDefinitionInput:
    return models.StructureRelationDefinitionInput(key=key, source=models.StructureDescriptorInput(identifiers=["ROI"]), target=models.StructureDescriptorInput(identifiers=["ROI"]), definition=definition)


def _measurement(key: str, definition=None) -> models.MeasurementDefinitionInput:
    return models.MeasurementDefinitionInput(key=key, source=models.StructureDescriptorInput(identifiers=["ROI"]), target=models.EntityDescriptorInput(keys=["Cell"]), definition=definition)


def _schema(*, entities=(), relations=(), events=(), structure_relations=(), measurements=()) -> models.GraphDefinitionInput:
    return models.GraphDefinitionInput(
        system_version="1.0.0",
        extensions=models.GraphExtensionsInput(
            entities=list(entities),
            relations=list(relations),
            events=list(events),
            structure_relations=list(structure_relations),
            measurements=list(measurements),
        ),
    )


# --------------------------------------------------------------------------- the zoo: schemas that must build


def good_schemas() -> dict[str, models.GraphDefinitionInput]:
    curator_rule = rules.rule(rules.word("ADJACENT_TO"), rules.by("curator"))
    return {
        "primitive-everything": _schema(
            entities=[_entity_definition("Cell")],
            relations=[_relation("TOUCHES")],
            events=[_event("Mitosis")],
            structure_relations=[_structure_relation("OVERLAPS")],
            measurements=[_measurement("SHOWS")],
        ),
        "entity-two-rules-with-unless": _schema(
            entities=[
                _entity_definition(
                    "AIS",
                    _definition_input(
                        rules.rule(rules.word("AIS"), rules.by("peter"), rules.before(DEC5), unless=[[rules.via("sloppy-import")]]),
                        rules.rule(rules.word("AxonInitialSegment"), rules.by("karl"), rules.since(DEC5)),
                    ),
                )
            ]
        ),
        "entity-kind-split": _schema(
            entities=[
                _entity_definition(
                    "AIS",
                    _definition_input(
                        rules.rule(rules.word("AIS"), rules.by("peter"), rules.not_kind("EVIDENCE")),
                        rules.rule(rules.of_kind("EVIDENCE"), rules.by("curator")),
                    ),
                )
            ]
        ),
        "relation-scoped": _schema(
            entities=[_entity_definition("Cell")],
            relations=[_relation("TOUCHES", _definition_input(rules.rule(rules.word("TOUCHES"), rules.by("karl"), rules.since(DEC5))))],
        ),
        "event-app-scoped": _schema(
            entities=[_entity_definition("Cell")],
            events=[_event("Mitosis", _definition_input(rules.rule(rules.word("Mitosis", "CellDivision"), rules.via("event-annotator"))))],
        ),
        "structure-relation-scoped": _schema(
            structure_relations=[_structure_relation("ADJACENT_TO", _definition_input(curator_rule))],
        ),
        "structure-relation-derives-other-words": _schema(
            structure_relations=[_structure_relation("NEIGHBOURS", _definition_input(rules.rule(rules.word("ADJACENT_TO", "ABUTS"), rules.by("curator"))))],
        ),
        "measurement-scoped": _schema(
            entities=[_entity_definition("Cell")],
            measurements=[_measurement("SHOWS", _definition_input(rules.rule(rules.word("SHOWS"), rules.via("mikro"))))],
        ),
        "measurement-not-in": _schema(
            entities=[_entity_definition("Cell")],
            measurements=[_measurement("SHOWS", _definition_input(rules.rule(rules.word("SHOWS"), rules.not_by("untrusted-bot"))))],
        ),
        "entity-measurement-rules-name-keys": _schema(
            entities=[
                _entity_definition(
                    "Cell",
                    _definition_input(
                        rules.rule(rules.word("Cell"), rules.not_kind("MEASUREMENT")),
                        rules.rule(rules.of_kind("MEASUREMENT"), rules.via("app-a"), rules.key("vector_length")),
                        rules.rule(rules.of_kind("MEASUREMENT"), rules.via("app-b"), rules.key("area", "volume")),
                    ),
                    properties=[
                        models.PropertyDefinitionInput(
                            key="avg_area",
                            type=models.PropertyType.FLOAT,
                            derivation=models.DerivationType.ROLLUP,
                            rule=models.DerivationRuleInput(
                                source_node="ROI",
                                key="area",
                                aggregation=models.AggregationFunction.MEAN,
                                evidence=rules.evidence(rules.rule(rules.via("app-b")), rules.rule(rules.via("app-c"), rules.observed_before(DEC5), unless=[[rules.by("intern")]])),
                            ),
                        )
                    ],
                )
            ]
        ),
        "all-five-defined": _schema(
            entities=[_entity_definition("Cell", _definition_input(rules.rule(rules.word("Cell"), rules.by("peter"))))],
            relations=[_relation("TOUCHES", _definition_input(rules.rule(rules.word("TOUCHES"), rules.by("peter"))))],
            events=[_event("Mitosis", _definition_input(rules.rule(rules.word("Mitosis"), rules.by("peter"))))],
            structure_relations=[_structure_relation("ADJACENT_TO", _definition_input(rules.rule(rules.word("ADJACENT_TO"), rules.by("peter"))))],
            measurements=[_measurement("SHOWS", _definition_input(rules.rule(rules.word("SHOWS"), rules.by("peter"))))],
        ),
    }


@pytest.mark.parametrize("name", sorted(good_schemas()))
def test_schema_builds(name: str) -> None:
    assert good_schemas()[name] is not None


def test_bad_schemas_are_refused() -> None:
    with pytest.raises(ValidationError, match="WORD"):  # wordless rule on a structure relation
        _structure_relation("ADJACENT_TO", _definition_input(rules.rule(rules.by("curator"))))
    # Observation time on a plain measurement rule is fine now (RFC 0015):
    # every claim carries `observed_at`, so the bound is total.
    assert _measurement("SHOWS", _definition_input(rules.rule(rules.word("SHOWS"), rules.observed_since(DEC5)))) is not None
    with pytest.raises(ValidationError, match="KIND"):  # KIND in an unless group, on an event
        _event("Mitosis", models.CategoryDefinitionInput.model_validate(rules.definition(rules.rule(rules.word("Mitosis"), unless=[[rules.of_kind("SAMENESS")]]))))
    with pytest.raises(ValidationError, match="samenessRule"):  # sameness is the view's rule (RFC 0024)
        _entity_definition("AIS", _definition_input(rules.rule(rules.word("AIS"), rules.by("peter"), rules.not_kind("SAMENESS"))))
    with pytest.raises(ValidationError, match="samenessRule"):
        _entity_definition("AIS", _definition_input(rules.rule(rules.of_kind("SAMENESS"), rules.by("curator"))))
    with pytest.raises(ValidationError, match="KEY"):  # a metric key on a classification rule
        _entity_definition("Cell", _definition_input(rules.rule(rules.word("Cell"), rules.key("area"))))
    with pytest.raises(ValidationError):  # the flat evidence list is not an input any more
        models.DerivationRuleInput(source_node="ROI", key="area", evidence=[rules.via("app-b")])
    with pytest.raises(ValidationError):  # empty rule list on a relation
        _relation("TOUCHES", models.CategoryDefinitionInput(rules=[]))


# --------------------------------------------------------------------------- materialization stores every one


@pytest.mark.django_db(transaction=True)
def test_materialize_stores_definitions_on_every_family(transactional_db, table_projector, authenticated_context) -> None:
    request = authenticated_context.request
    graph = materialize(good_schemas()["all-five-defined"], table_projector, user=request._user, organization=request._organization, membership=request.membership, name="all-five")

    for model, key in (
        (core_models.EntityCategory, "Cell"),
        (core_models.RelationCategory, "TOUCHES"),
        (core_models.NaturalEventCategory, "Mitosis"),
        (core_models.StructureRelationCategory, "ADJACENT_TO"),
        (core_models.MeasurementCategory, "SHOWS"),
    ):
        category = model.objects.get(graph=graph, key=key)
        assert category.definition.get("rules"), f"{key}: the definition must be stored"
        assert {row.key for row in core_models.CategoryAssertedTerm.objects.filter(category=category)} == {key}, f"{key}: the vocabulary index follows the rules"


@pytest.mark.django_db(transaction=True)
def test_a_structure_relation_may_derive_from_other_words(transactional_db, table_projector, authenticated_context) -> None:
    request = authenticated_context.request
    graph = materialize(good_schemas()["structure-relation-derives-other-words"], table_projector, user=request._user, organization=request._organization, membership=request.membership, name="sr-derives")
    category = core_models.StructureRelationCategory.objects.get(graph=graph, key="NEIGHBOURS")
    assert {row.key for row in core_models.CategoryAssertedTerm.objects.filter(category=category)} == {"ADJACENT_TO", "ABUTS"}


# --------------------------------------------------------------------------- behavior: the rules govern the claim lists


def _sr_listed(category) -> set:
    from api.queries import _edges

    links = _edges.links_for_category(category.graph.organization, category, evidence_models.Link.Kind.STRUCTURE_RELATION)
    return {link.pk for link in links}


def _measurement_listed(category) -> set:
    from api.queries import _edges

    links = _edges.links_for_category(category.graph.organization, category, evidence_models.Link.Kind.MEASUREMENT)
    return {link.pk for link in links}


@pytest.mark.django_db(transaction=True)
def test_structure_relation_claims_fold_under_the_categorys_rules(transactional_db, table_projector, authenticated_context) -> None:
    request = authenticated_context.request
    graph = materialize(good_schemas()["structure-relation-scoped"], table_projector, user=request._user, organization=request._organization, membership=request.membership, name="sr-scoped")
    org = graph.organization
    category = core_models.StructureRelationCategory.objects.get(graph=graph, key="ADJACENT_TO")

    left = claims.structure(org, "roi-left", "curator")
    right = claims.structure(org, "roi-right", "curator")
    trusted = claims.relate_structures(org, "ADJACENT_TO", left, right, "curator")
    untrusted = claims.relate_structures(org, "ADJACENT_TO", left, right, "bot")

    listed = _sr_listed(category)
    assert trusted.pk in listed, "the curator's claim is the category's rule"
    assert untrusted.pk not in listed, "the bot's is not"

    # Standings fold under the same rules: the bot's retraction changes nothing,
    # the curator's takes the claim out.
    writer.retract(org, trusted, writer.create_assertion(org, subject="bot", app_id="pytest"))
    assert trusted.pk in _sr_listed(category), "an untrusted retraction does not count"
    writer.retract(org, trusted, writer.create_assertion(org, subject="curator", app_id="pytest"))
    assert trusted.pk not in _sr_listed(category), "the trusted one does"


@pytest.mark.django_db(transaction=True)
def test_measurement_claims_fold_under_the_categorys_rules(transactional_db, table_projector, authenticated_context) -> None:
    request = authenticated_context.request
    graph = materialize(good_schemas()["measurement-scoped"], table_projector, user=request._user, organization=request._organization, membership=request.membership, name="m-scoped")
    org = graph.organization
    category = core_models.MeasurementCategory.objects.get(graph=graph, key="SHOWS")

    cell = claims.mint(org, "Cell", "peter")
    roi = claims.structure(org, "roi-m", "peter")
    trusted = claims.measure_between(org, "SHOWS", roi, cell, "peter", app_id="mikro")
    untrusted = claims.measure_between(org, "SHOWS", roi, cell, "peter", app_id="freehand")

    listed = _measurement_listed(category)
    assert trusted.pk in listed, "the claim through the trusted app is listed"
    assert untrusted.pk not in listed, "one through any other app is not"


@pytest.mark.django_db(transaction=True)
def test_a_primitive_category_still_lists_everything(transactional_db, table_projector, authenticated_context) -> None:
    request = authenticated_context.request
    graph = materialize(good_schemas()["primitive-everything"], table_projector, user=request._user, organization=request._organization, membership=request.membership, name="primitive-zoo")
    org = graph.organization
    category = core_models.StructureRelationCategory.objects.get(graph=graph, key="OVERLAPS")

    left = claims.structure(org, "roi-a", "anyone")
    right = claims.structure(org, "roi-b", "anyone")
    link = claims.relate_structures(org, "OVERLAPS", left, right, "whoever")
    assert link.pk in _sr_listed(category), "no rules means everything counts, as always"


# --------------------------------------------------------------------------- the mutation surfaces


UPDATE_SR = """
    mutation U($input: UpdateStructureRelationCategoryInput!) {
        updateStructureRelationCategory(input: $input) { id definition { rules { when { field operator value } } } }
    }
"""

CREATE_PROTOCOL_EVENT = """
    mutation C($input: CreateProtocolEventCategoryInput!) {
        createProtocolEventCategory(input: $input) { id definition { rules { when { field operator value } } } }
    }
"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_update_structure_relation_category_writes_the_rule(api_schema, simple_api_context, table_projector, authenticated_context) -> None:
    from asgiref.sync import sync_to_async

    request = authenticated_context.request

    @sync_to_async
    def build():
        graph = materialize(good_schemas()["primitive-everything"], table_projector, user=request._user, organization=request._organization, membership=request.membership, name="sr-update")
        return str(core_models.StructureRelationCategory.objects.get(graph=graph, key="OVERLAPS").pk)

    category_id = await build()
    updated = await api_schema.execute(
        UPDATE_SR,
        variable_values={"input": {"id": category_id, "definition": rules.definition(rules.rule(rules.word("OVERLAPS"), rules.by("curator")))}},
        context_value=simple_api_context,
    )
    assert updated.errors is None, f"GraphQL errors: {updated.errors}"
    read_back = updated.data["updateStructureRelationCategory"]["definition"]["rules"][0]["when"]
    assert {"field": "SUBJECT", "operator": "IS", "value": "curator"} in read_back

    both = await api_schema.execute(
        UPDATE_SR,
        variable_values={"input": {"id": category_id, "definition": rules.definition(rules.rule(rules.word("OVERLAPS"))), "clearDefinition": True}},
        context_value=simple_api_context,
    )
    assert both.errors is not None, "a new definition and clearDefinition together are refused"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_protocol_event_categorys_rules_govern_its_participations(api_schema, simple_api_context, table_projector, authenticated_context) -> None:
    from asgiref.sync import sync_to_async

    from tests.support import drawing

    request = authenticated_context.request

    @sync_to_async
    def build():
        graph = materialize(good_schemas()["primitive-everything"], table_projector, user=request._user, organization=request._organization, membership=request.membership, name="protocol-rules")
        return str(graph.pk)

    graph_id = await build()
    made = await api_schema.execute(
        CREATE_PROTOCOL_EVENT,
        variable_values={
            "input": {
                "graph": graph_id,
                "key": "Staining",
                "protocol": "staining-v1",
                "kind": "EXTRINSIC",
                "inputs": [{"key": "Cell", "role": "subject", "descriptor": {"keys": ["Cell"]}}],
                "outputs": [],
                "definition": rules.definition(rules.rule(rules.word("Staining"), rules.via("protocol-runner"))),
            }
        },
        context_value=simple_api_context,
    )
    assert made.errors is None, f"GraphQL errors: {made.errors}"
    read_back = made.data["createProtocolEventCategory"]["definition"]["rules"][0]["when"]
    assert {"field": "APP", "operator": "IS", "value": "protocol-runner"} in read_back

    @sync_to_async
    def story():
        graph = core_models.Graph.objects.get(pk=graph_id)
        org = graph.organization
        cell = claims.mint(org, "Cell", "peter")
        other = claims.mint(org, "Cell", "peter")
        event = claims.mint(org, "Staining", "anyone", app_id="protocol-runner", kind="PROTOCOL_EVENT")
        claims.participate(org, "Staining", cell, event, "anyone", app_id="protocol-runner", role="subject", term_kind="PROTOCOL_EVENT")
        claims.participate(org, "Staining", other, event, "anyone", app_id="freehand", role="subject", term_kind="PROTOCOL_EVENT")
        graphs.rebuild(graph, table_projector)
        return drawing.edges_between(graph, cell, event), drawing.edges_between(graph, other, event)

    trusted, untrusted = await story()
    assert trusted == 1, "a participation claimed through the trusted app draws"
    assert untrusted == 0, "one through any other app does not"
