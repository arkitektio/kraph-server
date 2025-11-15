from contextlib import contextmanager, asynccontextmanager
import datetime
import json
from unicodedata import category
from django.db import connections
from core import models
from dataclasses import dataclass
from core import filters, pagination
import typing
from core.pagination import GraphPaginationInput
from core.utils import get_now_epoch_millis, translate_to_epoch_millis, from_epoch_millis
from pydantic import BaseModel, Field
import strawberry
from enum import Enum
from typing import Any


if typing.TYPE_CHECKING:
    from core import models, filters, pagination, inputs


class ProtocolInEdge(BaseModel):
    source: int
    role: str
    quantity: float | None = None


class ProtocolOutEdge(BaseModel):
    target: int
    role: str
    quantity: float | None = None


class ProvenanceAction(str, Enum):
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    CREATE = "CREATE"


@dataclass
class ProvenanceLog:
    action: ProvenanceAction
    user: str
    client: str
    assignation: str
    before_value: str
    after_value: str


@dataclass
class RetrievedVariable:
    log: list[ProvenanceLog]
    value: Any
    key: str


RESERVED_KEYWORDS = ["sequence", "type", "category_id", "created_at", "id", "labels", "category_type"]


@dataclass
class RetrievedEntity:
    graph_name: str
    id: int
    kind_age_name: str | None
    properties: dict[str, str] | None
    cached_relations: list["RetrievedRelation"] | None = None

    def retrieve_relations(self) -> "RetrievedRelation":
        """Retrieve all relations for this entity from the age database

        This includes both left and right relations."""
        return self.cached_relations or get_age_relations(self.graph_name, self.id)

    def retrieve_right_relations(self) -> "RetrievedRelation":
        """Retrieve all right relations for this entity from the age database"""
        return get_right_relations(self.graph_name, self.id)

    def retrieve_left_relations(self) -> "RetrievedRelation":
        """ " Retrieve all left relations for this entity from the age database"""
        return get_left_relations(self.graph_name, self.id)

    @property
    def label(self):
        return self.properties.get("label", self.kind_age_name + " - " + str(self.id))

    @property
    def valid_from(self):
        valid_from = self.properties.get("valid_from", None)
        if valid_from:
            return from_epoch_millis(valid_from)
        return None

    @property
    def created_by(self):
        return self.properties.get("created_by", None)

    @property
    def created_app(self):
        return self.properties.get("created_app", None)

    @property
    def created_through(self):
        return self.properties.get("created_through", None)

    @property
    def pinned_by(self):
        return self.properties.get("pinned_by", [])

    @property
    def tags(self):
        return self.properties.get("tags", None)

    @property
    def cleaned_properties(self):
        return {key: value for key, value in self.properties.items() if key not in RESERVED_KEYWORDS}

    def get_variable(self, key) -> RetrievedVariable:
        value = self.cleaned_properties.get(key, None)

        return RetrievedVariable(value=value, key=key, log=[])

    def get_all_properties(self) -> list[RetrievedVariable]:
        return [RetrievedVariable(value=value, key=key, log=[]) for key, value in self.cleaned_properties.items()]

    @property
    def variables(self):
        return [{"role": key[len("variable_") :], "value": value} for key, value in self.properties.items() if key.startswith("variable_")]

    @property
    def local_id(self):
        return self.properties.get("sequence", None)

    @property
    def value(self):
        return self.properties.get("value", None)

    @property
    def external_id(self):
        return self.properties.get("external_id", None)

    @property
    def category_type(
        self,
    ) -> typing.Literal["ENTITY", "STRUCTURE", "NATURAL_EVENT", "PROTOCOL_EVENT", "REAGENT", "METRIC"]:
        return self.properties.get("type", None)

    @property
    def category_id(self) -> str:
        return self.properties["category_id"]

    @property
    def valid_to(self):
        valid_to = self.properties.get("valid_to", None)
        if valid_to:
            return from_epoch_millis(valid_to)
        return None

    @property
    def created_at(self):
        created_at = self.properties.get("created_at", None)
        if created_at:
            return from_epoch_millis(created_at)
        return None

    @property
    def valid_relative_from(self):
        return self.properties.get("valid_relative_from", None)

    @property
    def valid_relative_to(self):
        return self.properties.get("valid_relative_to", None)

    @property
    def object(self):
        return self.properties.get("object", None)

    @property
    def identifier(self):
        return self.properties.get("identifier", None)

    @property
    def unique_id(self):
        return f"{self.graph_name}:{self.id}"

    def retrieve_properties(self):
        return {key: value for key, value in self.cleaned_properties.items() if key != "id" and key != "labels"}


@dataclass
class RetrievedRelation:
    graph_name: str
    id: int
    kind_age_name: str | None
    left_id: int
    right_id: int
    properties: dict[str, str] | None

    def retrieve_left(self) -> "RetrievedEntity":
        return get_age_entity(self.graph_name, self.left_id)

    def retrieve_right(self) -> "RetrievedEntity":
        return get_age_entity(self.graph_name, self.right_id)

    @property
    def category_type(
        self,
    ) -> typing.Literal["MEASUREMENT", "RELATION", "PARTICIPANT", "DESCRIPTION", "EDITED"]:
        return self.properties.get("type", None)

    @property
    def category_id(self) -> str:
        return self.properties.get("category_id", None)

    @property
    def value(self):
        return self.properties.get("value", None)

    @property
    def label(self):
        return self.properties.get("label", self.kind_age_name + " - " + str(self.id))

    @property
    def valid_from(self):
        return self.properties.get("valid_from", None)

    @property
    def valid_to(self):
        return self.properties.get("valid_to", None)

    @property
    def role(self):
        return self.properties.get("role", None)

    @property
    def quantity(self):
        return self.properties.get("quantity", None)

    @property
    def valid_relative_from(self):
        return self.properties.get("valid_relative_from", None)

    @property
    def valid_relative_to(self):
        return self.properties.get("valid_relative_to", None)

    @property
    def unique_left_id(self):
        return f"{self.graph_name}:{self.left_id}"

    @property
    def unique_right_id(self):
        return f"{self.graph_name}:{self.right_id}"

    @property
    def unique_id(self):
        return f"{self.graph_name}:{self.id}"


@contextmanager
def graph_cursor():
    with connections["default"].cursor() as cursor:
        cursor.execute("LOAD 'age';")
        cursor.execute('SET search_path = ag_catalog, "$user", public')

        print(f"Creating new graph cursor. Use this to support AGE queries.")
        yield cursor
        print(f"Closing graph cursor.")


def create_age_graph(name: str):
    with graph_cursor() as cursor:
        cursor.execute("SELECT EXISTS(SELECT 1 FROM ag_catalog.ag_graph WHERE name = %s);", [name])
        exists = cursor.fetchone()[0]
        if exists:
            return exists
        else:
            cursor.execute("SELECT create_graph(%s);", [name])
            print(cursor.fetchone())


def delete_age_graph(name: str):
    with graph_cursor() as cursor:
        cursor.execute("SELECT drop_graph(%s, true);", [name])
        print(cursor.fetchone())


def create_age_entity_kind(category: "models.EntityCategory"):
    with graph_cursor() as cursor:
        try:
            cursor.execute(
                "SELECT create_vlabel(%s, %s);",
                (category.graph.age_name, category.get_age_vertex_name()),
            )
            print(cursor.fetchone())
        except Exception as e:
            print(e)


def create_age_relation_kind(category: "models.RelationCategory"):
    with graph_cursor() as cursor:
        try:
            cursor.execute(
                "SELECT create_elabel(%s, %s);",
                (category.graph.age_name, category.get_age_vertex_name()),
            )
            print(cursor.fetchone())
        except Exception as e:
            print(e)


def create_age_structure_kind(category: "models.StructureCategory"):
    with graph_cursor() as cursor:
        try:
            cursor.execute(
                "SELECT create_vlabel(%s, %s);",
                (category.graph.age_name, category.get_age_vertex_name()),
            )
            print(cursor.fetchone())
        except Exception as e:
            print(e)


def create_age_natural_event_kind(category: "models.NaturalEventCategory"):
    with graph_cursor() as cursor:
        try:
            cursor.execute(
                "SELECT create_vlabel(%s, %s);",
                (category.graph.age_name, category.get_age_vertex_name()),
            )
            print(cursor.fetchone())
        except Exception as e:
            print(e)

        for role in category.collected_in_role_vertex_name:
            try:
                cursor.execute(
                    "SELECT create_elabel(%s, %s);",
                    (category.graph.age_name, category.get_inrole_vertex_name(role)),
                )
                print(cursor.fetchone())
            except Exception as e:
                print(e)
        for role in category.collected_in_role_vertex_name:
            try:
                cursor.execute(
                    "SELECT create_elabel(%s, %s);",
                    (category.graph.age_name, category.get_outrole_vertex_name(role)),
                )
                print(cursor.fetchone())
            except Exception as e:
                print(e)


def create_age_protocol_event_kind(category: "models.ProtocolEventCategory"):
    with graph_cursor() as cursor:
        try:
            cursor.execute(
                "SELECT create_vlabel(%s, %s);",
                (category.graph.age_name, category.get_age_vertex_name()),
            )
            print(cursor.fetchone())
        except Exception as e:
            print(e)

        for role in category.collected_in_role_vertex_name:
            try:
                cursor.execute(
                    "SELECT create_elabel(%s, %s);",
                    (category.graph.age_name, category.get_inrole_vertex_name(role)),
                )
                print(cursor.fetchone())
            except Exception as e:
                print(e)
        for role in category.collected_in_role_vertex_name:
            try:
                cursor.execute(
                    "SELECT create_elabel(%s, %s);",
                    (category.graph.age_name, category.get_outrole_vertex_name(role)),
                )
                print(cursor.fetchone())
            except Exception as e:
                print(e)


def create_age_metric_kind(category: "models.MetricCategory"):
    with graph_cursor() as cursor:
        try:
            cursor.execute(
                "SELECT create_vlabel(%s, %s);",
                (category.graph.age_name, category.get_age_vertex_name()),
            )
            print(cursor.fetchone())
        except Exception as e:
            print(e)


def create_age_reagent_kind(category: "models.ReagentCategory"):
    with graph_cursor() as cursor:
        try:
            cursor.execute(
                "SELECT create_vlabel(%s, %s);",
                (category.graph.age_name, category.get_age_vertex_name()),
            )
            print(cursor.fetchone())
        except Exception as e:
            print(e)


def create_age_measurement_kind(category: "models.MeasurementCategory"):
    with graph_cursor() as cursor:
        try:
            cursor.execute(
                "SELECT create_elabel(%s, %s);",
                (category.graph.age_name, category.get_age_vertex_name()),
            )
            print(cursor.fetchone())
        except Exception as e:
            print(e)


def create_age_relation_kind(category: "models.RelationCategory"):
    with graph_cursor() as cursor:
        try:
            cursor.execute(
                "SELECT create_elabel(%s, %s);",
                (category.graph.age_name, category.get_age_vertex_name()),
            )
            print(cursor.fetchone())
        except Exception as e:
            print(e)


def vertex_ag_to_retrieved_entity(graph_name, vertex):
    trimmed_vertex = vertex.replace("::vertex", "")
    print("timmed neighbour", trimmed_vertex)

    parsed_vertex = json.loads(trimmed_vertex)
    return RetrievedEntity(
        graph_name=graph_name,
        id=parsed_vertex["id"],
        kind_age_name=parsed_vertex["label"],
        properties=parsed_vertex["properties"],
    )


def edge_ag_to_retrieved_relation(graph_name, edge):
    trimmed_relationship = edge.replace("::edge", "")
    print("timmed", trimmed_relationship)
    parsed_relationship = json.loads(trimmed_relationship)
    return RetrievedRelation(
        graph_name=graph_name,
        id=parsed_relationship["id"],
        kind_age_name=parsed_relationship["label"],
        left_id=parsed_relationship["start_id"],
        right_id=parsed_relationship["end_id"],
        properties=parsed_relationship["properties"],
    )


def edge_ag_to_retrieved_metric(graph_name, edge):
    trimmed_relationship = edge.replace("::edge", "")
    print("timmed", trimmed_relationship)
    parsed_relationship = json.loads(trimmed_relationship)
    return RetrievedNodeMetric(
        graph_name=graph_name,
        id=parsed_relationship["id"],
        kind_age_name=parsed_relationship["label"],
        properties=parsed_relationship["properties"],
    )


def select_latest_entities(graph_name, category_id, limit=5):
    with graph_cursor() as cursor:
        cursor.execute(
            """
            SELECT * 
            FROM cypher(%s, $$
                MATCH (n)
                WHERE n.category_id = %s
                RETURN n
                ORDER BY n.created_at DESC
                LIMIT %s
            $$) as (n agtype);
            """,
            [graph_name, category_id, limit],
        )

        results = cursor.fetchall()
        print("Thre results", results)

        nodes: list[RetrievedEntity] = []

        for result in results:
            print(result)
            entity = result[0]
            if entity:
                nodes.append(vertex_ag_to_retrieved_entity(graph_name, entity))

        print(nodes)
        return nodes


def get_neighbors_and_edges(graph_name, node_id):
    with graph_cursor() as cursor:
        print(graph_name, int(node_id))
        cursor.execute(
            """
            SELECT * 
            FROM cypher(%s, $$
                MATCH (n)-[r]-(neighbor)
                WHERE id(n) = %s AND id(neighbor) <> id(n)
                RETURN DISTINCT r, neighbor 
            $$) as (relationship agtype, neighbor agtype);
            """,
            [graph_name, int(node_id)],
        )

        results = cursor.fetchall()
        print("Thre results", results)

        nodes: list[RetrievedEntity] = []
        relation_ships: list[RetrievedRelation] = []

        for result in results:
            print(result)
            relationship = result[0]  # Edge connecting the nodes
            neighbour = result[1]  # Starting node

            if neighbour:
                nodes.append(vertex_ag_to_retrieved_entity(graph_name, neighbour))

            if relationship:
                relation_ships.append(edge_ag_to_retrieved_relation(graph_name, relationship))

        print(nodes, relation_ships)
        return nodes, relation_ships


def create_age_entity(
    category: "models.EntityCategory",
    name: str | None = None,
    external_id: str | None = None,
) -> RetrievedEntity:
    with graph_cursor() as cursor:
        if external_id:
            # Try to find existing reagent first
            cursor.execute(
                f"""
            SELECT * 
            FROM cypher(%s, $$
                MATCH (n:{category.get_age_vertex_name()} {{type: "ENTITY", category_id: %s, category_type: %s}}) 
                WHERE n.external_id = %s
                SET n.label = %s
                SET n.created_at = %s
                RETURN n
            $$) as (n agtype);
            """,
                (
                    category.graph.age_name,
                    category.id,
                    category.get_age_type_name(),
                    external_id,
                    name,
                    datetime.datetime.now().isoformat(),
                ),
            )
            existing = cursor.fetchone()
            if existing:
                return vertex_ag_to_retrieved_entity(category.graph.age_name, existing[0])

        if category.sequence:
            sequence_name = category.sequence.ps_name
            cursor.execute(
                f"""
                SELECT nextval('{sequence_name}') AS seq_id;
                """,
            )
            seq_id = cursor.fetchone()[0]
        else:
            seq_id = None

        # Create new reagent if not found

        create_query = f"""
        SELECT * 
        FROM cypher(%s, $$
            CREATE (n:{category.get_age_vertex_name()} {{type: "ENTITY", category_id: %s,  category_type: %s, label: %s, created_at: %s, external_id: %s}})
            SET n.sequence = %s
            RETURN n
        $$) as (n agtype);"""

        print("create query", create_query)

        cursor.execute(
            create_query,
            (
                category.graph.age_name,
                category.id,
                category.get_age_type_name(),
                name,
                datetime.datetime.now().isoformat(),
                external_id,
                seq_id,
            ),
        )
        result = cursor.fetchone()
        if result:
            entity = result[0]
            return vertex_ag_to_retrieved_entity(category.graph.age_name, entity)
        else:
            raise ValueError("No entity created or returned by the query.")


def update_entity(graph: str, id: int, external_id: str | None = None, tags: list[str] | None = None, pinned_by: list[str] | None = None) -> RetrievedEntity:
    with graph_cursor() as cursor:
        # Try to find existing reagent first
        cursor.execute(
            f"""
            SELECT * 
            FROM cypher(%s, $$
                MATCH (n)
                WHERE id(n) = %s
                SET n.external_id = %s
                SET n.tags = %s
                SET n.pinned_by = %s
                RETURN n
            $$) as (n agtype);
            """,
            (graph, id, external_id, tags, pinned_by),
        )
        result = cursor.fetchone()
        if result:
            entity = result[0]
            return vertex_ag_to_retrieved_entity(graph, entity)
        else:
            raise ValueError("No entity updated or returned by the query.")


def create_age_reagent(
    category: "models.ReagentCategory",
    name: str | None = None,
    external_id: str | None = None,
) -> RetrievedEntity:
    with graph_cursor() as cursor:
        if external_id:
            # Try to find existing reagent first
            cursor.execute(
                f"""
            SELECT * 
            FROM cypher(%s, $$
                MATCH (n:{category.get_age_vertex_name()} {{type: "REAGENT", category_id: %s, category_type: %s}}) 
                WHERE n.external_id = %s
                SET n.label = %s
                SET n.created_at = %s
                RETURN n
            $$) as (n agtype);
            """,
                (
                    category.graph.age_name,
                    category.id,
                    category.get_age_type_name(),
                    external_id,
                    name,
                    datetime.datetime.now().isoformat(),
                ),
            )
            existing = cursor.fetchone()
            if existing:
                return vertex_ag_to_retrieved_entity(category.graph.age_name, existing[0])

        if category.sequence:
            sequence_name = category.sequence.ps_name
            cursor.execute(
                f"""
                SELECT nextval('{sequence_name}') AS seq_id;
                """,
            )
            seq_id = cursor.fetchone()[0]
        else:
            seq_id = None

        # Create new reagent if not found

        cursor.execute(
            f"""
            SELECT * 
            FROM cypher(%s, $$
                CREATE (n:{category.get_age_vertex_name()} {{type: "REAGENT", category_id: %s, category_type: %s, label: %s, created_at: %s, external_id: %s}})
                SET n.sequence = %s
                RETURN n
            $$) as (n agtype);
            """,
            (
                category.graph.age_name,
                category.id,
                category.get_age_type_name(),
                name,
                datetime.datetime.now().isoformat(),
                external_id,
                seq_id,
            ),
        )
        result = cursor.fetchone()
        if result:
            entity = result[0]
            return vertex_ag_to_retrieved_entity(category.graph.age_name, entity)
        else:
            raise ValueError("No entity created or returned by the query.")


def get_active_reagent_for_reagent_category(category: "models.ReagentCategory"):
    # get the active reagent for the category
    with graph_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT * 
            FROM cypher(%s, $$
                MATCH (n:{category.get_age_vertex_name()} {{type: "REAGENT", category_id: %s, category_type: %s}}) 
                WHERE n.active = true
                RETURN n
            $$) as (n agtype);
            """,
            (category.graph.age_name, category.id, category.get_age_type_name()),
        )
        result = cursor.fetchone()
        if result:
            entity = result[0]
            return vertex_ag_to_retrieved_entity(category.graph.age_name, entity)
        else:
            raise ValueError("No entity created or returned by the query.")


def set_as_active_reagent_for_category(category: "models.ReagentCategory", entity_id: str) -> RetrievedEntity:
    # unsert old active
    with graph_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT * 
            FROM cypher(%s, $$
                MATCH (n:{category.get_age_vertex_name()} {{type: "REAGENT", category_id: %s, category_type: %s}}) 
                WHERE n.active = true
                SET n.active = false
                RETURN n
            $$) as (n agtype);
            """,
            (category.graph.age_name, category.id, category.get_age_type_name()),
        )

    # set new active
    with graph_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT * 
            FROM cypher(%s, $$
                MATCH (n:{category.get_age_vertex_name()} {{type: "REAGENT", category_id: %s, category_type: %s}}) 
                WHERE id(n) = %s
                SET n.active = true
                RETURN n
            $$) as (n agtype);
            """,
            (
                category.graph.age_name,
                category.id,
                category.get_age_type_name(),
                int(entity_id),
            ),
        )
        result = cursor.fetchone()
        if result:
            entity = result[0]
            return vertex_ag_to_retrieved_entity(category.graph.age_name, entity)
        else:
            raise ValueError("No entity created or returned by the query.")


def create_age_protocol_event(
    category: "models.ProtocolEventCategory",
    name: str | None = None,
    external_id: str | None = None,
    valid_from: datetime.datetime | None = None,
    valid_to: datetime.datetime | None = None,
    variables: list["inputs.VariableMappingInput"] | None = None,
    user: str | None = None,
) -> RetrievedEntity:
    build_variable_setters = ""

    if variables:
        for i, variable in enumerate(variables):
            build_variable_setters += f"SET n.variable_{variable.key} = %s\n"

    with graph_cursor() as cursor:
        if external_id:
            # Try to find existing reagent first
            cursor.execute(
                f"""
            SELECT * 
            FROM cypher(%s, $$
                MATCH (n:{category.get_age_vertex_name()} {{type: "PROTOCOL_EVENT", category_id: %s, category_type: %s}}) 
                WHERE n.external_id = %s
                SET n.label = %s
                SET n.created_at = %s
                SET n.valid_from = %s
                SET n.valid_to = %s
                SET n.performed_by = %s
                {build_variable_setters}
                RETURN n
            $$) as (n agtype);
            """,
                tuple([category.graph.age_name, category.id, category.get_age_type_name(), external_id, name, datetime.datetime.now().isoformat(), valid_from.isoformat() if valid_from else None, valid_to.isoformat() if valid_to else None, user] + [variable.value for variable in variables]),
            )
            existing = cursor.fetchone()
            if existing:
                return vertex_ag_to_retrieved_entity(category.graph.age_name, existing[0])

        # Create new reagent if not found
        cursor.execute(
            f"""
            SELECT * 
            FROM cypher(%s, $$
                CREATE (n:{category.get_age_vertex_name()} {{type: "PROTOCOL_EVENT", category_id: %s, category_type: %s, label: %s, created_at: %s, external_id: %s, valid_from: %s, valid_to: %s}})
                SET n.performed_by = %s
                {build_variable_setters}
                RETURN n
            $$) as (n agtype);
            """,
            tuple([category.graph.age_name, category.id, category.get_age_type_name(), name, datetime.datetime.now().isoformat(), external_id, valid_from.isoformat() if valid_from else None, valid_to.isoformat() if valid_to else None, user] + [variable.value for variable in variables]),
        )
        result = cursor.fetchone()
        if result:
            entity = result[0]
            return vertex_ag_to_retrieved_entity(category.graph.age_name, entity)
        else:
            raise ValueError("No entity created or returned by the query.")


def create_age_natural_event(
    category: "models.NaturalEventCategory",
    name: str | None = None,
    external_id: str | None = None,
    valid_from: datetime.datetime | None = None,
    valid_to: datetime.datetime | None = None,
) -> RetrievedEntity:
    if category.sequence:
        select_sequence = f"SELECT nextval({category.sequence.ps_name}) AS next_id"
        sequence_setting = "SET n.sequence = next_id"
    else:
        select_sequence = ""
        sequence_setting = ""

    with graph_cursor() as cursor:
        if external_id:
            # Try to find existing reagent first
            cursor.execute(
                f"""
            SELECT * 
            {select_sequence}
            FROM cypher(%s, $$
                MATCH (n:{category.get_age_vertex_name()} {{type: "NATURAL_EVENT", category_id: %s, category_type: %s}}) 
                WHERE n.external_id = %s
                SET n.label = %s
                SET n.created_at = %s
                SET n.valid_from = %s
                SET n.valid_to = %s
                {sequence_setting}
                RETURN n
            $$) as (n agtype);
            """,
                (
                    category.graph.age_name,
                    category.id,
                    category.get_age_type_name(),
                    external_id,
                    name,
                    get_now_epoch_millis(),
                    valid_from.isoformat() if valid_from else None,
                    valid_to.isoformat() if valid_to else None,
                ),
            )
            existing = cursor.fetchone()
            if existing:
                return vertex_ag_to_retrieved_entity(category.graph.age_name, existing[0])

        # Create new reagent if not found
        cursor.execute(
            f"""
            SELECT * 
            FROM cypher(%s, $$
                CREATE (n:{category.get_age_vertex_name()} {{type: "NATURAL_EVENT", category_id: %s, category_type: %s, label: %s, created_at: %s, external_id: %s, valid_from: %s, valid_to: %s}})
                RETURN n
            $$) as (n agtype);
            """,
            (
                category.graph.age_name,
                category.id,
                category.get_age_type_name(),
                name,
                datetime.datetime.now().isoformat(),
                external_id,
                valid_from.isoformat() if valid_from else None,
                valid_to.isoformat() if valid_to else None,
            ),
        )
        result = cursor.fetchone()
        if result:
            entity = result[0]
            return vertex_ag_to_retrieved_entity(category.graph.age_name, entity)
        else:
            raise ValueError("No entity created or returned by the query.")


def create_age_event_in_edge(
    category: "models.ProtocolEventCategory",
    event_entity: RetrievedEntity,
    edge: ProtocolInEdge,
):
    # Create the edge between the entity and the event
    with graph_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT * 
            FROM cypher(%s, $$
                MATCH (a) WHERE id(a) = %s
                MATCH (b) WHERE id(b) = %s
                CREATE (a)-[r: {category.get_inrole_vertex_name(edge.role)} {{quantity: %s, role: %s, type: "PARTICIPANT"}}]->(b)
                RETURN r
            $$) as (r agtype);
            """,
            (
                event_entity.graph_name,
                edge.source,
                event_entity.id,
                edge.quantity,
                edge.role,
            ),
        )
        result = cursor.fetchone()
        if result:
            new_edge = result[0]
            return edge_ag_to_retrieved_relation(event_entity.graph_name, new_edge)
        else:
            raise ValueError(f"No entity created or returned by the query. To created {event_entity} {edge}")


def create_age_event_out_edge(
    category: "models.ProtocolEventCategory",
    event_entity: RetrievedEntity,
    edge: ProtocolOutEdge,
):
    # Create the edge between the entity and the event
    with graph_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT * 
            FROM cypher(%s, $$
                MATCH (a) WHERE id(a) = %s
                MATCH (b) WHERE id(b) = %s
                CREATE (a)-[r: {category.get_outrole_vertex_name(edge.role)} {{quantity: %s, role: %s, type: "PARTICIPANT"}}]->(b)
                RETURN r
            $$) as (r agtype);
            """,
            (
                event_entity.graph_name,
                event_entity.id,
                edge.target,
                edge.quantity,
                edge.role,
            ),
        )
        result = cursor.fetchone()
        if result:
            new_edge = result[0]
            return edge_ag_to_retrieved_relation(event_entity.graph_name, new_edge)
        else:
            raise ValueError(f"No entity created or returned by the query. To created {event_entity} {edge}")


def get_random_node(graph_name):
    with graph_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT * 
            FROM cypher(%s, $$
                MATCH (n)
                RETURN n
                ORDER BY rand()
                LIMIT 1
            $$) as (n agtype);
            """,
            [graph_name],
        )

        result = cursor.fetchone()
        if result:
            entity = result[0]
            return vertex_ag_to_retrieved_entity(graph_name, entity)
        else:
            raise ValueError("No entity created or returned by the query.")


def create_age_structure(
    category: "models.StructureCategory",
    object: str = None,
) -> RetrievedEntity:
    with graph_cursor() as cursor:
        try:
            cursor.execute(
                f"""
                SELECT *
                FROM cypher(%s, $$
                    MATCH (s:{category.get_age_vertex_name()} {{type: "STRUCTURE", category_type: %s, category_id: %s}})
                    WHERE s.object = %s
                    SET s.created_at = %s,
                        s.identifier = %s
                    RETURN s
                $$) AS (s agtype);
                """,
                (
                    category.graph.age_name,
                    category.get_age_type_name(),
                    category.id,
                    object,
                    get_now_epoch_millis(),
                    category.identifier,
                ),
            )
            existing = cursor.fetchone()
            if existing:
                return vertex_ag_to_retrieved_entity(category.graph.age_name, existing[0])
        except Exception as e:
            print(f"Error finding existing structure: {e}")

        cursor.execute(
            f"""
            SELECT * 
            FROM cypher(%s, $$
                CREATE (s: {category.get_age_vertex_name()} {{type: "STRUCTURE", category_type: %s, category_id: %s}})
                SET s.object = %s
                SET s.created_at = %s,
                    s.identifier = %s
                RETURN s
            $$) as (s agtype);
            """,
            (
                category.graph.age_name,
                category.get_age_type_name(),
                category.id,
                object,
                get_now_epoch_millis(),
                category.identifier,
            ),
        )
        result = cursor.fetchone()
        if result:
            entity = result[0]
            print("Created structure", entity)
            return vertex_ag_to_retrieved_entity(category.graph.age_name, entity)
        else:
            raise ValueError("No entity created or returned by the query.")


def create_measurement(
    category: "models.MeasurementCategory",
    structure_id: str,
    entity_id: str,
    valid_from: datetime.datetime | None = None,
    valid_to: datetime.datetime | None = None,
    assignation_id: str | None = None,
    created_by: str | None = None,
    created_at: datetime.datetime | None = None,
):
    """Associate a structure to an entity

    Associate a structure to an entity in the graph database.
    Creates the second link in the measurment path

    (metric: Metric) -> [describes] -> (Structure) -> [measures] -> (Entity)
                                                        ++++++

    Parameters:
        graph_name (str): The name of the graph.
        structure_identifier (str): The identifier of the structure. Think "@mikro/image"
        structure_id (str): The ID of the structure. Think "566"
        entity_id (str): The ID of the entity (bioentity). Think "566"
        valid_from (datetime.datetime): The date from which the association is valid.
        valid_to (datetime.datetime): The date until which the association is valid.
        assignation_id (str): The ID of the assignation (based on the rekuest ID, if applicable).
        created_by (str): The ID of the user who created the association.

    """
    with graph_cursor() as cursor:
        cursor.execute(
            f"""SELECT * FROM cypher(%s, $$
                MATCH (a) WHERE id(a) = %s
                MATCH (b) WHERE id(b) = %s
                CREATE (a)-[r: {category.get_age_edge_name()} {{type: "MEASUREMENT", category_type: %s, category_id: %s}}]->(b)
                SET r.valid_from = %s, r.valid_to = %s, r.created_at = %s, r.created_through = %s, r.created_by = %s
                RETURN r
            $$) AS (r agtype);
            """,
            (
                category.graph.age_name,
                structure_id,
                entity_id,
                category.get_age_type_name(),
                category.id,
                valid_from.isoformat() if valid_from else None,
                valid_to.isoformat() if valid_to else None,
                created_at.isoformat() if created_at else None,
                assignation_id,
                created_by,
            ),
        )

        result = cursor.fetchone()
        if result:
            measurement = result[0]
            return edge_ag_to_retrieved_relation(category.graph.age_name, measurement)
        else:
            raise ValueError("No measurement created or returned by the query.")


def delete_edge(
    graph_name: str,
    edge_id: int,
):
    """
    Delete an edge by its ID.

    Parameters:
        graph_name (str): The name of the graph.
        edge_id (int): The ID of the edge to delete.

    Returns:
        None
    """

    with graph_cursor() as cursor:
        cursor.execute(
            f"""SELECT * FROM cypher(%s, $$
                MATCH (a)-[r]->(b)
                WHERE id(r) = %s
                DELETE r
            $$) AS (r agtype);
            """,
            (graph_name, int(edge_id)),
        )

        result = cursor.fetchone()
        return None


def delete_node(
    graph_name: str,
    node_id: int,
):
    """
    Delete an edge by its ID.

    Parameters:
        graph_name (str): The name of the graph.
        edge_id (int): The ID of the edge to delete.

    Returns:
        None
    """

    with graph_cursor() as cursor:
        cursor.execute(
            f"""SELECT * FROM cypher(%s, $$
                MATCH (a)
                WHERE id(a) = %s
                DELETE a
            $$) AS (r agtype);
            """,
            (graph_name, int(node_id)),
        )

        result = cursor.fetchone()
        return None


def detach_delete_node(
    graph_name: str,
    node_id: int,
):
    """
    Delete an edge by its ID.

    Parameters:
        graph_name (str): The name of the graph.
        edge_id (int): The ID of the edge to delete.

    Returns:
        None
    """

    with graph_cursor() as cursor:
        cursor.execute(
            f"""SELECT * FROM cypher(%s, $$
                MATCH (a)
                WHERE id(a) = %s
                DETACH DELETE a
            $$) AS (r agtype);
            """,
            (graph_name, int(node_id)),
        )

        result = cursor.fetchone()
        return None


def create_age_metric(
    metric_category: "models.MetricCategory",
    structure_id: str,
    value,
    assignation_id: str | None = None,
    created_by: str | None = None,
    created_app: str | None = None,
):
    with graph_cursor() as cursor:
        if isinstance(value, list):
            value = json.dumps(value)

        cursor.execute(
            f"""SELECT * FROM cypher(%s, $$
                MATCH (a) WHERE id(a) = %s
                CREATE (b: {metric_category.get_age_vertex_name()} {{type: "METRIC", category_type: %s, category_id: %s, value: %s, created_at: %s, created_by: %s, created_through: %s, created_app: %s}})
                CREATE (b)-[r:DESCRIBES {{type: "DESCRIPTION"}}]->(a)
                RETURN b
            $$) AS (r agtype);
            """,
            (
                metric_category.graph.age_name,
                structure_id,
                metric_category.get_age_type_name(),
                metric_category.id,
                value,
                datetime.datetime.now().isoformat(),
                created_by,
                assignation_id,
                created_app,
            ),
        )
        result = cursor.fetchone()
        if result:
            entity = result[0]
            return vertex_ag_to_retrieved_entity(metric_category.graph.age_name, entity)
        else:
            raise ValueError("No entity created or returned by the query.")


def get_age_entity(graph_name, entity_id) -> RetrievedEntity:
    with graph_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT * 
            FROM cypher(%s, $$
                MATCH (n) WHERE id(n) = %s
                RETURN n
            $$) as (n agtype);
            """,
            (graph_name, int(entity_id)),
        )
        result = cursor.fetchone()
        if result:
            entity = result[0]
            return vertex_ag_to_retrieved_entity(graph_name, entity)
        raise ValueError("No entity created or returned by the query.")


def get_age_entity_by_category_and_external_id(category: models.EntityCategory, external_id) -> RetrievedEntity:
    with graph_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT * 
            FROM cypher(%s, $$
                MATCH {{type: "ENTITY", category_id: %s}}
                WHERE n.external_id = %s
            $$) as (n agtype);
            """,
            (category.graph.age_name, category.id, external_id),
        )
        result = cursor.fetchone()
        if result:
            entity = result[0]
            return vertex_ag_to_retrieved_entity(category.graph.age_name, entity)
        raise ValueError("No entity created or returned by the query.")


def get_entities(filters: typing.Optional["filters.EntityFilter"], pagination: typing.Optional["pagination.GraphPaginationInput"] = None) -> RetrievedEntity:
    from core import models, filters as f, pagination as p

    if not filters:
        filters = f.EntityFilter()

    if not pagination:
        pagination = p.GraphPaginationInput()

    base_qs = models.EntityCategory.objects

    match_statements = []

    print(filters)

    if filters.graph:
        base_qs = base_qs.filter(graph_id=filters.graph)

    if filters.tags:
        base_qs = base_qs.filter(tags__value__in=filters.tags)

    if filters.categories:
        base_qs = base_qs.filter(id__in=filters.categories)

    categories = base_qs.all()
    if categories.count() == 0:
        raise ValueError(f"No categories found for {filters.categories} and {filters.tags}")

    if not filters.graph:
        graph_name = categories[0].graph.age_name
        for category in categories:
            if category.graph.age_name != graph_name:
                raise ValueError("All categories must belong to the same graph.")
    else:
        graph_name = models.Graph.objects.get(id=filters.graph).age_name

    query_params = [
        graph_name,
    ]

    match_statements.append(f"n.category_id IN {[cat.id for cat in categories]}")

    if filters.external_ids:
        match_statements.append(f"n.external_id IN [{', '.join(map(str, filters.external_ids))}]")

    if filters.search:
        match_statements.append(f"n.label CONTAINS '{filters.search}' OR n.description CONTAINS '{filters.search}' OR n.external_id CONTAINS '{filters.search}'")

    if filters.created_after:
        match_statements.append(f"n.created_at > '{filters.created_after.isoformat()}'")

    if filters.created_before:
        match_statements.append(f"n.created_at < '{filters.created_before.isoformat()}'")

    if filters.ids:
        graph_names = [to_graph_id(i) for i in filters.ids]
        assert set(graph_names) == {graph_name}, "All ids must belong to the same graph."

        match_statements.append(f"id(n) IN {[int(to_entity_id(i)) for i in filters.ids]}")

    if filters.active:
        match_statements.append(f"n.active = true")

    FINAL_MATCH = " AND ".join(match_statements)
    print("Final match", FINAL_MATCH)
    print("Graphname", graph_name)

    final_query = f"""
            SELECT *
            FROM cypher(%s, $$
                MATCH (n) WHERE {FINAL_MATCH}
                RETURN n
            $$) as (n agtype);
    """

    print("Final query", final_query, query_params)

    with graph_cursor() as cursor:
        cursor.execute(
            final_query,
            query_params,
        )
        result = cursor.fetchall()
        print("Retrieved this result", result)
        if result:
            return [vertex_ag_to_retrieved_entity(graph_name, metric[0]) for metric in result]
        else:
            return []


def get_reagents(filters: typing.Optional["filters.ReagentFilter"], pagination: typing.Optional["pagination.GraphPaginationInput"] = None) -> RetrievedEntity:
    from core import models, filters as f, pagination as p

    if not filters:
        filters = f.ReagentFilter()

    if not pagination:
        pagination = p.GraphPaginationInput()

    base_qs = models.ReagentCategory.objects

    match_statements = []

    print(filters)

    if filters.graph:
        base_qs = base_qs.filter(graph_id=filters.graph)

    if filters.tags:
        base_qs = base_qs.filter(tags__value__in=filters.tags)

    if filters.categories:
        base_qs = base_qs.filter(id__in=filters.categories)

    categories = base_qs.all()

    if categories.count() == 0:
        raise ValueError(f"No categories found for {filters.categories} and {filters.tags}")

    if not filters.graph:
        graph_name = categories[0].graph.age_name
        for category in categories:
            if category.graph.age_name != graph_name:
                raise ValueError("All categories must belong to the same graph.")
    else:
        graph_name = models.Graph.objects.get(id=filters.graph).age_name

    query_params = [
        graph_name,
    ]

    match_statements.append(f"n.category_id IN {[cat.id for cat in categories]}")

    if filters.external_ids:
        match_statements.append(f"n.external_id IN [{', '.join(map(str, filters.external_ids))}]")

    if filters.search:
        match_statements.append(f"n.label ILIKE '%{filters.search}%'")

    if filters.created_after:
        match_statements.append(f"n.created_at > '{filters.created_after.isoformat()}'")

    if filters.created_before:
        match_statements.append(f"n.created_at < '{filters.created_before.isoformat()}'")

    if filters.ids:
        graph_names = [to_graph_id(i) for i in filters.ids]
        assert set(graph_names) == {graph_name}, "All ids must belong to the same graph."

        match_statements.append(f"id(n) IN {[int(to_entity_id(i)) for i in filters.ids]}")

    if filters.active:
        match_statements.append(f"n.active = true")

    FINAL_MATCH = " AND ".join(match_statements)
    print("Final match", FINAL_MATCH)
    print("Graphname", graph_name)

    final_query = f"""
            SELECT *
            FROM cypher(%s, $$
                MATCH (n) WHERE {FINAL_MATCH}
                RETURN n
            $$) as (n agtype);
    """

    print("Final query", final_query, query_params)

    with graph_cursor() as cursor:
        cursor.execute(
            final_query,
            query_params,
        )
        result = cursor.fetchall()
        print("Retrieved this result", result)
        if result:
            return [vertex_ag_to_retrieved_entity(graph_name, metric[0]) for metric in result]
        else:
            return []


def select_measurements_for_structure(graph_name, structure_id, categories: list["models.MeasurementCategory"]):
    with graph_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT * 
            FROM cypher(%s, $$
                MATCH (n)-[r]->(m)
                WHERE id(n) = %s 
                AND r.category_id IN {[cat.id for cat in categories]}
                RETURN r
            $$) as (r agtype);
            """,
            (graph_name, structure_id),
        )
        result = cursor.fetchall()
        if result:
            return [edge_ag_to_retrieved_relation(graph_name, measurement[0]) for measurement in result]
        else:
            return []


def select_measurements_for_entity(graph_name, entity_id):
    with graph_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT * 
            FROM cypher(%s, $$
                MATCH (n)<-[r]-(m)
                WHERE r.type = "MEASUREMENT"
                AND id(n) = %s 
                RETURN r
            $$) as (r agtype);
            """,
            (graph_name, entity_id),
        )
        result = cursor.fetchall()
        if result:
            return [edge_ag_to_retrieved_relation(graph_name, measurement[0]) for measurement in result]
        else:
            return []


def select_target_participation_for_entity(graph_name, entity_id):
    with graph_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT * 
            FROM cypher(%s, $$
                MATCH (n)<-[r]-(m)
                WHERE r.type = "PARTICIPANT"
                AND id(n) = %s 
                RETURN r
            $$) as (r agtype);
            """,
            (graph_name, entity_id),
        )
        result = cursor.fetchall()
        if result:
            return [edge_ag_to_retrieved_relation(graph_name, participation[0]) for participation in result]
        else:
            return []


def select_source_participation_for_entity(graph_name, entity_id):
    with graph_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT * 
            FROM cypher(%s, $$
                MATCH (n)-[r]->(m)
                WHERE r.type = "PARTICIPANT"
                AND id(n) = %s 
                RETURN r
            $$) as (r agtype);
            """,
            (graph_name, entity_id),
        )
        result = cursor.fetchall()
        if result:
            return [edge_ag_to_retrieved_relation(graph_name, participation[0]) for participation in result]
        else:
            return []


def get_age_structure(graph_name, structure_identifier) -> RetrievedEntity:
    with graph_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT * 
            FROM cypher(%s, $$
                MATCH (n)
                WHERE n.structure = %s
                RETURN n
            $$) as (n agtype);
            """,
            (graph_name, structure_identifier),
        )
        result = cursor.fetchone()
        if result:
            entity = result[0]
            return vertex_ag_to_retrieved_entity(graph_name, entity)
        raise ValueError("No entity created or returned by the query.")


def get_age_structure_by_object(structure: "models.StructureCategory", object: str) -> RetrievedEntity:
    with graph_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT * 
            FROM cypher(%s, $$
                MATCH (n)
                WHERE n.object = %s
                AND n.category_id = %s
                RETURN n
            $$) as (n agtype);
            """,
            (structure.graph.age_name, object, structure.id),
        )
        result = cursor.fetchone()
        if result:
            entity = result[0]
            return vertex_ag_to_retrieved_entity(structure.graph.age_name, entity)
        raise ValueError("No entity created or returned by the query.")


def get_age_entity_relation(graph_name, edge_id) -> RetrievedRelation:
    with graph_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT * 
            FROM cypher(%s, $$
                MATCH (a)-[e]->(b) 
                WHERE id(e) = %s
                RETURN e
            $$) as (e agtype);
            """,
            (graph_name, int(edge_id)),
        )
        result = cursor.fetchone()
        if result:
            relation = result[0]
            return edge_ag_to_retrieved_relation(graph_name, relation)
        raise ValueError("No entityrelation found by the query.")


def get_age_edge(graph_name, edge_id) -> RetrievedRelation:
    with graph_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT * 
            FROM cypher(%s, $$
                MATCH (a)-[e]->(b) 
                WHERE id(e) = %s
                RETURN e
            $$) as (e agtype);
            """,
            (graph_name, int(edge_id)),
        )
        result = cursor.fetchone()
        if result:
            relation = result[0]
            return edge_ag_to_retrieved_relation(graph_name, relation)
        raise ValueError("No entityrelation found by the query.")


def get_age_metrics(graph_name, node_id):
    with graph_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT * 
            FROM cypher(%s, $$
                    MATCH (a)-[r]->(a)
                    WHERE id(a) = %s
                    RETURN r
            $$) AS (r agtype);
            """,
            (graph_name, int(node_id)),
        )
        result = cursor.fetchall()
        print("Retrieved this result", result)
        if result:
            return [edge_ag_to_retrieved_metric(graph_name, metric[0]) for metric in result]
        else:
            return []


def create_age_relation(category: "models.RelationCategory", left_id, right_id):
    with graph_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT * 
            FROM cypher(%s, $$
                MATCH (a) WHERE id(a) = %s
                MATCH (b) WHERE id(b) = %s
                CREATE (a)-[r:{category.get_age_edge_name()} {{type: "RELATION", category_type: %s, category_id: %s}}]->(b)
                RETURN r
            $$) as (r agtype);
            """,
            (category.graph.age_name, int(left_id), int(right_id), category.get_age_type_name(), category.id),
        )
        result = cursor.fetchone()
        if result:
            return edge_ag_to_retrieved_relation(category.graph.age_name, result[0])
        else:
            existence_query = """
                SELECT count(*)
                FROM cypher(%s, $$
                    MATCH (a), (b)
                    WHERE id(a) = %s AND id(b) = %s
                    RETURN count(*)
                $$) as (count agtype);
            """

            cursor.execute(existence_query, (category.graph.age_name, int(left_id), int(right_id)))
            node_count = cursor.fetchone()[0]

            if node_count < 2:
                raise ValueError(f"One or both of the nodes do not exist. {left_id}, {right_id}, {category.graph.age_name}")

            raise ValueError("No entity created or returned by the query.")


def create_age_structure_relation(category: "models.StructureRelationCategory", left_id, right_id):
    with graph_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT * 
            FROM cypher(%s, $$
                MATCH (a) WHERE id(a) = %s
                MATCH (b) WHERE id(b) = %s
                CREATE (a)-[r:{category.get_age_edge_name()} {{type: "STRUCTURE_RELATION", category_type: %s, category_id: %s}}]->(b)
                RETURN r
            $$) as (r agtype);
            """,
            (category.graph.age_name, int(left_id), int(right_id), category.get_age_type_name(), category.id),
        )
        result = cursor.fetchone()
        if result:
            return edge_ag_to_retrieved_relation(category.graph.age_name, result[0])
        else:
            existence_query = """
                SELECT count(*)
                FROM cypher(%s, $$
                    MATCH (a), (b)
                    WHERE id(a) = %s AND id(b) = %s
                    RETURN count(*)
                $$) as (count agtype);
            """

            cursor.execute(existence_query, (category.graph.age_name, int(left_id), int(right_id)))
            node_count = cursor.fetchone()[0]

            if node_count < 2:
                raise ValueError(f"One or both of the nodes do not exist. {left_id}, {right_id}, {category.graph.age_name}")

            raise ValueError("No entity created or returned by the query.")


def to_entity_id(id):
    return int(id.split(":")[1])


def to_graph_id(id):
    return id.split(":")[0]


def select_all_entities(
    graph_name,
    pagination: pagination.GraphPaginationInput,
    filter: filters.EntityFilter,
):
    with graph_cursor() as cursor:
        WHERE = ""

        and_clauses = []

        if filter:
            if filter.ids:
                and_clauses.append(f"id(n) IN [ {', '.join([to_entity_id(id) for id in filter.ids])}]")

            if filter.search:
                and_clauses.append(f'n.Label STARTS WITH "{filter.search}"')

            if filter.linked_expression:
                expression = models.LinkedExpression.objects.get(id=filter.linked_expression)
                and_clauses.append(f'label(n) = "{expression.age_name}"')

            if and_clauses:
                WHERE = "WHERE " + " AND ".join(and_clauses)

        print(WHERE)

        cursor.execute(
            f"""
            SELECT * 
            FROM cypher(%s, $$
                MATCH (n)
                {WHERE}
                RETURN n
                ORDER BY id(n)
                SKIP %s
                LIMIT %s
            $$) as (n agtype);
            """,
            [graph_name, pagination.offset or 0, pagination.limit or 200],
        )

        if cursor.rowcount == 0:
            return []

        for result in cursor.fetchall():
            print(result)
            yield vertex_ag_to_retrieved_entity(graph_name, result[0])


def select_latest_nodes(
    graph_name,
    pagination: pagination.GraphPaginationInput,
    filter: filters.EntityFilter,
):
    with graph_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT *
            FROM cypher(%s, $$
                MATCH (n)
                RETURN n
                ORDER BY n.created_at DESC
                SKIP %s
                LIMIT %s
            $$) as (n agtype);
            """,
            [graph_name, pagination.offset or 0, pagination.limit or 200],
        )

        if cursor.rowcount == 0:
            return []

        for result in cursor.fetchall():
            yield vertex_ag_to_retrieved_entity(graph_name, result[0])


def select_paired_entities(
    graph_name,
    pagination: pagination.GraphPaginationInput,
    relation_filter: filters.EntityRelationFilter | None = None,
    left_filter: filters.EntityFilter | None = None,
    right_filter: filters.EntityFilter | None = None,
):
    with graph_cursor() as cursor:
        WHERE = ""

        and_clauses = []

        if left_filter:
            if left_filter.ids:
                and_clauses.append(f"id(n) IN [ {', '.join([to_entity_id(id) for id in filter.ids])}]")

            if left_filter.search:
                and_clauses.append(f'n.Label STARTS WITH "{filter.search}"')

            if left_filter.linked_expression:
                expression = models.LinkedExpression.objects.get(id=filter.linked_expression)
                and_clauses.append(f'label(n) = "{expression.age_name}"')

            if and_clauses:
                WHERE = "WHERE " + " AND ".join(and_clauses)

        if right_filter:
            if right_filter.ids:
                and_clauses.append(f"id(m) IN [ {', '.join([to_entity_id(id) for id in filter.ids])}]")

            if right_filter.search:
                and_clauses.append(f'm.Label STARTS WITH "{filter.search}"')

            if right_filter.linked_expression:
                expression = models.LinkedExpression.objects.get(id=filter.linked_expression)
                and_clauses.append(f'label(m) = "{expression.age_name}"')

            if and_clauses:
                WHERE = "WHERE " + " AND ".join(and_clauses)

        if relation_filter:
            if relation_filter.left_id:
                and_clauses.append(f"id(n) = {to_entity_id(relation_filter.left_id)}")

            if relation_filter.right_id:
                and_clauses.append(f"id(m) = {to_entity_id(relation_filter.right_id)}")

            if not relation_filter.with_self:
                and_clauses.append(f"id(n) <> id(m)")

            if relation_filter.ids:
                and_clauses.append(f"id(e) IN [ {', '.join([to_entity_id(id) for id in relation_filter.ids])}]")

            if relation_filter.search:
                and_clauses.append(f'e.Label STARTS WITH "{relation_filter.search}"')

            if relation_filter.linked_expression:
                expression = models.LinkedExpression.objects.get(id=relation_filter.linked_expression)
                and_clauses.append(f'label(e) = "{expression.age_name}"')

        cursor.execute(
            f"""
            SELECT * 
            FROM cypher(%s, $$
                MATCH (n) - [e] - (m)
                {WHERE}
                RETURN n, m, e
                SKIP %s
                LIMIT %s
            $$) as (n agtype, m agtype, e agtype);
            """,
            [graph_name, pagination.offset or 0, pagination.limit or 200],
        )

        if cursor.rowcount == 0:
            return []

        for result in cursor.fetchall():
            print(result)
            yield vertex_ag_to_retrieved_entity(graph_name, result[0]), vertex_ag_to_retrieved_entity(graph_name, result[1]), edge_ag_to_retrieved_relation(graph_name, result[2])


def set_entity_variable(graph_name: str, node_id: int, variable_name: str, variable_value: typing.Union[str, int, float, bool], created_by: str | None = None) -> RetrievedEntity:
    with graph_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT * 
            FROM cypher(%s, $$
                MATCH (n) WHERE id(n) = %s
                SET n.{variable_name} = %s
                RETURN n
            $$) as (n agtype);
            """,
            (graph_name, int(node_id), variable_value),
        )
        result = cursor.fetchone()
        if result:
            # Always create an edit event for provenance logging
            cursor.execute(
                f"""
                SELECT * 
                FROM cypher(%s, $$
                    MATCH (a) WHERE id(a) = %s
                    CREATE (b:EditEvent {{type: "EDIT_EVENT", created_by: %s, new_value: %s, variable_name: %s, created_at: %s}})
                    CREATE (a)-[r:EDITED {{type: "EDITED"}}]->(b)
                    RETURN r
                $$) as (r agtype);
                """,
                (graph_name, int(node_id), created_by, str(variable_value), variable_name, datetime.datetime.now().isoformat()),
            )
            print(cursor.fetchone())

            entity = result[0]
            return vertex_ag_to_retrieved_entity(graph_name, entity)
        else:
            raise ValueError("No entity created or returned by the query.")


def select_related_structure_metrics(
    graph_name,
    node_id,
    pagination: pagination.GraphPaginationInput | None = None,
    filters: filters.MetricFilter | None = None,
):
    with graph_cursor() as cursor:
        WHERE = "WHERE id(n)= %s"

        if not pagination:
            pagination = GraphPaginationInput()

        cursor.execute(
            f"""
            SELECT * 
            FROM cypher(%s, $$
                MATCH (n) <-[:DESCRIBES]- (m)
                {WHERE}
                RETURN m
                SKIP %s
                LIMIT %s
            $$) as (m agtype);
            """,
            [graph_name, int(node_id), pagination.offset or 0, pagination.limit or 200],
        )

        for result in cursor.fetchall():
            yield vertex_ag_to_retrieved_entity(graph_name, result[0])


def select_all_relations(
    graph_name,
    pagination: pagination.GraphPaginationInput,
    filter: filters.EntityRelationFilter,
):
    with graph_cursor() as cursor:
        WHERE = ""

        and_clauses = []

        if filter:
            if filter.left_id:
                and_clauses.append(f"id(a) = {to_entity_id(filter.left_id)}")

            if filter.right_id:
                and_clauses.append(f"id(b) = {to_entity_id(filter.right_id)}")

            if not filter.with_self:
                and_clauses.append(f"id(a) <> id(b)")

            if filter.ids:
                and_clauses.append(f"id(e) IN [ {', '.join([to_entity_id(id) for id in filter.ids])}]")

            if filter.search:
                and_clauses.append(f'e.Label STARTS WITH "{filter.search}"')

            if filter.linked_expression:
                expression = models.LinkedExpression.objects.get(id=filter.linked_expression)
                and_clauses.append(f'label(e) = "{expression.age_name}"')

            if and_clauses:
                WHERE = "WHERE " + " AND ".join(and_clauses)

        print(WHERE)

        try:
            cursor.execute(
                f"""
                SELECT * 
                FROM cypher(%s, $$
                    MATCH (a) - [e] - (b)
                    {WHERE}
                    RETURN e
                    ORDER BY id(e)
                    SKIP %s
                    LIMIT %s
                $$) as (e agtype);
                """,
                [graph_name, pagination.offset or 0, pagination.limit or 200],
            )

            print("here")

            if cursor.rowcount == 0:
                print("No results")
                return []

            for result in cursor.fetchall():
                print(result)
                yield edge_ag_to_retrieved_relation(graph_name, result[0])

        except Exception as e:
            print("Error", e)
            print(e)
            return []


def get_age_relations(graph_name: str, entity_id: int) -> typing.Iterable[RetrievedRelation]:
    """Get all relations for an entity"""
    with graph_cursor() as cursor:
        cursor.execute(
            """
            SELECT * 
            FROM cypher(%s, $$
                MATCH (a)-[r]-(b) WHERE id(a) = %s
                RETURN id(r), type(r), id(a), id(b), properties(r)
            $$) as (rel_id agtype, rel_type agtype, start_id agtype, end_id agtype, rel_props agtype);
            """,
            [graph_name, entity_id],
        )
        for result in cursor.fetchall():
            print(result)
            yield RetrievedRelation(
                id=result[0],
                kind_age_name=result[1],
                left_id=result[2],
                right_id=result[3],
                properties=json.loads(result[4]),
                graph_name=graph_name,
            )


def get_right_relations(graph_name: str, entity_id: int):
    with graph_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT * 
            FROM cypher(%s, $$
                MATCH (a)-[r]->(b) WHERE id(a) = %s
                RETURN id(r), type(r), id(a), id(b), properties(r)
            $$) as (rel_id agtype, rel_type agtype, start_id agtype, end_id agtype, rel_props agtype);
            """,
            [graph_name, entity_id],
        )
        for result in cursor.fetchall():
            print(result)
            yield RetrievedRelation(
                id=result[0],
                kind_age_name=result[1],
                left_id=result[2],
                right_id=result[3],
                properties=json.loads(result[4]),
                graph_name=graph_name,
            )


def get_left_relations(graph_name, entity_id):
    with graph_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT * 
            FROM cypher(%s, $$
                MATCH (a)<-[r]-(b) WHERE id(a) = %s
                RETURN id(r), type(r), id(b), id(a), properties(r)
            $$) as (rel_id agtype, rel_type agtype, start_id agtype, end_id agtype, rel_props agtype);
            """,
            [graph_name, entity_id],
        )
        for result in cursor.fetchall():
            print(result)
            yield RetrievedRelation(
                id=result[0],
                kind_age_name=result[1],
                left_id=result[2],
                right_id=result[3],
                properties=json.loads(result[4]),
                graph_name=graph_name,
            )


def create_age_sequence(sequence: "models.GraphSequence") -> RetrievedEntity:
    with graph_cursor() as cursor:
        cursor.execute(
            f"""
            CREATE SEQUENCE {sequence.ps_name}
                START WITH {sequence.start_value}
                INCREMENT BY {sequence.step_size}
                MINVALUE {sequence.min_value}
                CACHE 1
                {"MAXVALUE " + str(sequence.max_value) if sequence.max_value else ""}
                {"CYCLE " if sequence.cycle else ""}
            
            """,
        )
        return cursor.fetchone() if cursor.rowcount > 0 else None
