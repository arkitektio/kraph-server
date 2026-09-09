"""Engine-internal vertex properties never reach the public `properties` field (C4).

The projection writes bookkeeping onto vertices under a `__` prefix
(`__schema_version`, `__last_derived`, `__measured__from|to|at`,
`__shadow_link_id`); `cleaned_properties` strips every one of them. There is no
state flag among them: the graph holds only what exists (C7), so a flag beside
a vertex would say nothing its presence did not.

No database, no docker stack.

History: `RESERVED_PROPERTY_KEYS` used to list the *unprefixed* spellings of
two of those plus a typo (`lyfecyle_status`), so every one leaked. The list
also reserved a `__lifecycle_state` key long after no vertex carried one.
"""

from graph_engine import retrieved
from graph_engine.retrieved import is_internal_property_key
from tests.support import reads


WRITTEN_INTERNAL_KEYS = [
    "__schema_version",
    "__last_derived",
    "__measured__from",
    "__measured__to",
    "__measured__at",
    "__shadow_link_id",
]
def test_written_internal_keys_are_classified_internal() -> None:
    """Every key the projection writes must be recognised as internal."""
    for key in WRITTEN_INTERNAL_KEYS:
        assert is_internal_property_key(key), f"{key} is written by the projection but not filtered"
def test_cleaned_properties_hides_every_written_internal_key() -> None:
    """None of the internal keys may survive into the public property dict."""
    props = {key: "internal" for key in WRITTEN_INTERNAL_KEYS}
    props["avg_length"] = 45.2

    cleaned = reads.retrieved_node(props).cleaned_properties

    assert cleaned == {"avg_length": 45.2}
def test_cleaned_properties_keeps_user_data() -> None:
    """Filtering internals must not drop legitimate user properties."""
    cleaned = reads.retrieved_node({"avg_length": 45.2, "name": "AIS_1", "count": 3}).cleaned_properties

    assert cleaned == {"avg_length": 45.2, "name": "AIS_1", "count": 3}
def test_identity_keys_are_still_reserved() -> None:
    """The named (unprefixed) reserved keys must keep being filtered."""
    props = {key: "x" for key in retrieved.RESERVED_PROPERTY_KEYS}
    props["real"] = 1

    assert reads.retrieved_node(props).cleaned_properties == {"real": 1}
def test_a_new_internal_key_needs_no_registration() -> None:
    """The point of the prefix rule: future `__` keys are excluded automatically."""
    assert is_internal_property_key("__some_future_projection_key")
    assert reads.retrieved_node({"__some_future_projection_key": 1, "real": 2}).cleaned_properties == {"real": 2}
def test_user_key_beginning_with_single_underscore_is_not_filtered() -> None:
    """Only the `__` prefix is reserved; a single underscore is legitimate user data."""
    assert not is_internal_property_key("_private_but_users")
    assert reads.retrieved_node({"_private_but_users": 1}).cleaned_properties == {"_private_but_users": 1}
