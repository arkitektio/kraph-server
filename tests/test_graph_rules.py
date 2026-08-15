"""Action rules on a graph, and what a rule's filter can actually say.

Both rules below used to carry `filter={"user_id": ...}`. `ActionFilterInput` has
no such field and never has — `can_perform_action`'s own comment is emphatic that
roles and scopes are the only things extracted — so pydantic dropped the key and
the filter matched *everything*. The first test then passed for the wrong reason:
`allow=False` denied the action for every caller, not for the named user, and the
assertion could not tell the two apart. `StrictModel` refuses the key now, which
is what surfaced it.

Filtering by user is not the thing being tested here and is not a feature this
model offers; these test that a deny rule is honoured and that rules survive
materialization. So they say that with a filter the model has.
"""

import pytest
from types import SimpleNamespace

from api import context as api_context
from graph_engine import input_models
from graph_engine.materialize import materialize


@pytest.mark.django_db(transaction=True)
def test_can_perform_action_from_graph_rules(test_graph, authenticated_context) -> None:
    info = SimpleNamespace(context=authenticated_context)

    test_graph.rules = [
        {
            "action": "AUTO_ADD_STRUCTURES",
            "allow": False,
            "filter": {},
        }
    ]
    test_graph.save(update_fields=["rules"])

    assert test_graph.can_perform_action(info, "AUTO_ADD_STRUCTURES") is False
    assert test_graph.can_perform_action(info, "AUTO_ADD_METRICS") is True


@pytest.mark.django_db(transaction=True)
def test_a_rule_filtered_to_a_role_the_caller_lacks_does_not_fire(test_graph, authenticated_context) -> None:
    """The half the `user_id` spelling was reaching for, said in the supported way.

    Without this, nothing distinguishes "the filter matched" from "the filter was
    ignored" — which is exactly how the dropped `user_id` key went unnoticed.
    """
    info = SimpleNamespace(context=authenticated_context)

    test_graph.rules = [
        {
            "action": "AUTO_ADD_STRUCTURES",
            "allow": False,
            "filter": {"required_roles": ["a-role-nobody-here-has"]},
        }
    ]
    test_graph.save(update_fields=["rules"])

    assert test_graph.can_perform_action(info, "AUTO_ADD_STRUCTURES") is True, "A rule whose filter does not match the request must not apply"


@pytest.mark.django_db(transaction=True)
def test_materialize_persists_rules_from_definition(age_engine, bio_graph_schema, authenticated_context) -> None:
    request = authenticated_context.request

    definition = bio_graph_schema.model_copy(deep=True)
    definition.rules = [
        input_models.ActionRuleInput(
            action=input_models.Action.AUTO_ADD_STRUCTURES,
            allow=False,
            filter=input_models.ActionFilterInput(required_scopes=["write"]),
        )
    ]

    graph = materialize(
        definition=definition,
        engine=age_engine,
        user=request._user,
        organization=request._organization,
        membership=request.membership,
        name="rules_graph",
        description="graph with action rules",
    )

    assert isinstance(graph.rules, list)
    assert graph.rules[0]["action"] == "AUTO_ADD_STRUCTURES"
    assert graph.rules[0]["allow"] is False


@pytest.mark.django_db(transaction=True)
def test_get_accessible_graph_checks_requested_actions(test_graph, authenticated_context) -> None:
    test_graph.rules = [
        {
            "action": "CREATE_BUILDER_ARG",
            "allow": False,
        }
    ]
    test_graph.save(update_fields=["rules"])

    info = SimpleNamespace(context=authenticated_context)

    with pytest.raises(PermissionError):
        api_context.get_accessible_graph(
            info,
            str(test_graph.id),
            actions=[input_models.Action.CREATE_BUILDER_ARG],
        )
