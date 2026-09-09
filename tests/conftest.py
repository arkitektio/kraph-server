"""The one conftest.

Two tenants appear in this suite and they are not the same organization:

- `api_context` authenticates as the static token's identity — user
  `static_issuer_1`, organization `static_org` (`tests.support.identity`). Every
  graph fixture below is owned by it, and every GraphQL write lands in it.
- `organization` (slug `evidence-org`) and `other_organization` are tenants for
  tests that write evidence rows directly through `evidence.writer`.

A test that mixes the two writes evidence the API caller cannot see. Pick one.
"""

import os
import time
from datetime import datetime, timezone

import boto3
import pytest
from authentikate.models import Client, Membership, Organization, User
from dokker import local
from kante.context import HttpContext, UniversalRequest
from moto import mock_aws
from strawberry.http.temporal_response import TemporalResponse

from core import models as core_models
from core.enums import ValueKind
from evidence import models as evidence_models
from graph_engine import input_models as models
from graph_engine.controller import GraphController
from graph_engine.materialize import materialize
from graph_engine.projection import TableProjector
from tests.support import rules
from tests.support.identity import static_identity


@pytest.fixture(scope="function")
def aws_credentials(monkeypatch) -> None:
    """Mocked AWS credentials for moto, restored after the test."""
    for key, value in (("AWS_ACCESS_KEY_ID", "testing"), ("AWS_SECRET_ACCESS_KEY", "testing"), ("AWS_SECURITY_TOKEN", "testing"), ("AWS_SESSION_TOKEN", "testing"), ("AWS_DEFAULT_REGION", "us-east-1")):
        monkeypatch.setenv(key, value)


@pytest.fixture(scope="function")
def s3(aws_credentials):
    with mock_aws():
        yield boto3.client("s3", region_name="us-east-1")


@pytest.fixture
def create_bucket1(s3) -> None:
    s3.create_bucket(Bucket="babanana")


@pytest.fixture
def create_bucket2(s3) -> None:
    s3.create_bucket(Bucket="cabanana")


@pytest.fixture(scope="session")
def backend_stack():
    docker_compose_path = os.path.join(os.path.dirname(__file__), "integration", "docker-compose.yaml")

    with local(docker_compose_path) as e:
        e.inspect()

        e.down()

        e.up()

        time.sleep(2)

        yield


@pytest.fixture(scope="function")
def api_context(db, backend_stack) -> HttpContext:
    """The request context every GraphQL test executes under: the static token's identity."""
    user, org, membership = static_identity()
    client, _ = Client.objects.get_or_create(client_id="oinsoins")

    request = UniversalRequest(
        _extensions={"token": "test"},
        _client=client,  # type: ignore
        _user=user,  # type: ignore
        _organization=org,  # type: ignore
    )
    request.set_membership(membership)  # type: ignore

    return HttpContext(request=request, response=TemporalResponse(), headers={"Authorization": "Bearer test"}, type="http")


@pytest.fixture(scope="function")
def authenticated_context(api_context) -> HttpContext:
    """`api_context` under its old name. One release, then gone."""
    return api_context


@pytest.fixture(scope="function")
def simple_api_context(api_context) -> HttpContext:
    """`api_context` under its old name. One release, then gone."""
    return api_context


@pytest.fixture(scope="session")
def bio_graph_schema() -> models.GraphDefinitionInput:
    """
    Fixture defined using EXPLICIT Pydantic Model constructors.
    Uses list-based definitions with key attributes.

    Note: Structures (ROI, ToldYouSo) are no longer defined in the schema.
    They are dynamically resolved from the structure identifier at write time.

    Every rollup rule here names an explicit metric key and a *structure* source.
    Both are now enforced: `materialize.validate_derivation_rules` rejects a rule with
    no key, and rejects one whose source is an entity or event kind. Before that, such
    rules rendered as `WHERE m.key = null`, which never matches — so the property
    silently stayed unset and any test asserting on it passed vacuously.
    """
    return models.GraphDefinitionInput(
        system_version="1.0.1",
        extensions=models.GraphExtensionsInput(
            # --- 1. ENTITIES ---
            entities=[
                models.EntityDefinitionInput(
                    key="AIS",
                    property_definitions=[
                        models.PropertyDefinitionInput(key="avg_length", type=models.PropertyType.FLOAT, derivation=models.DerivationType.ROLLUP, rule=models.DerivationRuleInput(source_node="ROI", key="vector_length", aggregation=models.AggregationFunction.MEAN)),
                        models.PropertyDefinitionInput(key="name", type=models.PropertyType.STRING, derivation=models.DerivationType.ROLLUP, rule=models.DerivationRuleInput(source_node="ToldYouSo", key="name", aggregation=models.AggregationFunction.LATEST)),
                    ],
                ),
                models.EntityDefinitionInput(key="Soma", property_definitions=[models.PropertyDefinitionInput(key="centroid", type=models.PropertyType.POINT_3D, derivation=models.DerivationType.LATEST, rule=models.DerivationRuleInput(source_node="ROI", key="centroid"))]),
                models.EntityDefinitionInput(
                    key="Cell",
                    property_definitions=[
                        models.PropertyDefinitionInput(key="id", type=models.PropertyType.STRING),
                        # These originally counted/summarised evidence reached through
                        # another node kind (a Mitosis event, an AIS entity). The state
                        # vector's grain is (entity, source_category, key) over metrics
                        # reached via (Metric)-[DESCRIBES]->(Structure)-[INFORMS]->(Entity),
                        # so cross-entity rollups are not expressible — and are now
                        # rejected at materialization rather than silently never computing.
                        # Modelled here as metric keys on the supporting structure.
                        models.PropertyDefinitionInput(key="mitosis_count", type=models.PropertyType.INTEGER, derivation=models.DerivationType.ROLLUP, rule=models.DerivationRuleInput(key="mitosis_event", source_node="ROI", aggregation=models.AggregationFunction.COUNT)),
                        models.PropertyDefinitionInput(key="ais_length_summary", type=models.PropertyType.FLOAT, derivation=models.DerivationType.ROLLUP, rule=models.DerivationRuleInput(key="vector_length", source_node="ROI", aggregation=models.AggregationFunction.LATEST)),
                    ],
                ),
            ],
            # --- 3. RELATIONS ---
            relations=[
                models.RelationDefinitionInput(
                    key="IS_CONNECTED_TO",
                    source=models.EntityDescriptorInput(keys=["Cell"]),
                    target=models.EntityDescriptorInput(keys=["Cell"]),
                    cardinality=models.Cardinality.ONE_TO_ONE,
                    # No `properties`. This used to declare `distance` as a
                    # EUCLIDEAN_RANGE rollup, and `project_edges` has never run a
                    # derivation rule — it writes `category_id` and
                    # `__assertion_count` and stops. So the fixture the whole
                    # suite runs against contained a rule nothing executed, and
                    # nothing failed. `validate_derivation_rules` now refuses it.
                ),
                models.RelationDefinitionInput(key="PART_OF", source=models.EntityDescriptorInput(keys=["AIS", "Soma"]), target=models.EntityDescriptorInput(keys=["Cell"])),
            ],
            # --- 4. EVENTS ---
            events=[
                models.EventDefinitionInput(
                    key="Mitosis",
                    kind=models.EventKind.INTRINSIC,
                    inputs=[models.EventRoleInput(key="Cell", role="a", descriptor=models.EntityDescriptorInput(keys=["Cell"]))],
                    outputs=[models.EventRoleInput(key="Cell", role="a", descriptor=models.EntityDescriptorInput(keys=["Cell"])), models.EventRoleInput(key="Cell", role="b", descriptor=models.EntityDescriptorInput(keys=["Cell"]))],
                    properties=[models.PropertyDefinitionInput(key="cell_count", type=models.PropertyType.INTEGER, derivation=models.DerivationType.ROLLUP, rule=models.DerivationRuleInput(source_node="ROI", key="cell_marker", aggregation=models.AggregationFunction.COUNT))],
                )
            ],
        ),
    )


@pytest.fixture(scope="function")
def test_graph(transactional_db, table_projector, bio_graph_schema, authenticated_context) -> core_models.Graph:
    """
    Create a test graph with the bio_graph schema.

    This is the standard test graph fixture that materializes a graph
    from the bio_graph_schema definition, creating all necessary
    Django models (EntityCategory, RelationCategory, etc.).
    """
    request = authenticated_context.request
    return materialize(
        bio_graph_schema,
        table_projector,
        user=request._user,
        organization=request._organization,
        membership=request.membership,
        name="test_graph",
    )


@pytest.fixture(scope="function")
def graph_controller(transactional_db, table_projector, test_graph) -> GraphController:
    """A ready-to-use GraphController drawing through the table projector."""
    return GraphController(
        projector=table_projector,
        subject="test_user",
        app_id="test_app",
    )


@pytest.fixture(scope="function")
def bio_graph(transactional_db, table_projector, bio_graph_schema, authenticated_context) -> core_models.Graph:
    """
    Create a biological graph with the provided schema.
    Uses transactional_db to maintain database state across the fixture.
    The graph is created once and reused.
    """
    request = authenticated_context.request
    return materialize(
        bio_graph_schema,
        table_projector,
        user=request._user,
        organization=request._organization,
        membership=request.membership,
        name="bio_graph",
    )


@pytest.fixture(scope="function")
def minimal_schema() -> models.GraphDefinitionInput:
    """A minimal schema for testing.

    Uses the canonical `*Input` names and `property_definitions`. The previous version
    passed `properties=`, which is not a field on EntityDefinitionInput, so the entity
    materialized with zero properties and any assertion about them passed vacuously.

    Both properties carry a rule. They did not, which made them inert — nothing
    writes a property directly — so `materialize` now rejects that shape and this
    fixture would fail to build the graph it exists to provide.
    """
    return models.GraphDefinitionInput(
        system_version="1.0.0",
        extensions=models.GraphExtensionsInput(
            entities=[
                models.EntityDefinitionInput(
                    key="Person",
                    description="A person",
                    property_definitions=[
                        models.PropertyDefinitionInput(
                            key="name",
                            type=models.PropertyType.STRING,
                            derivation=models.DerivationType.LATEST,
                            rule=models.DerivationRuleInput(source_node="ROI", key="name"),
                        ),
                        models.PropertyDefinitionInput(
                            key="age",
                            type=models.PropertyType.INTEGER,
                            derivation=models.DerivationType.ROLLUP,
                            rule=models.DerivationRuleInput(source_node="ROI", key="age", aggregation=models.AggregationFunction.LATEST),
                        ),
                    ],
                )
            ]
        ),
    )


@pytest.fixture(scope="function")
def table_projector(transactional_db, backend_stack) -> TableProjector:
    """The projection kind the suite draws through.

    Stateless: the drawing lives in the projection tables of the same test
    database, so `transactional_db` flushes it between tests — real isolation,
    where the Apache AGE namespace this replaced had to be dropped by hand and
    (before that) was deliberately leaked around a type-cache bug.
    """
    return TableProjector()


@pytest.fixture(scope="function")
def api_schema(table_projector):
    """The served schema — the one `api/schema.py` builds, drawing through the table projector.

    Not rebuilt per test: `create_schema` binds only a `ProjectionExtension` over
    a stateless projector, and the module-level schema is built with exactly these
    arguments. Still function-scoped over `table_projector` so a test that asks
    for the schema alone keeps the transactional database it always had.
    """
    from api.schema import schema

    return schema


# ---------------------------------------------------------------------------
# More graph schemas. Each is a different *shape* of view — minimal, open
# descriptors, protocol lane, and a consensus pair that shares a word — so the
# namespace machinery (RFC 0006) is exercised against more than one schema.
# ---------------------------------------------------------------------------


@pytest.fixture
def minimal_graph_schema() -> models.GraphDefinitionInput:
    """The smallest possible view: one entity word, no edges of any kind."""
    return models.GraphDefinitionInput(
        system_version="1.0.0",
        extensions=models.GraphExtensionsInput(
            entities=[models.EntityDefinitionInput(key="Specimen", property_definitions=[])],
        ),
    )


@pytest.fixture(scope="function")
def minimal_graph(transactional_db, table_projector, minimal_graph_schema, authenticated_context) -> core_models.Graph:
    request = authenticated_context.request
    return materialize(minimal_graph_schema, table_projector, user=request._user, organization=request._organization, membership=request.membership, name="minimal")


@pytest.fixture
def interactome_graph_schema() -> models.GraphDefinitionInput:
    """Open and closed descriptors side by side.

    `interacts_with` declares no source or target filter at all — the open
    descriptor, which the namespace expands over every entity-like category —
    while `binds` is closed to Protein -> Site.
    """
    return models.GraphDefinitionInput(
        system_version="1.0.0",
        extensions=models.GraphExtensionsInput(
            entities=[
                models.EntityDefinitionInput(key="Protein", property_definitions=[]),
                models.EntityDefinitionInput(key="Complex", property_definitions=[]),
                models.EntityDefinitionInput(key="Site", property_definitions=[]),
            ],
            relations=[
                models.RelationDefinitionInput(key="interacts_with", source=models.EntityDescriptorInput(), target=models.EntityDescriptorInput()),
                models.RelationDefinitionInput(key="binds", source=models.EntityDescriptorInput(keys=["Protein"]), target=models.EntityDescriptorInput(keys=["Site"])),
            ],
        ),
    )


@pytest.fixture(scope="function")
def interactome_graph(transactional_db, table_projector, interactome_graph_schema, authenticated_context) -> core_models.Graph:
    request = authenticated_context.request
    return materialize(interactome_graph_schema, table_projector, user=request._user, organization=request._organization, membership=request.membership, name="interactome")


@pytest.fixture
def lab_graph_schema() -> models.GraphDefinitionInput:
    """The protocol lane's entity words. Protocol event and reagent categories
    cannot be declared in a schema (`GraphExtensionsInput` has no field for
    them), so the `lab_graph` fixture adds those through the ORM — which is
    also what exercises the category-write signal for both kinds."""
    return models.GraphDefinitionInput(
        system_version="1.0.0",
        extensions=models.GraphExtensionsInput(
            entities=[
                models.EntityDefinitionInput(key="Sample", property_definitions=[]),
                models.EntityDefinitionInput(key="Slide", property_definitions=[]),
            ],
        ),
    )


@pytest.fixture(scope="function")
def lab_graph(transactional_db, table_projector, lab_graph_schema, authenticated_context) -> core_models.Graph:
    request = authenticated_context.request
    graph = materialize(lab_graph_schema, table_projector, user=request._user, organization=request._organization, membership=request.membership, name="lab")
    core_models.ProtocolEventCategory.objects.create(
        graph=graph,
        key="Fixation",
        age_name="Fixation",
        label="Fixation",
        source_entity_roles=[{"key": "Sample", "role": "specimen", "descriptor": {"keys": ["Sample"]}}],
        target_entity_roles=[{"key": "Slide", "role": "mounted", "descriptor": {"keys": ["Slide"]}}],
    )
    return graph


@pytest.fixture
def cytology_graph_schema() -> models.GraphDefinitionInput:
    """One half of the consensus pair: declares the shared word `Cell`.

    Both halves derive a `size` property from the **same** metric claims
    (`ROI.size`), under different rules — MEAN here, MAX in oncology — so the
    same evidence reads as different knowledge per view.
    """
    return models.GraphDefinitionInput(
        system_version="1.0.0",
        extensions=models.GraphExtensionsInput(
            entities=[
                models.EntityDefinitionInput(
                    key="Cell",
                    property_definitions=[
                        models.PropertyDefinitionInput(key="size", type=models.PropertyType.FLOAT, derivation=models.DerivationType.ROLLUP, rule=models.DerivationRuleInput(source_node="ROI", key="size", aggregation=models.AggregationFunction.MEAN)),
                    ],
                ),
                models.EntityDefinitionInput(key="Nucleus", property_definitions=[]),
            ],
            relations=[
                models.RelationDefinitionInput(key="has_nucleus", source=models.EntityDescriptorInput(keys=["Cell"]), target=models.EntityDescriptorInput(keys=["Nucleus"])),
            ],
        ),
    )


@pytest.fixture
def oncology_graph_schema() -> models.GraphDefinitionInput:
    """The other half: also declares `Cell`, plus words of its own — and reads
    the same `ROI.size` metrics as MAX where cytology reads MEAN."""
    return models.GraphDefinitionInput(
        system_version="1.0.0",
        extensions=models.GraphExtensionsInput(
            entities=[
                models.EntityDefinitionInput(
                    key="Cell",
                    property_definitions=[
                        models.PropertyDefinitionInput(key="size", type=models.PropertyType.FLOAT, derivation=models.DerivationType.ROLLUP, rule=models.DerivationRuleInput(source_node="ROI", key="size", aggregation=models.AggregationFunction.MAX)),
                    ],
                ),
                models.EntityDefinitionInput(key="Tumor", property_definitions=[]),
            ],
            relations=[
                models.RelationDefinitionInput(key="part_of", source=models.EntityDescriptorInput(keys=["Cell"]), target=models.EntityDescriptorInput(keys=["Tumor"])),
            ],
        ),
    )


@pytest.fixture(scope="function")
def cytology_graph(transactional_db, table_projector, cytology_graph_schema, authenticated_context) -> core_models.Graph:
    request = authenticated_context.request
    return materialize(cytology_graph_schema, table_projector, user=request._user, organization=request._organization, membership=request.membership, name="cytology")


@pytest.fixture(scope="function")
def oncology_graph(transactional_db, table_projector, oncology_graph_schema, authenticated_context) -> core_models.Graph:
    request = authenticated_context.request
    return materialize(oncology_graph_schema, table_projector, user=request._user, organization=request._organization, membership=request.membership, name="oncology")


@pytest.fixture(scope="function")
def census_graph(transactional_db, table_projector, authenticated_context) -> core_models.Graph:
    """A view that declares no word of its own — its one category **derives**
    from the word `Cell` (a rule whose WORD condition names it, RFC 0010),
    so it reads other views' claims under its own name. Declared in the schema
    itself (RFC 0007): a graph's meaning is part of its definition document."""
    request = authenticated_context.request
    return materialize(
        models.GraphDefinitionInput(
            system_version="1.0.0",
            extensions=models.GraphExtensionsInput(
                entities=[
                    models.EntityDefinitionInput(
                        key="ObservedCell",
                        label="Observed cell",
                        definition=models.CategoryDefinitionInput.model_validate(rules.definition(rules.rule(rules.word("Cell")))),
                    ),
                ],
            ),
        ),
        table_projector,
        user=request._user,
        organization=request._organization,
        membership=request.membership,
        name="census",
    )


@pytest.fixture(scope="function")
def literal_graph(transactional_db, table_projector, authenticated_context) -> core_models.Graph:
    """Declares `Cell` and `StemCell` primitively — membership is whatever was
    asserted, under each word's own label. The contrast for `subsumption_graph`."""
    request = authenticated_context.request
    return materialize(
        models.GraphDefinitionInput(
            system_version="1.0.0",
            extensions=models.GraphExtensionsInput(
                entities=[
                    models.EntityDefinitionInput(key="Cell", property_definitions=[]),
                    models.EntityDefinitionInput(key="StemCell", property_definitions=[]),
                ],
            ),
        ),
        table_projector,
        user=request._user,
        organization=request._organization,
        membership=request.membership,
        name="literal",
    )


@pytest.fixture(scope="function")
def subsumption_graph(transactional_db, table_projector, authenticated_context) -> core_models.Graph:
    """One category, a union of clauses: "'Cell' means what Peter called Cell,
    and what Karl called StemCell after Dec 5" (RFC 0007). Declares no word of
    its own — both words arrive through the definition, which the **schema
    itself** carries: a graph's meaning is part of its definition document."""
    from datetime import datetime, timezone

    request = authenticated_context.request
    return materialize(
        models.GraphDefinitionInput(
            system_version="1.0.0",
            extensions=models.GraphExtensionsInput(
                entities=[
                    models.EntityDefinitionInput(
                        key="Cell",
                        definition=models.CategoryDefinitionInput.model_validate(
                            rules.definition(
                                rules.rule(rules.word("Cell"), rules.by("peter")),
                                rules.rule(rules.word("StemCell"), rules.by("karl"), rules.since(datetime(2026, 12, 5, tzinfo=timezone.utc))),
                            )
                        ),
                    ),
                ],
            ),
        ),
        table_projector,
        user=request._user,
        organization=request._organization,
        membership=request.membership,
        name="subsumption",
    )


# ---------------------------------------------------------------------------
# Evidence-layer fixtures: tenants and vocabulary for tests that write rows
# through `evidence.writer` rather than through the API. `organization` is
# **not** the API caller's organization — see the module docstring.
# ---------------------------------------------------------------------------


@pytest.fixture
def organization(db: None, backend_stack: None) -> Organization:
    """The tenant most evidence-level tests write under (slug `evidence-org`)."""
    org, _ = Organization.objects.get_or_create(slug="evidence-org")
    return org


@pytest.fixture
def other_organization(db: None, backend_stack: None) -> Organization:
    """An organization the static test token is **not** a member of. Nothing it owns may be visible to any other tenant."""
    org, _ = Organization.objects.get_or_create(slug="a_tenant_you_are_not_in")
    return org


@pytest.fixture
def user(db: None, backend_stack: None) -> User:
    """A user to own the graphs categories still hang off."""
    user, _ = User.objects.get_or_create(username="evidence-user", sub="evidence-sub")
    return user


def _make_graph(name: str, organization: Organization, user: User) -> core_models.Graph:
    """A bare `Graph` row: categories hang off one, and no projection is built from it here."""
    membership, _ = Membership.objects.get_or_create(user=user, organization=organization)
    return core_models.Graph.objects.create(name=name, user=user, membership=membership, organization=organization)


@pytest.fixture
def graph_a(organization: Organization, user: User) -> core_models.Graph:
    """One view over the organization's evidence."""
    return _make_graph("graph_a", organization, user)


@pytest.fixture
def graph_b(organization: Organization, user: User) -> core_models.Graph:
    """A second view over the *same* organization's evidence."""
    return _make_graph("graph_b", organization, user)


def _category(graph: core_models.Graph, key: str) -> core_models.EntityCategory:
    """A view's category for a word, minting the organization's term for it."""
    from evidence import writer

    return core_models.EntityCategory.objects.create(graph=graph, term=writer.ensure_term(graph.organization, core_models.EntityCategory.KIND, key), key=key, age_name=key, label=key)


@pytest.fixture
def entity_category_a(graph_a: core_models.Graph) -> core_models.EntityCategory:
    """A word graph A declares, so nodes claimed under it belong to graph A."""
    return _category(graph_a, "AIS")


@pytest.fixture
def entity_category_b(graph_b: core_models.Graph) -> core_models.EntityCategory:
    """A **different** word, declared by graph B alone — two graphs declaring one word share it."""
    return _category(graph_b, "Soma")


@pytest.fixture
def make_node(organization: Organization, assertion: evidence_models.Assertion):
    """Mint a real instance under a category's word and hand back its ref."""

    def _make(category: core_models.Category) -> str:
        node = evidence_models.Instance.objects.create_for_organization(organization=organization, kind=evidence_models.Instance.Kind.ENTITY, term=category.term, assertion=assertion)
        return node.ref

    return _make


@pytest.fixture
def roi_kind(organization: Organization) -> evidence_models.StructureKind:
    """The ROI kind. One per organization — there is no per-graph variant to have."""
    return evidence_models.StructureKind.all_objects.create(organization=organization, identifier="@mikro/roi")


@pytest.fixture
def roi_category_a(roi_kind: evidence_models.StructureKind) -> evidence_models.StructureKind:
    """The ROI kind as reached from graph A — the same row as from graph B."""
    return roi_kind


@pytest.fixture
def roi_category_b(roi_kind: evidence_models.StructureKind) -> evidence_models.StructureKind:
    """The same kind, reached from graph B. Deliberately identical to `roi_category_a`."""
    return roi_kind


@pytest.fixture
def length_category(organization: Organization, roi_kind: evidence_models.StructureKind) -> evidence_models.MetricKind:
    """A float-valued measurement kind describing an ROI."""
    return evidence_models.MetricKind.all_objects.create(organization=organization, structure_kind=roi_kind, key="vector_length", value_kind=ValueKind.FLOAT.value)


@pytest.fixture
def assertion(organization: Organization) -> evidence_models.Assertion:
    """An act every other fixture can hang evidence off."""
    return evidence_models.Assertion.objects.create_for_organization(organization=organization, subject="tester", app_id="pytest", action_name="record_evidence", asserted_at=datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc))


@pytest.fixture
def second_graph(test_graph: core_models.Graph, bio_graph_schema, table_projector, api_context) -> core_models.Graph:
    """A second full view over the same organization's evidence, from the same schema as `test_graph`."""
    request = api_context.request
    return materialize(bio_graph_schema, table_projector, user=request._user, organization=request._organization, membership=request.membership, name="second_graph")
