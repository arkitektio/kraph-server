"""Folding sameness claims into components.

Every observation mints its own instance — "this is an AIS" writes a fresh node
rather than reusing one — so identity *between* observations is a claim, and the
component is the fold over those claims. `docs/LOG.md` listed this as a known
gap: *"No merge. Identity is a bare uuid, so one vertex standing for several
nodes is expressible — but nothing implements it."*

The load-bearing property is that **incremental maintenance and the rebuild
agree**. `evidence.state` has the same split and CLAUDE.md records what happens
when it slips: `merge`, `recompute` and `refold_state` once disagreed about which
metrics counted, so ingest and replay produced different numbers from the same
evidence. These tests pin the analogous agreement here.
"""

import uuid

import pytest
from authentikate.models import Organization

from evidence import identity, models as evidence_models, writer


@pytest.fixture
def node_factory(organization: Organization, assertion: evidence_models.Assertion):
    """Fresh entity instances, the way an observation mints them."""
    term = writer.ensure_term(organization, "ENTITY", "AIS")

    def _make() -> str:
        node = evidence_models.Instance.objects.create_for_organization(
            organization=organization,
            kind=evidence_models.Instance.Kind.ENTITY,
            term=term,
            assertion=assertion,
        )
        return str(node.pk)

    return _make


def _same(organization: Organization, assertion: evidence_models.Assertion, left: str, right: str) -> evidence_models.Link:
    link = writer.create_link(
        organization,
        kind=evidence_models.Link.Kind.SAME_AS,
        source_ref=left,
        target_ref=right,
        assertion=assertion,
    )
    identity.merge(organization, left, right)
    return link


@pytest.mark.django_db(transaction=True)
def test_an_unmerged_node_is_its_own_component(organization: Organization, node_factory) -> None:
    """A component of one has no row, and must still answer.

    Materializing a row per unmerged node would make this table as large as
    `Node` and say nothing, so `canonical_for` returns the node itself.
    """
    node = node_factory()

    assert identity.canonical_for(organization, node) == node
    assert identity.component_refs(organization, [node]) == {node: [node]}
    assert not evidence_models.InstanceIdentity.objects.for_organization(organization).exists()


@pytest.mark.django_db(transaction=True)
def test_merging_two_instances_makes_one_component(organization: Organization, assertion, node_factory) -> None:
    """ "This is AIS 6": a fresh instance, then a claim that it is one already known."""
    first, second = node_factory(), node_factory()
    _same(organization, assertion, first, second)

    component = identity.component_refs(organization, [first])[first]
    assert component == sorted([first, second])

    # Both ends answer identically — sameness is symmetric, so which one you ask
    # cannot matter.
    assert identity.component_refs(organization, [second])[second] == component
    assert identity.canonical_for(organization, first) == identity.canonical_for(organization, second)


@pytest.mark.django_db(transaction=True)
def test_the_representative_is_the_lowest_uuid_not_the_first_asserted(organization: Organization, assertion, node_factory) -> None:
    """Identity must not be an accident of arrival order.

    A replay reads the same claims in the same order the log records, but the
    *component* it lands on has to be the same whichever direction the claim was
    written in — which is what a deterministic representative buys.
    """
    first, second = node_factory(), node_factory()
    _same(organization, assertion, first, second)

    assert identity.canonical_for(organization, first) == min(first, second)


@pytest.mark.django_db(transaction=True)
def test_sameness_is_transitive(organization: Organization, assertion, node_factory) -> None:
    """A~B and B~C means A~C, without anybody claiming A~C."""
    a, b, c = node_factory(), node_factory(), node_factory()
    _same(organization, assertion, a, b)
    _same(organization, assertion, b, c)

    assert identity.component_refs(organization, [a])[a] == sorted([a, b, c])


@pytest.mark.django_db(transaction=True)
def test_a_fold_row_can_say_what_it_is(organization: Organization, assertion, node_factory) -> None:
    """`str(row)` read `node_id`, a field migration 0008 renamed, and raised."""
    a, b = node_factory(), node_factory()
    _same(organization, assertion, a, b)

    for row in evidence_models.InstanceIdentity.objects.for_organization(organization):
        assert str(row) == f"{row.instance_id} ~ {row.canonical_id}"


@pytest.mark.django_db(transaction=True)
def test_a_repeated_claim_changes_nothing(organization: Organization, assertion, node_factory) -> None:
    """Agreement is counted in the log, not in the fold.

    The fold records *which nodes are one thing*. How many people said so is a
    question for the claims, and answering it here would make the component
    depend on how often it was asserted.
    """
    a, b = node_factory(), node_factory()
    _same(organization, assertion, a, b)
    before = identity.component_refs(organization, [a])[a]

    _same(organization, assertion, a, b)

    assert identity.component_refs(organization, [a])[a] == before
    assert evidence_models.InstanceIdentity.objects.for_organization(organization).count() == 2


@pytest.mark.django_db(transaction=True)
def test_retracting_a_bridge_splits_the_component(organization: Organization, assertion, node_factory) -> None:
    """Union-find cannot un-union, so the component is rebuilt instead.

    A~B~C with the B–C claim withdrawn must become {A,B} and {C} — and nothing
    incremental can work that out, because the row does not record which claim
    put each member there.
    """
    a, b, c = node_factory(), node_factory(), node_factory()
    _same(organization, assertion, a, b)
    bridge = _same(organization, assertion, b, c)

    assert identity.component_refs(organization, [a])[a] == sorted([a, b, c])

    writer.retract(organization, bridge, assertion)
    identity.retract(organization, bridge)
    identity.recompute(organization, identity.canonical_for(organization, a))

    assert identity.component_refs(organization, [a])[a] == sorted([a, b])
    assert identity.component_refs(organization, [c])[c] == [c], "The far side is its own thing again"


@pytest.mark.django_db(transaction=True)
def test_retracting_a_redundant_claim_splits_nothing(organization: Organization, assertion, node_factory) -> None:
    """The rebuild is what tells a bridge from a redundant edge.

    A~B, B~C and A~C: withdrawing A~C leaves the three still connected. Guessing
    at retraction time which kind of edge it was would be a second implementation
    of the question the rebuild already answers.
    """
    a, b, c = node_factory(), node_factory(), node_factory()
    _same(organization, assertion, a, b)
    _same(organization, assertion, b, c)
    redundant = _same(organization, assertion, a, c)

    writer.retract(organization, redundant, assertion)
    identity.retract(organization, redundant)
    identity.recompute(organization, identity.canonical_for(organization, a))

    assert identity.component_refs(organization, [a])[a] == sorted([a, b, c])


@pytest.mark.django_db(transaction=True)
def test_the_rebuild_agrees_with_incremental_maintenance(organization: Organization, assertion, node_factory) -> None:
    """The correctness backstop, and the reason `refold` exists separately.

    Whatever the incremental path did, a rebuild from the surviving claims is
    what the answer should have been. `State`'s history is the warning: three
    write paths that were meant to agree, did not, and the "backstop" agreed with
    the wrong one.
    """
    nodes = [node_factory() for _ in range(6)]
    _same(organization, assertion, nodes[0], nodes[1])
    _same(organization, assertion, nodes[1], nodes[2])
    _same(organization, assertion, nodes[3], nodes[4])

    incremental = {node: identity.component_refs(organization, [node])[node] for node in nodes}

    identity.refold(organization)

    rebuilt = {node: identity.component_refs(organization, [node])[node] for node in nodes}
    assert rebuilt == incremental
    assert rebuilt[nodes[0]] == sorted(nodes[0:3])
    assert rebuilt[nodes[3]] == sorted(nodes[3:5])
    assert rebuilt[nodes[5]] == [nodes[5]], "A node nobody merged stays alone through a refold"


@pytest.mark.django_db(transaction=True)
def test_a_retracted_claim_does_not_survive_a_refold(organization: Organization, assertion, node_factory) -> None:
    """`refold` folds standing claims only.

    Retraction is a `Standing(stands=False)` rather than a delete, so the link row is
    still there; only the anti-join against `CurrentStanding` says it is gone.
    """
    a, b = node_factory(), node_factory()
    link = _same(organization, assertion, a, b)
    writer.retract(organization, link, assertion)

    identity.refold(organization)

    assert identity.component_refs(organization, [a])[a] == [a]


@pytest.mark.django_db(transaction=True)
def test_components_are_scoped_to_their_organization(organization: Organization, other_organization: Organization, assertion, node_factory) -> None:
    """A fold over evidence inherits evidence's tenancy."""
    a, b = node_factory(), node_factory()
    _same(organization, assertion, a, b)

    assert identity.component_refs(other_organization, [a])[a] == [a]


@pytest.mark.django_db(transaction=True)
def test_asking_about_many_nodes_costs_two_queries(organization: Organization, assertion, node_factory, django_assert_num_queries) -> None:
    """The point of the table: a page of subjects is not a page of queries."""
    pairs = [(node_factory(), node_factory()) for _ in range(5)]
    for left, right in pairs:
        _same(organization, assertion, left, right)

    asked = [left for left, _ in pairs]
    with django_assert_num_queries(2):
        identity.component_refs(organization, asked)


@pytest.mark.django_db(transaction=True)
def test_an_unknown_node_is_still_answerable(organization: Organization) -> None:
    """A ref naming nothing is a component of one, not an error.

    `component_refs` is a fold lookup, not an existence check — the caller has
    already resolved and authorized whatever it is asking about.
    """
    missing = str(uuid.uuid4())
    assert identity.component_refs(organization, [missing]) == {missing: [missing]}
