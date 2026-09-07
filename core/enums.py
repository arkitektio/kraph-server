from django.db.models import TextChoices
import strawberry
from enum import Enum


class CategoryKindChoices(TextChoices):
    """Which kind of category a `core.Category` row is.

    Categories used to be a multi-table inheritance chain. They are now one table
    and this field is what tells the rows apart -- for the proxy managers, for the
    GraphQL `is_type_of` resolution, and for every `filter(kind=...)` in between.
    """

    ENTITY = "ENTITY"
    REAGENT = "REAGENT"
    NATURAL_EVENT = "NATURAL_EVENT"
    PROTOCOL_EVENT = "PROTOCOL_EVENT"
    MEASUREMENT = "MEASUREMENT"
    RELATION = "RELATION"
    STRUCTURE_RELATION = "STRUCTURE_RELATION"


#: The category kinds that are nodes in the graph (the former `NodeCategory` subtree).
NODE_CATEGORY_KINDS = (
    CategoryKindChoices.ENTITY,
    CategoryKindChoices.REAGENT,
    CategoryKindChoices.NATURAL_EVENT,
    CategoryKindChoices.PROTOCOL_EVENT,
)

#: The category kinds that are edges in the graph (the former `EdgeCategory` subtree).
EDGE_CATEGORY_KINDS = (
    CategoryKindChoices.MEASUREMENT,
    CategoryKindChoices.RELATION,
    CategoryKindChoices.STRUCTURE_RELATION,
)


class GraphQueryKindChoices(TextChoices):
    """Which shape of result a saved graph query returns.

    Only `TABLE` now. `NODES`, `PATH` and `PAIRS` — and the whole `NodeQuery` /
    `EdgeQuery` families — had mutations, types and filters but no execution path
    anywhere: nothing could ever render one. They went with the saved-query
    contract becoming a plan (`graph_engine/query_ir.py`); a new shape comes
    back as a plan kind, not as a stored query string.
    """

    TABLE = "TABLE"


class MetricKindChoices(TextChoices):
    INT = "INT"
    FLOAT = "FLOAT"
    DATETIME = "DATETIME"
    STRING = "STRING"
    CATEGORY = "CATEGORY"
    BOOLEAN = "BOOLEAN"
    THREE_D_VECTOR = "THREE_D_VECTOR"
    TWO_D_VECTOR = "TWO_D_VECTOR"
    ONE_D_VECTOR = "ONE_D_VECTOR"
    FOUR_D_VECTOR = "FOUR_D_VECTOR"
    N_VECTOR = "N_VECTOR"


class ProtocolStepKindChoices(TextChoices):
    """Variety expresses the Type of Representation we are dealing with"""

    PREPERATION = "PREP"
    ADD_REAGENT = "ADD_REAGENT"
    MEASUREMENT = "MEASUREMENT"
    STORAGE = "STORAGE"
    CUSTOM = "CUSTOM"
    UNKNOWN = "UNKNOWN"


@strawberry.enum
class ProtocolStepKind(str, Enum):
    """Variety expresses the Type of Representation we are dealing with"""

    PREPERATION = "PREP"
    ADD_REAGENT = "ADD_REAGENT"
    MEASUREMENT = "MEASUREMENT"
    ANALYSIS = "ANALYSIS"
    STORAGE = "STORAGE"
    CUSTOM = "CUSTOM"
    UNKNOWN = "UNKNOWN"


@strawberry.enum
class TermKind(str, Enum):
    """What sort of thing one of the organization's words names.

    Deliberately the same members as `CategoryKindChoices`, because a `Term` and a
    `Category` for it are the same sort of thing seen from two sides — the word,
    and one view's rule for the word. Kept as a separate strawberry enum because
    `CategoryKindChoices` is a Django `TextChoices` and is not exposed to GraphQL;
    the two are checked against each other by `test_term_kinds_match_category_kinds`.

    It is part of a term's identity: "AIS" as an entity and "AIS" as a relation
    are different words that happen to be spelled alike.
    """

    ENTITY = "ENTITY"
    REAGENT = "REAGENT"
    NATURAL_EVENT = "NATURAL_EVENT"
    PROTOCOL_EVENT = "PROTOCOL_EVENT"
    MEASUREMENT = "MEASUREMENT"
    RELATION = "RELATION"
    STRUCTURE_RELATION = "STRUCTURE_RELATION"


#: Which word-kind a node's claims are stated in, keyed by `evidence.Node.Kind`.
#:
#: The two vocabularies are deliberately separate — `Instance.Kind` is lowercase, has
#: three members, and says what sort of row this is; `CategoryKindChoices` is
#: uppercase, has seven, and says what sort of thing a word names. A write needs
#: both, and `classify_nodes` needs to go from the row it was handed to the kind of
#: word it may claim. Total over `Instance.Kind`, so there is no default to get wrong;
#: `REAGENT` has no node kind and so cannot be reached from here, which matches the
#: fact that nothing mints reagent instances.
TERM_KIND_FOR_NODE_KIND: dict[str, str] = {
    "entity": CategoryKindChoices.ENTITY.value,
    "natural_event": CategoryKindChoices.NATURAL_EVENT.value,
    "protocol_event": CategoryKindChoices.PROTOCOL_EVENT.value,
}


@strawberry.enum
class InstanceKind(str, Enum):
    """What sort of individual an `evidence.Instance` is.

    A separate strawberry enum from `Instance.Kind`, for the same reason `TermKind`
    is separate from `CategoryKindChoices`: the Django `TextChoices` stores
    **lowercase** values and is not exposed to GraphQL, while a GraphQL enum is
    conventionally uppercase. `test_instance_kinds_match_the_model` holds the two
    together.

    Three members, and no `REAGENT`: nothing mints a reagent instance, which is why
    `TERM_KIND_FOR_NODE_KIND` above cannot reach that word kind either.
    """

    ENTITY = "ENTITY"
    NATURAL_EVENT = "NATURAL_EVENT"
    PROTOCOL_EVENT = "PROTOCOL_EVENT"


@strawberry.enum
class LinkKind(str, Enum):
    """What an `evidence.Link` claims — and therefore what its two refs point at.

    The refs are opaque strings by design, so `kind` is the only thing that says
    which end is which; `api/types.py::Link.source` reads exactly this to decide.
    Uppercase mirror of `Link.Kind`, held to it by
    `test_link_kinds_match_the_model`.
    """

    INFORMS = "INFORMS"
    RELATION = "RELATION"
    STRUCTURE_RELATION = "STRUCTURE_RELATION"
    MEASUREMENT = "MEASUREMENT"
    PARTICIPATES_AS_INPUT = "PARTICIPATES_AS_INPUT"
    PARTICIPATES_AS_OUTPUT = "PARTICIPATES_AS_OUTPUT"
    CLASSIFIES = "CLASSIFIES"
    SAME_AS = "SAME_AS"
    DIFFERENT_FROM = "DIFFERENT_FROM"
    DERIVED_FROM = "DERIVED_FROM"


@strawberry.enum
class ValueKind(str, Enum):
    INT = "INT"
    FLOAT = "FLOAT"
    DATETIME = "DATETIME"
    STRING = "STRING"
    CATEGORY = "CATEGORY"
    BOOLEAN = "BOOLEAN"
    THREE_D_VECTOR = "THREE_D_VECTOR"
    TWO_D_VECTOR = "TWO_D_VECTOR"
    ONE_D_VECTOR = "ONE_D_VECTOR"
    FOUR_D_VECTOR = "FOUR_D_VECTOR"
    N_VECTOR = "N_VECTOR"


@strawberry.enum
@strawberry.enum
class ChangeKind(str, Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    IMPORT = "IMPORT"


@strawberry.enum
class OrderDirection(str, Enum):
    ASC = "ASC"
    DESC = "DESC"


@strawberry.enum(description="The kind of a comment descendant — how one node of the rich-text tree renders")
class DescendantKind(str, Enum):
    """One node of a comment's rich-text tree.

    The same three kinds `lok`'s komment app renders, kept value-compatible so a
    client (or lok itself) can post the identical tree here: a PARAGRAPH holds
    children, a LEAF holds styled text and ends a branch, a MENTION names a
    subject — the same string `Assertion.subject` carries, because the evidence
    layer knows actors by subject id and never by a user row.
    """

    LEAF = "LEAF"
    MENTION = "MENTION"
    PARAGRAPH = "PARAGRAPH"
