import pytest
from types import SimpleNamespace

from api import context as api_context
from graph_engine import input_models
from graph_engine.materialize import materialize


@pytest.mark.django_db(transaction=True)
def test_can_perform_action_from_graph_rules(test_graph, authenticated_context) -> None:
    request = authenticated_context.request
    info = SimpleNamespace(context=authenticated_context)

    test_graph.rules = [
        {
            "action": "AUTO_ADD_STRUCTURES",
            "allow": False,
            "filter": {"user_id": str(request._user.id)},
        }
    ]
    test_graph.save(update_fields=["rules"])

    assert test_graph.can_perform_action(info, "AUTO_ADD_STRUCTURES") is False
    assert test_graph.can_perform_action(info, "AUTO_ADD_METRICS") is True


@pytest.mark.django_db(transaction=True)
def test_materialize_persists_rules_from_definition(age_engine, bio_graph_schema, authenticated_context) -> None:
    request = authenticated_context.request

    definition = bio_graph_schema.model_copy(deep=True)
    definition.rules = [
        input_models.ActionRuleInput(
            action=input_models.Action.AUTO_ADD_STRUCTURES,
            allow=False,
            filter=input_models.ActionFilterInput(user_id=str(request._user.id)),
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
