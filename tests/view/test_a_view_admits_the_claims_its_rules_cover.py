"""What a category *means* can be a property of the graph, not of the entity.

Classification used to be the `Node.category` foreign key: written once at
creation, never updated anywhere, one answer per node forever. So two annotators
could not disagree about what something is — the second one had to create a
second entity, and every metric and relation keyed on the first node stopped
describing it.

Classification is a claim now (`Link.Kind.CLASSIFIES`), which gives a category
something to be *defined over*. A category with an empty `definition` stays
**primitive**: membership is whatever was asserted, the old behaviour, and the
default. A category carrying a definition is **defined** — necessary and
sufficient conditions, evaluated at projection time.

The claim these tests exist to prove is the identity analogue of one the codebase
already makes for values: swapping MEAN for MAX costs zero writes because `State`
holds statistics rather than an answer. Swapping a category's definition must cost
zero writes for the same reason.
"""

import kante
import pytest
from tests.support import claims, drawing, graphs, namespaces, rules, writes
from asgiref.sync import sync_to_async
from kante.context import HttpContext
from core import models as core_models
from evidence import models as evidence_models
from evidence import selector as selector_module
from evidence import writer
from datetime import datetime, timezone
from graph_engine import input_models
from graph_engine.materialize import materialize
from core import asserted_terms
from graph_engine import projector
import uuid
from tests.support.graphs import AFTER, BEFORE, example_graph as _example_graph, rebuild as _rebuild


JOHANNES = "johannes"
CHRISTIAN = "christian"


_claim = claims.classify
_retract_classifications = claims.retract_classifications


def _labels(table_projector, graph: core_models.Graph, keys: list[str]) -> dict[str, int]:
    """How many vertices carry each category's label, keyed by category key.

    Resolves `age_name` from the row rather than assuming the key lowercases to
    it — the mapping is `Category.key_to_age_name` and differs by kind.
    """
    counts = {}
    for key in keys:
        category = core_models.Category.objects.filter(graph=graph, key=key).first()
        assert category is not None, f"no category {key!r} in this graph"
        counts[key] = drawing.vertex_count(graph, category.age_name)
    return counts


def _ids_with_label(table_projector, graph: core_models.Graph, key: str) -> list[str]:
    """The `id` property of every vertex carrying this category's label."""
    category = core_models.Category.objects.get(graph=graph, key=key)
    return drawing.refs_with_label(graph, category.age_name)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_two_annotators_can_disagree_without_forking_the_entity(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
) -> None:
    """The prerequisite for everything else in this file.

    Before classification was a claim, the only way to say "actually it's a Soma"
    was `updateEntity`, which archives the node and creates a new one — a second
    opinion produced a second entity.
    """

    entity_id = await writes.create_entity(api_schema, simple_api_context, "AIS")

    @sync_to_async
    def disagree() -> tuple[int, int]:
        node = evidence_models.Instance.objects.for_organization(test_graph.organization).filter(term__in=selector_module.term_ids_for(test_graph)).get()
        soma = core_models.EntityCategory.objects.get(graph=test_graph, key="Soma")
        _claim(test_graph, node.ref, soma, CHRISTIAN)

        claims = evidence_models.Link.objects.for_organization(test_graph.organization).filter(kind=evidence_models.Link.Kind.CLASSIFIES, source_ref=node.ref)
        nodes = evidence_models.Instance.objects.for_organization(test_graph.organization).filter(pk=node.ref)
        return claims.count(), nodes.count()

    claim_count, node_count = await disagree()

    assert claim_count == 2, "Both classifications must stand — the creating one and the correction"
    assert node_count == 1, "And they must be about one entity, not two"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_definition_narrows_what_the_graph_contains(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """ "In this graph, AIS means the ones Johannes called AIS."

    The node Christian called AIS is admitted by no category here, so it is not in
    the view — and the count is reported rather than the graph quietly shrinking.
    """

    await writes.create_entity(api_schema, simple_api_context, "AIS")
    await writes.create_entity(api_schema, simple_api_context, "AIS")

    @sync_to_async
    def define_and_rebuild() -> dict:
        ais = core_models.EntityCategory.objects.get(graph=test_graph, key="AIS")
        nodes = list(evidence_models.Instance.objects.for_organization(test_graph.organization).filter(term__in=selector_module.term_ids_for(test_graph)))
        assert len(nodes) == 2

        # Each node gets one annotator's claim, and the creating claim is retracted
        # so the two nodes differ only in who says they are an AIS.
        for node, subject in zip(nodes, (JOHANNES, CHRISTIAN)):
            _retract_classifications(test_graph, node.ref)
            _claim(test_graph, node.ref, ais, subject)

        ais.definition = rules.definition(rules.rule(rules.word("AIS"), rules.by(JOHANNES)))
        ais.save()

        return graphs.rebuild(test_graph, table_projector)

    result = await define_and_rebuild()

    assert result["nodes"] == 1, "Only Johannes's AIS is admitted"
    assert result["unclassified"] == 1, "And the one that is not must be reported, not silently dropped"

    @sync_to_async
    def counts() -> dict[str, int]:
        return _labels(table_projector, test_graph, ["AIS"])

    assert (await counts())["AIS"] == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_changing_a_definition_moves_membership_and_writes_no_evidence(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """The whole claim.

    A category's meaning is a read-side reinterpretation, exactly as an
    aggregation is. Changing it must move which nodes are in the graph without
    touching a single row of evidence — otherwise "the graph is a view" is not
    true of identity, only of values.
    """

    await writes.create_entity(api_schema, simple_api_context, "AIS")
    await writes.create_entity(api_schema, simple_api_context, "AIS")

    @sync_to_async
    def setup() -> int:
        ais = core_models.EntityCategory.objects.get(graph=test_graph, key="AIS")
        nodes = list(evidence_models.Instance.objects.for_organization(test_graph.organization).filter(term__in=selector_module.term_ids_for(test_graph)))
        for node, subject in zip(nodes, (JOHANNES, CHRISTIAN)):
            _retract_classifications(test_graph, node.ref)
            _claim(test_graph, node.ref, ais, subject)

        ais.definition = rules.definition(rules.rule(rules.word("AIS"), rules.by(JOHANNES)))
        ais.save()
        graphs.rebuild(test_graph, table_projector)
        return _evidence_row_count(test_graph)

    before = await setup()

    @sync_to_async
    def which_node_is_in() -> str:
        ids = _ids_with_label(table_projector, test_graph, "AIS")
        assert len(ids) == 1, f"expected exactly one projected AIS, got {ids}"
        return ids[0]

    johannes_node = await which_node_is_in()

    @sync_to_async
    def redefine() -> tuple[str, int]:
        ais = core_models.EntityCategory.objects.get(graph=test_graph, key="AIS")
        ais.definition = rules.definition(rules.rule(rules.word("AIS"), rules.by(CHRISTIAN)))
        ais.save()
        graphs.rebuild(test_graph, table_projector)
        ids = _ids_with_label(table_projector, test_graph, "AIS")
        assert len(ids) == 1, f"expected exactly one projected AIS, got {ids}"
        return ids[0], _evidence_row_count(test_graph)

    christian_node, after = await redefine()

    assert christian_node != johannes_node, "Redefining the term must change which node the graph contains"
    assert after == before, "And must cost zero writes to the evidence base — the definition is a read, not a migration"


def _evidence_row_count(graph: core_models.Graph) -> int:
    """Every evidence row this organization holds, as one number."""
    organization = graph.organization
    return sum(
        model.objects.for_organization(organization).count()
        for model in (
            evidence_models.Assertion,
            evidence_models.Structure,
            evidence_models.Metric,
            evidence_models.Link,
            evidence_models.Instance,
            evidence_models.Standing,
        )
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_definitions_can_partition_one_term_by_annotator(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """ "Split AIS into AISprox if Johannes called it and AISdistal if Christian did."

    Two definitions over the same claims. Neither node was ever reclassified and
    no evidence says "AISprox" — the split exists only in this graph's terms.
    """

    await writes.create_entity(api_schema, simple_api_context, "AIS")
    await writes.create_entity(api_schema, simple_api_context, "AIS")

    @sync_to_async
    def partition() -> dict:
        ais = core_models.EntityCategory.objects.get(graph=test_graph, key="AIS")
        nodes = list(evidence_models.Instance.objects.for_organization(test_graph.organization).filter(term__in=selector_module.term_ids_for(test_graph)))
        for node, subject in zip(nodes, (JOHANNES, CHRISTIAN)):
            _retract_classifications(test_graph, node.ref)
            _claim(test_graph, node.ref, ais, subject)

        for key, subject in (("AISprox", JOHANNES), ("AISdistal", CHRISTIAN)):
            core_models.EntityCategory.objects.create(
                graph=test_graph,
                key=key,
                age_name=key.lower(),
                label=key,
                definition=rules.definition(rules.rule(rules.word("AIS"), rules.by(subject))),
            )

        return graphs.rebuild(test_graph, table_projector)

    result = await partition()
    assert result["nodes"] == 2, "Both nodes are admitted, each by a different definition"
    assert result["unclassified"] == 0

    @sync_to_async
    def counts() -> dict[str, int]:
        return _labels(table_projector, test_graph, ["AISprox", "AISdistal", "AIS"])

    got = await counts()
    assert got["AISprox"] == 1, "Johannes's node carries the proximal term"
    assert got["AISdistal"] == 1, "Christian's carries the distal one"
    assert got["AIS"] == 2, "And both still carry the primitive word they were claimed under — a primitive category admits anything claimed as it (RFC 0019)"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_node_matching_two_definitions_is_drawn_under_both(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """A vertex carries every label that admits it (RFC 0019), so a node both
    definitions admit is drawn once, under both — and under the primitive AIS
    it was claimed as, because a primitive category means "anything claimed
    under this word". Refusing it as ambiguous used to be the answer; that was
    Apache AGE's one-label-per-vertex dressed as policy, and choosing between
    the two would have buried exactly the disagreement the view can now show.
    """

    await writes.create_entity(api_schema, simple_api_context, "AIS")

    @sync_to_async
    def both_claim_it() -> dict:
        ais = core_models.EntityCategory.objects.get(graph=test_graph, key="AIS")
        node = evidence_models.Instance.objects.for_organization(test_graph.organization).filter(term__in=selector_module.term_ids_for(test_graph)).first()
        _retract_classifications(test_graph, node.ref)

        # The same node, claimed as AIS by both annotators.
        _claim(test_graph, node.ref, ais, JOHANNES)
        _claim(test_graph, node.ref, ais, CHRISTIAN)

        for key, subject in (("AISprox", JOHANNES), ("AISdistal", CHRISTIAN)):
            core_models.EntityCategory.objects.create(
                graph=test_graph,
                key=key,
                age_name=key.lower(),
                label=key,
                definition=rules.definition(rules.rule(rules.word("AIS"), rules.by(subject))),
            )

        return graphs.rebuild(test_graph, table_projector)

    result = await both_claim_it()

    assert result["nodes"] == 1, "A node two definitions admit is drawn — once"
    assert result["unclassified"] == 0

    @sync_to_async
    def counts() -> dict[str, int]:
        return _labels(table_projector, test_graph, ["AISprox", "AISdistal", "AIS"])

    assert await counts() == {"AISprox": 1, "AISdistal": 1, "AIS": 1}, "one vertex, three labels"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_primitive_category_behaves_exactly_as_before(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """A graph that declares no definitions must be unchanged by any of this.

    The compatibility claim. Every existing graph has empty definitions, so every
    existing graph keeps projecting exactly the nodes it did — membership falls
    back to what was asserted.
    """

    await writes.create_entity(api_schema, simple_api_context, "AIS")

    @sync_to_async
    def rebuild() -> tuple[dict, dict[str, int]]:
        result = graphs.rebuild(test_graph, table_projector)
        return result, _labels(table_projector, test_graph, ["AIS"])

    result, counts = await rebuild()

    assert result["nodes"] == 1
    assert result["unclassified"] == 0, "Nothing is dropped when nothing is defined"
    assert counts["AIS"] == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_category_can_derive_from_several_words_the_graph_never_declares(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """ "Neuron here means anything claimed Pyramidal or Interneuron."

    Two things this holds up, and both were broken.

    A definition used to take a single word, so a defined category was a rename rather
    than a definition — it could not express a union, which is the ordinary
    ontology operation of grouping several claimed kinds under one heading.

    And membership counted only the words a graph's categories *declare*. A node
    claimed Pyramidal therefore never entered `instances_for` for a graph that only
    declares Neuron, so it never reached `resolve_categories` and the definition
    never fired: the category matched claims the graph could not see. Every other
    test here defines `AIS` over `"AIS"` — the category's own word — so membership
    worked by coincidence and the gap stayed invisible.

    Note what the node is *not*: reclassified. Nothing writes "Neuron" anywhere.
    Both nodes keep their own claims, and a second view is free to disagree.
    """
    await writes.create_entity(api_schema, simple_api_context, "AIS")
    await writes.create_entity(api_schema, simple_api_context, "AIS")

    @sync_to_async
    def regroup() -> dict:

        organization = test_graph.organization
        nodes = list(evidence_models.Instance.objects.for_organization(organization).filter(term__in=selector_module.term_ids_for(test_graph)))
        assert len(nodes) == 2

        # Claim the two nodes under words this graph declares no category for.
        # Retract the creating AIS claims so nothing but the definition can admit
        # them — otherwise the primitive fallback would carry the test.
        for node, key in zip(nodes, ("Pyramidal", "Interneuron")):
            _retract_classifications(test_graph, node.ref)
            term = writer.ensure_term(organization, core_models.EntityCategory.KIND, key)
            assertion = writer.create_assertion(organization, subject=JOHANNES, app_id="pytest")
            writer.create_link(organization, kind=evidence_models.Link.Kind.CLASSIFIES, source_ref=node.ref, target_ref=str(term.pk), assertion=assertion, term=term)
            # `node.term` is deliberately left alone. It used to be rewritten here
            # to match, which the append-only trigger now refuses — and rightly:
            # the originating word is what the node was created under, and editing
            # it is rewriting history rather than adding to it. The test does not
            # need it either. `term_ids_for` widens to the words a definition
            # derives from, so a node still carrying "AIS" is in `instances_for`, and
            # `resolve_categories` matches on the CLASSIFIES claims above — which
            # is precisely the mechanism under test.

        assert not core_models.EntityCategory.objects.filter(graph=test_graph, key__in=("Pyramidal", "Interneuron")).exists(), "The graph must declare neither word for this to mean anything"

        core_models.EntityCategory.objects.create(
            graph=test_graph,
            key="Neuron",
            age_name="neuron",
            label="Neuron",
            definition=rules.definition(rules.rule(rules.word("Pyramidal", "Interneuron"))),
        )

        return graphs.rebuild(test_graph, table_projector)

    result = await regroup()
    assert result["nodes"] == 2, "Both nodes are admitted by the one definition, from words the graph never declares"
    assert result["unclassified"] == 0

    @sync_to_async
    def counts() -> dict[str, int]:
        return _labels(table_projector, test_graph, ["Neuron", "AIS"])

    got = await counts()
    assert got["Neuron"] == 2, "Grouped under the heading this view gives them"
    assert got["AIS"] == 0, "And not under the word they were created with, which no longer stands"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_single_word_definition_still_reads_as_one(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """A WORD condition's value may be one word (IS) or several (IN).

    Definitions are hand-written JSON, and the vocabulary is always read
    through `asserted_as_keys`, whatever the operator.
    """
    assert selector_module.asserted_as_keys(rules.definition(rules.rule(rules.word("AIS")))) == ["AIS"]
    assert selector_module.asserted_as_keys(rules.definition(rules.rule(rules.word("AIS", "Soma")))) == ["AIS", "Soma"]
    assert selector_module.asserted_as_keys({}) == []
    assert selector_module.asserted_as_keys(None) == []


PETER = "peter"
KARL = "karl"
DEC_1 = datetime(2026, 12, 1, tzinfo=timezone.utc)
DEC_10 = datetime(2026, 12, 10, tzinfo=timezone.utc)


async def _five_claims(api_schema, ctx, literal_graph) -> dict[str, str]:
    """Five entities, one annotator claim each — the shared evidence.

    Creation mints the word under the request's own subject (which no clause
    names); the annotator claims are writer-level so subject and belief time
    are chosen, not inherited.
    """
    c1 = await writes.create_entity(api_schema, ctx, "Cell")
    c2 = await writes.create_entity(api_schema, ctx, "Cell")
    c3 = await writes.create_entity(api_schema, ctx, "StemCell")
    c4 = await writes.create_entity(api_schema, ctx, "StemCell")
    c5 = await writes.create_entity(api_schema, ctx, "StemCell")

    @sync_to_async
    def annotate():
        cell = core_models.Category.objects.get(graph=literal_graph, key="Cell")
        stem = core_models.Category.objects.get(graph=literal_graph, key="StemCell")
        claims.classify(literal_graph, c1, cell, PETER)
        claims.classify(literal_graph, c2, cell, KARL)
        claims.classify(literal_graph, c3, stem, PETER)
        claims.classify(literal_graph, c4, stem, KARL, asserted_at=DEC_1)
        claims.classify(literal_graph, c5, stem, KARL, asserted_at=DEC_10)

    await annotate()
    return {"c1": c1, "c2": c2, "c3": c3, "c4": c4, "c5": c5}


def _defined_graph(request, name: str, key: str, definition: input_models.CategoryDefinitionInput) -> core_models.Graph:
    """One graph whose single category's meaning is declared **in the schema** —
    the definition document carries the predicate (RFC 0007)."""
    return materialize(
        input_models.GraphDefinitionInput(
            system_version="1.0.0",
            extensions=input_models.GraphExtensionsInput(entities=[input_models.EntityDefinitionInput(key=key, definition=definition)]),
        ),
        None,
        user=request._user,
        organization=request._organization,
        membership=request.membership,
        name=name,
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_category_subsumes_word_annotator_time_clauses(api_schema, simple_api_context, subsumption_graph, literal_graph, table_projector) -> None:
    refs = await _five_claims(api_schema, simple_api_context, literal_graph)

    @sync_to_async
    def views():
        _rebuild(subsumption_graph, table_projector)
        subsumed = namespaces.graph_table(subsumption_graph, 'MATCH (c IS "Cell") COLUMNS (c.__ref AS ref, c.__label AS label)')
        literal_cells = namespaces.graph_table(literal_graph, 'MATCH (c IS "Cell") COLUMNS (c.__ref AS ref)')
        literal_stems = namespaces.graph_table(literal_graph, 'MATCH (s IS "StemCell") COLUMNS (s.__ref AS ref)')
        return subsumed, literal_cells, literal_stems

    subsumed, literal_cells, literal_stems = await views()
    assert {row[0] for row in subsumed} == {refs["c1"], refs["c5"]}, "Peter's Cell and Karl's post-Dec-5 StemCell, nothing else"
    assert {row[1] for row in subsumed} == {"Cell"}, "both drawn under this view's one word"
    assert {row[0] for row in literal_cells} == {refs["c1"], refs["c2"]}, "the literal view keeps every claim under its own word"
    assert {row[0] for row in literal_stems} == {refs["c3"], refs["c4"], refs["c5"]}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_clauses_do_not_cross_multiply(api_schema, simple_api_context, subsumption_graph, literal_graph, table_projector, authenticated_context) -> None:
    """The exact wrong answers the flat form gives, pinned on both sides.

    Karl's Cell, Peter's StemCell and Karl's early StemCell each combine a word
    from one clause with an annotator or a time from another. The clause form
    excludes all three; the flat encoding of the same intent admits every one.
    """
    refs = await _five_claims(api_schema, simple_api_context, literal_graph)
    request = authenticated_context.request

    @sync_to_async
    def both_encodings():
        _rebuild(subsumption_graph, table_projector)
        subsumed = {row[0] for row in namespaces.graph_table(subsumption_graph, 'MATCH (c IS "Cell") COLUMNS (c.__ref AS ref)')}

        flat_graph = _defined_graph(
            request,
            "flat-cross-product",
            "Cell",
            # One WORD list, one SUBJECT list in one rule: the binding is lost.
            input_models.CategoryDefinitionInput.model_validate(rules.definition(rules.rule(rules.word("Cell", "StemCell"), rules.by(PETER, KARL)))),
        )
        _rebuild(flat_graph, table_projector)
        flat = {row[0] for row in namespaces.graph_table(flat_graph, 'MATCH (c IS "Cell") COLUMNS (c.__ref AS ref)')}
        return subsumed, flat

    subsumed, flat = await both_encodings()
    for wrong in ("c2", "c3", "c4"):
        assert refs[wrong] not in subsumed, f"{wrong} combines clauses and must not be admitted"
    assert flat == set(refs.values()), "the flat cross-product admits all five — the reason clauses exist"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_flat_since_bound_admits_only_later_claims(api_schema, simple_api_context, literal_graph, table_projector, authenticated_context) -> None:
    refs = await _five_claims(api_schema, simple_api_context, literal_graph)
    request = authenticated_context.request

    @sync_to_async
    def late_stems():
        graph = _defined_graph(
            request,
            "late-stems",
            "LateStem",
            input_models.CategoryDefinitionInput.model_validate(rules.definition(rules.rule(rules.word("StemCell"), rules.by(KARL), rules.since(datetime(2026, 12, 5, tzinfo=timezone.utc))))),
        )
        _rebuild(graph, table_projector)
        return {row[0] for row in namespaces.graph_table(graph, 'MATCH (s IS "LateStem") COLUMNS (s.__ref AS ref)')}

    assert await late_stems() == {refs["c5"]}, "Dec 1 is before the bound, Dec 10 after — `since` is the lower half `as_of` never had"


ENTITIES = """
    query($category: ID!) {
        entities(entityCategoryId: $category) { __typename id }
    }
"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_entity_category_defined_over_an_event_word_admits_no_events(api_schema, simple_api_context, test_graph: core_models.Graph) -> None:
    event_id = await writes.create_event(api_schema, simple_api_context, "Mitosis")

    @sync_to_async
    def defined_over_mitosis():
        category = core_models.EntityCategory.objects.create(graph=test_graph, key="MitoticThing", label="Mitotic thing", age_name="MitoticThing", definition=rules.definition(rules.rule(rules.word("Mitosis"))))
        admitted = projector.refs_admitted_by(category)
        return category.pk, admitted, asserted_terms.keys_and_kinds_for_graph(test_graph)

    category_pk, admitted, derived = await defined_over_mitosis()
    assert event_id not in admitted, "an entity definition must not admit an event's classification"
    assert ("Mitosis", "ENTITY") in derived and ("Mitosis", "NATURAL_EVENT") not in derived, "the derived half of the vocabulary is keyed on kind as well as key"

    listed = await api_schema.execute(ENTITIES, variable_values={"category": str(category_pk)}, context_value=simple_api_context)
    assert listed.errors is None, f"GraphQL errors: {listed.errors}"
    assert listed.data["entities"] == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_view_that_declares_the_word_later_can_pick_the_claim_up(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """Org-scoped write, then materialization — the whole point of the change.

    `materialize` created the categories and the AGE namespace and stopped, so a
    graph declaring a word the organization had already used came up empty and
    stayed that way until an operator ran `manage.py reproject`. `backfill` is that
    step, offered at the moment the declaration is made.
    """
    word = f"Latecomer_{uuid.uuid4().hex[:8]}"
    entity_id = await writes.create_entity(api_schema, simple_api_context, word)

    @sync_to_async
    def drawn_in(graph: core_models.Graph) -> int:
        return drawing.vertices_with_ref(graph, entity_id)

    assert await drawn_in(test_graph) == 0, "Nothing draws it yet"

    # Declaring the word alone does not project the history — the flag is opt-in
    # because the work is proportional to the organization's evidence.
    quiet = await api_schema.execute(
        writes.CREATE_ENTITY_CATEGORY,
        variable_values={"input": {"graph": str(test_graph.pk), "key": word, "backfill": False}},
        context_value=simple_api_context,
    )
    assert quiet.errors is None, f"GraphQL errors: {quiet.errors}"
    assert await drawn_in(test_graph) == 0, "Declared, but the history was not asked for"

    asked = await api_schema.execute(
        writes.CREATE_ENTITY_CATEGORY,
        variable_values={"input": {"graph": str(test_graph.pk), "key": word, "backfill": True}},
        context_value=simple_api_context,
    )
    assert asked.errors is None, f"GraphQL errors: {asked.errors}"
    assert await drawn_in(test_graph) == 1, "The claim that predated the view is now drawn in it"


def test_create_graph_offers_the_history(api_schema: kante.Schema) -> None:
    """`createGraph` takes `backfill`, and it defaults to off."""
    field = api_schema._schema.type_map["CreateGraphInput"].fields["backfill"]

    assert field is not None, "createGraph must be able to project the evidence its words admit"
    assert field.default_value is False, "and must not do it unasked — the work is O(the organization)"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_new_graph_can_be_a_view_over_history(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    bio_graph_schema: input_models.GraphDefinitionInput,
    table_projector,
) -> None:
    """A graph materialized after the claim holds it.

    Goes through `materialize` rather than the `createGraph` mutation, which
    forwards to it verbatim: re-encoding the whole bio schema as GraphQL variables
    would make this a test of camelCasing. The mutation's own wiring is held up by
    `test_create_graph_offers_the_history` above.
    """
    entity_id = await writes.create_entity(api_schema, simple_api_context, "Cell")

    @sync_to_async
    def hindsight() -> tuple[core_models.Graph, core_models.Graph]:
        from graph_engine.materialize import materialize

        request = simple_api_context.request
        common = dict(
            user=request._user,
            organization=request._organization,
            membership=request.membership,
        )
        quiet = materialize(bio_graph_schema, table_projector, name=f"quiet_{uuid.uuid4().hex[:6]}", **common)
        asked = materialize(bio_graph_schema, table_projector, name=f"asked_{uuid.uuid4().hex[:6]}", backfill=True, **common)
        return quiet, asked

    quiet, asked = await hindsight()

    @sync_to_async
    def drawn_in(graph: core_models.Graph) -> int:
        return drawing.vertices_with_ref(graph, entity_id)

    assert await drawn_in(quiet) == 0, "A new view declaring the word comes up empty unless asked"
    assert await drawn_in(asked) == 1, "And holds the organization's history when it is"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_classification_admits_per_clause(api_schema, simple_api_context, table_projector) -> None:
    """Peter's word before Dec 5 and Karl's word after — nothing else."""
    graph_id = await _example_graph(api_schema, simple_api_context, "trust-classification")

    @sync_to_async
    def build_and_read():
        graph = core_models.Graph.objects.get(pk=graph_id)
        org = graph.organization
        drawn = claims.mint(org, "AIS", "peter", asserted_at=BEFORE)
        too_late = claims.mint(org, "AIS", "peter", asserted_at=AFTER)
        karls = claims.mint(org, "AxonInitialSegment", "karl", asserted_at=AFTER)
        too_early = claims.mint(org, "AxonInitialSegment", "karl", asserted_at=BEFORE)
        sloppy = claims.mint(org, "AIS", "peter", asserted_at=BEFORE, app_id="sloppy-import")
        _rebuild(graph_id, table_projector)
        return {ref: drawing.vertices_with_ref(graph, ref) for ref in (drawn, too_late, karls, too_early, sloppy)}, drawn, too_late, karls, too_early, sloppy

    counts, drawn, too_late, karls, too_early, sloppy = await build_and_read()
    assert counts[drawn] == 1, "Peter's AIS before Dec 5 is rule 1"
    assert counts[karls] == 1, "Karl's AxonInitialSegment after Dec 5 is rule 2"
    assert counts[too_late] == 0, "Peter after Dec 5 falls outside his rule"
    assert counts[too_early] == 0, "Karl before Dec 5 falls outside his"
    assert counts[sloppy] == 0, "the `unless` group blocks Peter's claim through the sloppy import"
