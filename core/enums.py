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
    """Which shape of result a saved graph query returns."""

    NODES = "NODES"
    PATH = "PATH"
    PAIRS = "PAIRS"
    TABLE = "TABLE"


class NodeQueryKindChoices(TextChoices):
    """Which shape of result a saved node query returns."""

    PATH = "PATH"
    PAIRS = "PAIRS"
    TABLE = "TABLE"


class EdgeQueryKindChoices(TextChoices):
    """Which shape of result a saved edge query returns."""

    PATH = "PATH"
    PAIRS = "PAIRS"
    TABLE = "TABLE"


class MaterializedEdgeKindChoices(TextChoices):
    """Which kind of category a materialized edge was derived from."""

    RELATION = "RELATION"
    MEASUREMENT = "MEASUREMENT"
    STRUCTURE_RELATION = "STRUCTURE_RELATION"


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
#: The two vocabularies are deliberately separate — `Node.Kind` is lowercase, has
#: three members, and says what sort of row this is; `CategoryKindChoices` is
#: uppercase, has seven, and says what sort of thing a word names. A write needs
#: both, and `classify_nodes` needs to go from the row it was handed to the kind of
#: word it may claim. Total over `Node.Kind`, so there is no default to get wrong;
#: `REAGENT` has no node kind and so cannot be reached from here, which matches the
#: fact that nothing mints reagent instances.
TERM_KIND_FOR_NODE_KIND: dict[str, str] = {
    "entity": CategoryKindChoices.ENTITY.value,
    "natural_event": CategoryKindChoices.NATURAL_EVENT.value,
    "protocol_event": CategoryKindChoices.PROTOCOL_EVENT.value,
}


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
class WhereOperator(str, Enum):
    EQUALS = "EQUALS"
    NOT_EQUALS = "NOT_EQUALS"
    GREATER_THAN = "GREATER_THAN"
    LESS_THAN = "LESS_THAN"
    GREATER_THAN_OR_EQUAL = "GREATER_THAN_OR_EQUAL"
    LESS_THAN_OR_EQUAL = "LESS_THAN_OR_EQUAL"
    CONTAINS = "CONTAINS"
    STARTS_WITH = "STARTS_WITH"
    ENDS_WITH = "ENDS_WITH"


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
