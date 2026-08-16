"""Indexing the words a category's definition derives from.

A graph sees a word two ways: it **declares** one (`Category.term`, an ordinary
foreign key) or it **derives** from one, by naming it in
`definition.asserted_as`. Only the second was un-joinable, so
`selector._graph_ids_by_term` — which every instance write goes through — read
every category in the organization and pulled every `definition` blob out of the
database to loop over in Python.

`core.CategoryAssertedTerm` is that half normalized. These tests pin the two
things that make it safe to depend on: **the index and the definitions agree**,
maintained incrementally or rebuilt, and **the reads actually use it**.
"""

import pytest
from authentikate.models import Organization

from core import asserted_terms, models as core_models
from evidence import models as evidence_models, selector, writer


def _defined(graph: core_models.Graph, key: str, asserted_as) -> core_models.EntityCategory:
    """An entity category defined over claims rather than declared primitively."""
    return core_models.EntityCategory.objects.create(
        graph=graph,
        key=key,
        age_name=key.lower(),
        definition={"asserted_as": asserted_as},
    )


@pytest.mark.django_db(transaction=True)
def test_creating_a_defined_category_indexes_its_words(graph_a: core_models.Graph) -> None:
    """The signal, doing the one thing it is for."""
    category = _defined(graph_a, "Neuron", ["Pyramidal", "Interneuron"])

    rows = core_models.CategoryAssertedTerm.objects.filter(category=category)
    assert {row.key for row in rows} == {"Pyramidal", "Interneuron"}
    assert {row.graph_id for row in rows} == {graph_a.pk}, "The graph is denormalized onto the row — the read is 'which graphs derive from this word'"
    assert {row.organization_id for row in rows} == {graph_a.organization_id}


@pytest.mark.django_db(transaction=True)
def test_changing_a_definition_rewrites_rather_than_appends(graph_a: core_models.Graph) -> None:
    """A definition can stop naming a word as easily as start naming one.

    An insert-only index would leave the graph deriving from a word its own
    definition no longer mentions, and nothing would ever say so.
    """
    category = _defined(graph_a, "Neuron", ["Pyramidal"])

    category.definition = {"asserted_as": ["Interneuron"]}
    category.save()

    assert {row.key for row in core_models.CategoryAssertedTerm.objects.filter(category=category)} == {"Interneuron"}


@pytest.mark.django_db(transaction=True)
def test_suspending_schema_versioning_does_not_suspend_the_index(graph_a: core_models.Graph) -> None:
    """The gate the two handlers deliberately do not share.

    `materialize()` wraps its whole run in `versioning.suspended()` so that
    expressing one schema emits one version rather than one per category. Sharing
    that gate here would leave a freshly materialized graph deriving from nothing
    at all — which is exactly the case where the index has the most to say, and
    the failure would look like the defined categories simply not working.
    """
    from graph_engine import versioning

    with versioning.suspended():
        category = _defined(graph_a, "Neuron", ["Pyramidal"])

    assert core_models.GraphSchema.objects.filter(graph=graph_a).count() == 0, "Versioning really was suspended"
    assert {row.key for row in core_models.CategoryAssertedTerm.objects.filter(category=category)} == {"Pyramidal"}


@pytest.mark.django_db(transaction=True)
def test_a_primitive_category_indexes_nothing(graph_a: core_models.Graph) -> None:
    """An empty definition means "membership is whatever was asserted"."""
    category = core_models.EntityCategory.objects.create(graph=graph_a, key="AIS", age_name="ais")

    assert not core_models.CategoryAssertedTerm.objects.filter(category=category).exists()


@pytest.mark.django_db(transaction=True)
def test_a_bare_string_is_one_word(graph_a: core_models.Graph) -> None:
    """`asserted_as` accepts a single word, and definitions are hand-written JSON.

    Read through `selector.asserted_as_keys` rather than re-implemented here, so
    the index cannot come to a different conclusion than the predicate that
    matches claims.
    """
    category = _defined(graph_a, "Neuron", "Pyramidal")

    assert {row.key for row in core_models.CategoryAssertedTerm.objects.filter(category=category)} == {"Pyramidal"}


@pytest.mark.django_db(transaction=True)
def test_deleting_the_category_drops_its_words(graph_a: core_models.Graph) -> None:
    """A word nothing derives from any more is not a word the graph sees."""
    category = _defined(graph_a, "Neuron", ["Pyramidal"])
    category.delete()

    assert not core_models.CategoryAssertedTerm.objects.filter(key="Pyramidal").exists()


@pytest.mark.django_db(transaction=True)
def test_the_rebuild_agrees_with_the_signal(organization: Organization, graph_a: core_models.Graph, graph_b: core_models.Graph) -> None:
    """The correctness backstop, and the reason `refold` exists separately.

    `CLAUDE.md` records what it costs when a fold and its rebuild are allowed to
    disagree: `merge`, `recompute` and `refold_state` once produced different
    numbers from the same evidence, and the "backstop" agreed with the wrong one.
    """
    _defined(graph_a, "Neuron", ["Pyramidal", "Interneuron"])
    _defined(graph_b, "Neuron", ["Pyramidal"])
    _defined(graph_b, "Glia", "Astrocyte")

    incremental = asserted_terms.stored(organization)
    assert incremental == asserted_terms.expected(organization)

    asserted_terms.refold(organization)

    assert asserted_terms.stored(organization) == incremental


@pytest.mark.django_db(transaction=True)
def test_a_definition_edited_behind_the_signal_is_reported(organization: Organization, graph_a: core_models.Graph) -> None:
    """`--check`'s reason to exist.

    `queryset.update()` writes no `post_save`, and it can edit a definition. The
    index then says the graph derives from a word it does not, which is invisible
    until somebody asks.
    """
    category = _defined(graph_a, "Neuron", ["Pyramidal"])

    core_models.Category.objects.filter(pk=category.pk).update(definition={"asserted_as": ["Interneuron"]})

    stored = asserted_terms.stored(organization)
    expected = asserted_terms.expected(organization)
    assert stored != expected
    assert expected - stored == {(category.pk, "Interneuron")}
    assert stored - expected == {(category.pk, "Pyramidal")}

    asserted_terms.refold(organization)
    assert asserted_terms.stored(organization) == expected


@pytest.mark.django_db(transaction=True)
def test_the_index_is_scoped_to_its_organization(organization: Organization, other_organization: Organization, graph_a: core_models.Graph) -> None:
    """A rebuild of one tenant must not touch another's rows."""
    _defined(graph_a, "Neuron", ["Pyramidal"])

    assert asserted_terms.graph_ids_by_key(other_organization) == {}
    assert asserted_terms.graph_ids_by_key(organization, ["Pyramidal"]) == {"Pyramidal": [graph_a.pk]}

    asserted_terms.refold(other_organization)
    assert asserted_terms.stored(organization), "Refolding one organization must leave another's rows alone"


# ===================================================================
# The reads that have to use it
# ===================================================================


@pytest.mark.django_db(transaction=True)
def test_a_derived_word_still_widens_a_graphs_vocabulary(organization: Organization, graph_a: core_models.Graph) -> None:
    """`docs/LOG.md` calls this widening "what makes a definition a definition rather than a rename".

    A graph whose "Neuron" is *defined* as "anything claimed Pyramidal" declares
    no `Pyramidal` category at all, so counting only declared words excluded those
    nodes from `nodes_for` — the definition matched claims the graph could not
    see.
    """
    _defined(graph_a, "Neuron", ["Pyramidal"])
    pyramidal = writer.ensure_term(organization, "ENTITY", "Pyramidal")

    assert pyramidal.pk in selector.term_ids_for(graph_a)


@pytest.mark.django_db(transaction=True)
def test_a_word_indexed_before_it_is_minted_resolves_once_it_exists(organization: Organization, graph_a: core_models.Graph) -> None:
    """Which is why the row stores a key and not a `Term` foreign key.

    Terms are minted lazily, when somebody first claims one — so a definition
    routinely names a word that has no `Term` row yet. An FK would have nothing to
    point at, and the graph would stop deriving from the word until the first
    claim arrived, which is exactly backwards: the definition is what makes the
    claim visible.
    """
    category = _defined(graph_a, "Neuron", ["Pyramidal"])

    # The category declares "Neuron" — creating one mints that word — but nothing
    # has claimed "Pyramidal" yet, so there is no term for it to point at.
    assert selector.term_ids_for(graph_a) == {category.term_id}
    assert not evidence_models.Term.objects.for_organization(organization).filter(key="Pyramidal").exists()
    assert asserted_terms.graph_ids_by_key(organization, ["Pyramidal"]) == {"Pyramidal": [graph_a.pk]}, "and the word is indexed regardless"

    pyramidal = writer.ensure_term(organization, "ENTITY", "Pyramidal")

    assert selector.term_ids_for(graph_a) == {category.term_id, pyramidal.pk}


@pytest.mark.django_db(transaction=True)
def test_a_write_lands_in_the_graph_that_only_derives_from_the_word(
    organization: Organization,
    graph_a: core_models.Graph,
    assertion: evidence_models.Assertion,
) -> None:
    """`graph_ids_for_node_ids` is the only thing deciding where a write lands.

    It has to be the exact inverse of `nodes_for`, derived half included — a
    narrower rule here means a newly claimed Pyramidal reaches the defining view
    only on the next rebuild.
    """
    _defined(graph_a, "Neuron", ["Pyramidal"])
    pyramidal = writer.ensure_term(organization, "ENTITY", "Pyramidal")
    node = evidence_models.Node.objects.create_for_organization(
        organization=organization,
        kind=evidence_models.Node.Kind.ENTITY,
        term=pyramidal,
        assertion=assertion,
    )

    assert selector.graph_ids_for_node_ids(organization, [node.ref]) == [(node.ref, graph_a.pk)]


@pytest.mark.django_db(transaction=True)
def test_deciding_where_a_write_lands_does_not_scale_with_the_ontology(
    organization: Organization,
    user,
    graph_a: core_models.Graph,
    assertion: evidence_models.Assertion,
    django_assert_num_queries,
) -> None:
    """The measured problem this table was built for.

    `_graph_ids_by_term` runs on every instance write. It used to select
    `definition` for every category in the organization and parse the JSON in
    Python, so the cost of one write grew with the size of the whole ontology.
    The query *count* was always flat; what was not flat is what those queries
    returned, and a count test is the only part of that a test can hold onto —
    so this pins the count and leaves the payload to the narrowed `values_list`.
    """
    _defined(graph_a, "Neuron", ["Pyramidal"])
    pyramidal = writer.ensure_term(organization, "ENTITY", "Pyramidal")
    node = evidence_models.Node.objects.create_for_organization(
        organization=organization,
        kind=evidence_models.Node.Kind.ENTITY,
        term=pyramidal,
        assertion=assertion,
    )

    with django_assert_num_queries(4) as captured:
        selector.graph_ids_for_node_ids(organization, [node.ref])

    assert not any("definition" in query["sql"] for query in captured.captured_queries), "Deciding where a write lands must not read a single definition blob"
