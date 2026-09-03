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

from tests import rules
from asgiref.sync import sync_to_async
from kante.context import HttpContext

from core import models as core_models
from evidence import models as evidence_models
from evidence import selector as selector_module
from evidence import writer
from graph_engine.controller import GraphController
from tests import claims, drawing

CREATE_ENTITY = """
    mutation CreateEntity($input: AssertEntityExistsInput!) {
        assertEntityExists(input: $input) { instance { id } }
    }
"""

JOHANNES = "johannes"
CHRISTIAN = "christian"


async def _an_ais(api_schema: kante.Schema, ctx: HttpContext, graph: core_models.Graph) -> str:
    category = await core_models.EntityCategory.objects.filter(graph=graph, key="AIS").afirst()
    assert category is not None
    created = await api_schema.execute(
        CREATE_ENTITY,
        variable_values={"input": {"term": category.key, "supportingEvidence": []}},
        context_value=ctx,
    )
    assert created.errors is None, f"GraphQL errors: {created.errors}"
    return created.data["assertEntityExists"]["instance"]["id"]


# The claim spellings live in `tests/claims.py` now, shared with the
# subsumption tests, which additionally need `asserted_at`.
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

    entity_id = await _an_ais(api_schema, simple_api_context, test_graph)

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
    """"In this graph, AIS means the ones Johannes called AIS."

    The node Christian called AIS is admitted by no category here, so it is not in
    the view — and the count is reported rather than the graph quietly shrinking.
    """

    await _an_ais(api_schema, simple_api_context, test_graph)
    await _an_ais(api_schema, simple_api_context, test_graph)

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

        return GraphController(projector=table_projector).rebuild_projection(test_graph)

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

    await _an_ais(api_schema, simple_api_context, test_graph)
    await _an_ais(api_schema, simple_api_context, test_graph)

    @sync_to_async
    def setup() -> int:
        ais = core_models.EntityCategory.objects.get(graph=test_graph, key="AIS")
        nodes = list(evidence_models.Instance.objects.for_organization(test_graph.organization).filter(term__in=selector_module.term_ids_for(test_graph)))
        for node, subject in zip(nodes, (JOHANNES, CHRISTIAN)):
            _retract_classifications(test_graph, node.ref)
            _claim(test_graph, node.ref, ais, subject)

        ais.definition = rules.definition(rules.rule(rules.word("AIS"), rules.by(JOHANNES)))
        ais.save()
        GraphController(projector=table_projector).rebuild_projection(test_graph)
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
        GraphController(projector=table_projector).rebuild_projection(test_graph)
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
    """"Split AIS into AISprox if Johannes called it and AISdistal if Christian did."

    Two definitions over the same claims. Neither node was ever reclassified and
    no evidence says "AISprox" — the split exists only in this graph's terms.
    """

    await _an_ais(api_schema, simple_api_context, test_graph)
    await _an_ais(api_schema, simple_api_context, test_graph)

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

        return GraphController(projector=table_projector).rebuild_projection(test_graph)

    result = await partition()
    assert result["nodes"] == 2, "Both nodes are admitted, each by a different definition"
    assert result["unclassified"] == 0

    @sync_to_async
    def counts() -> dict[str, int]:
        return _labels(table_projector, test_graph, ["AISprox", "AISdistal", "AIS"])

    got = await counts()
    assert got["AISprox"] == 1, "Johannes's node carries the proximal term"
    assert got["AISdistal"] == 1, "Christian's carries the distal one"
    assert got["AIS"] == 0, "And neither falls back to the term they were actually asserted under"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_node_matching_two_definitions_is_refused_not_guessed(
    api_schema: kante.Schema,
    simple_api_context: HttpContext,
    test_graph: core_models.Graph,
    table_projector,
) -> None:
    """A vertex carries one label, so a node both definitions admit has no answer.

    Picking one would bury exactly the disagreement the evidence base exists to
    preserve. The codebase already refuses rather than guesses in the same
    situation — `_value_kinds_for_rule` returns None and warns when a key has
    terms in more than one family.
    """

    await _an_ais(api_schema, simple_api_context, test_graph)

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

        return GraphController(projector=table_projector).rebuild_projection(test_graph)

    result = await both_claim_it()

    assert result["nodes"] == 0, "An ambiguous node is not projected under an arbitrary label"
    assert result["unclassified"] == 1, "It is reported instead"

    @sync_to_async
    def counts() -> dict[str, int]:
        return _labels(table_projector, test_graph, ["AISprox", "AISdistal", "AIS"])

    assert await counts() == {"AISprox": 0, "AISdistal": 0, "AIS": 0}


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

    await _an_ais(api_schema, simple_api_context, test_graph)

    @sync_to_async
    def rebuild() -> tuple[dict, dict[str, int]]:
        result = GraphController(projector=table_projector).rebuild_projection(test_graph)
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
    """"Neuron here means anything claimed Pyramidal or Interneuron."

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
    await _an_ais(api_schema, simple_api_context, test_graph)
    await _an_ais(api_schema, simple_api_context, test_graph)

    @sync_to_async
    def regroup() -> dict:
        from evidence import writer

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

        return GraphController(projector=table_projector).rebuild_projection(test_graph)

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
