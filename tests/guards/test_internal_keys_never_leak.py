"""Engine-internal node properties must never reach the public `properties` field.

The projection layer writes bookkeeping onto entity nodes under a `__` prefix
(`__schema_version`, `__last_derived`, `__measured__from|to|at`, `__shadow_link_id`).
`RESERVED_PROPERTY_KEYS` used to list the *unprefixed* spellings of two of those plus
a typo (`lyfecyle_status`), so every one of them leaked through `cleaned_properties`
into the GraphQL `properties` scalar.

`__lifecycle_state` is kept in the list below even though **no vertex carries one
any more** — the graph holds only what exists, so a flag beside a vertex would say
nothing its presence did not. The `from_row` family still synthesizes the key when
adapting an evidence row to the node surface, and it must go on being filtered out
of the public map.

These tests need no database and no docker stack.
"""

from graph_engine import retrieved
from graph_engine.retrieved import RetrievedNode, is_internal_property_key

# Every internal key the write path actually emits. Sourced from
# GraphController._recalculate_entity and the relation write path.
WRITTEN_INTERNAL_KEYS = [
    "__schema_version",
    "__last_derived",
    "__lifecycle_state",
    "__measured__from",
    "__measured__to",
    "__measured__at",
    "__shadow_link_id",
]


def _entity(properties: dict) -> RetrievedNode:
    return RetrievedNode(
        controller=None,  # type: ignore[arg-type]
        graph_name="testgraph",
        vertex_id=1,
        label="AIS",
        properties=properties,
    )


def test_written_internal_keys_are_classified_internal() -> None:
    """Every key the projection writes must be recognised as internal."""
    for key in WRITTEN_INTERNAL_KEYS:
        assert is_internal_property_key(key), f"{key} is written by the projection but not filtered"


def test_cleaned_properties_hides_every_written_internal_key() -> None:
    """None of the internal keys may survive into the public property dict."""
    props = {key: "internal" for key in WRITTEN_INTERNAL_KEYS}
    props["avg_length"] = 45.2

    cleaned = _entity(props).cleaned_properties

    assert cleaned == {"avg_length": 45.2}


def test_cleaned_properties_keeps_user_data() -> None:
    """Filtering internals must not drop legitimate user properties."""
    cleaned = _entity({"avg_length": 45.2, "name": "AIS_1", "count": 3}).cleaned_properties

    assert cleaned == {"avg_length": 45.2, "name": "AIS_1", "count": 3}


def test_identity_keys_are_still_reserved() -> None:
    """The named (unprefixed) reserved keys must keep being filtered."""
    props = {key: "x" for key in retrieved.RESERVED_PROPERTY_KEYS}
    props["real"] = 1

    assert _entity(props).cleaned_properties == {"real": 1}


def test_a_new_internal_key_needs_no_registration() -> None:
    """The point of the prefix rule: future `__` keys are excluded automatically."""
    assert is_internal_property_key("__some_future_projection_key")
    assert _entity({"__some_future_projection_key": 1, "real": 2}).cleaned_properties == {"real": 2}


def test_user_key_beginning_with_single_underscore_is_not_filtered() -> None:
    """Only the `__` prefix is reserved; a single underscore is legitimate user data."""
    assert not is_internal_property_key("_private_but_users")
    assert _entity({"_private_but_users": 1}).cleaned_properties == {"_private_but_users": 1}


def test_rich_property_definition_resolves_from_the_category_schema() -> None:
    """RichProperty.definition must return the schema definition for its key.

    It previously called `.filter(name=...)` on `property_definitions`, which is a JSON
    list rather than a related manager, so this resolver raised AttributeError for every
    property. `richProperties` had no coverage at any of its four call sites.
    """
    import asyncio

    from api.types import PropertyDefinition, RichProperty
    from core import models as core_models
    from graph_engine import input_models as im

    definitions = [
        im.PropertyDefinitionInput(key="avg_length", type=im.PropertyType.FLOAT),
        im.PropertyDefinitionInput(key="name", type=im.PropertyType.STRING),
    ]
    # Unsaved instance: property_map reads the JSON field, so no database is involved.
    category = core_models.EntityCategory(property_definitions=[d.model_dump(mode="json") for d in definitions])

    entity = _entity({"avg_length": 45.2})
    prop = RichProperty(_entity=entity, _key="avg_length", _category=category)

    resolved = asyncio.run(prop.definition())

    assert isinstance(resolved, PropertyDefinition)
    assert resolved.key == "avg_length"


def test_rich_property_definition_is_none_for_an_undeclared_key() -> None:
    """A property present on the node but absent from the schema resolves to None."""
    import asyncio

    from api.types import RichProperty
    from core import models as core_models

    category = core_models.EntityCategory(property_definitions=[])
    prop = RichProperty(_entity=_entity({"stray": 1}), _key="stray", _category=category)

    assert asyncio.run(prop.definition()) is None
