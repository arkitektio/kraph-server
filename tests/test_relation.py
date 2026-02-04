"""
Tests for relationship creation with supporting evidence.

These tests verify that:
1. Relations between entities can be created with supporting evidence (ROIs)
2. Measurements on supporting structures are properly rolled up to the relation edge
3. ShadowLink nodes are created to track evidence
4. The relation edge properties are correctly materialized from evidence
"""
import pytest
import uuid
from graph_engine.controller import GraphController
from graph_engine import input_models as inputs
from graph_engine import base_models as models
from graph_engine.engine.protocol import SimpleGraph


def _uid(prefix: str = "test") -> str:
    """Generate a unique ID for test objects."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def relation_schema():
    """
    Schema with a relation that has materialized properties.
    Uses simpler aggregations (MEAN, SUM) that are implemented.
    """
    return models.GraphDefinitionModel(
        system_version="1.0",
        extensions=models.GraphExtensions(
            structures=[
                models.StructureDefinition(
                    key="ROI",
                    description="Region of Interest",
                ),
            ],
            entities=[
                models.EntityDefinition(
                    key="Neuron",
                    properties=[]
                ),
                models.EntityDefinition(
                    key="Synapse",
                    properties=[]
                )
            ],
            relations=[
                models.RelationDefinition(
                    key="SYNAPSES_WITH",
                    source="Neuron",
                    target="Neuron",
                    cardinality="N:N",
                    materialization=models.MaterializationConfig(
                        backing_link_type="synapse_link",
                        desired_evidence=[
                            models.EvidenceRequirement(key="overlap_score", unit="score"),
                            models.EvidenceRequirement(key="distance", unit="um"),
                        ],
                        properties=[
                            models.PropertyDefinition(
                                key="avg_overlap",
                                type=models.PropertyType.FLOAT,
                                derivation=models.DerivationType.ROLLUP,
                                rule=models.DerivationRule(
                                    source_node="ROI",
                                    key="overlap_score",
                                    aggregation=models.AggregationFunction.MEAN
                                )
                            ),
                            models.PropertyDefinition(
                                key="total_confidence",
                                type=models.PropertyType.FLOAT,
                                derivation=models.DerivationType.ROLLUP,
                                rule=models.DerivationRule(
                                    source_node="ROI",
                                    key="confidence",
                                    aggregation=models.AggregationFunction.SUM
                                )
                            ),
                            models.PropertyDefinition(
                                key="min_distance",
                                type=models.PropertyType.FLOAT,
                                derivation=models.DerivationType.ROLLUP,
                                rule=models.DerivationRule(
                                    source_node="ROI",
                                    key="distance",
                                    aggregation=models.AggregationFunction.MIN
                                )
                            ),
                            models.PropertyDefinition(
                                key="evidence_count",
                                type=models.PropertyType.INTEGER,
                                derivation=models.DerivationType.ROLLUP,
                                rule=models.DerivationRule(
                                    source_node="ROI",
                                    key="overlap_score",
                                    aggregation=models.AggregationFunction.COUNT
                                )
                            )
                        ]
                    )
                )
            ],
            events=[]
        )
    )


@pytest.fixture
def relation_graph(relation_schema):
    """Create a test graph with the relation schema."""
    return SimpleGraph(age_name="test_graph", definition=relation_schema)


@pytest.fixture
def relation_controller(transactional_db, age_engine, relation_graph):
    """Create a controller with the relation schema."""
    return GraphController(engine=age_engine, graph=relation_graph)


class TestRelationCreation:
    """Tests for basic relation creation."""
    
    def test_create_relation_with_single_roi_evidence(self, relation_controller: GraphController, relation_schema):
        """
        Test creating a relation between two entities with a single ROI as evidence.
        The ROI measurements should be materialized onto the relation edge.
        """
        neuron1_id = _uid("neuron1")
        neuron2_id = _uid("neuron2")
        roi_obj = _uid("synapse_roi")
        
        # Create source and target entities
        entity1_result = relation_controller.create_entity(
            inputs.EntityCreationPayload(
                kind="Neuron",
                ref_id=neuron1_id,
                supporting_evidence=[],
                provenance=inputs.ProvenanceContext(subject="user", app_id="test")
            )
        )
        
        entity2_result = relation_controller.create_entity(
            inputs.EntityCreationPayload(
                kind="Neuron",
                ref_id=neuron2_id,
                supporting_evidence=[],
                provenance=inputs.ProvenanceContext(subject="user", app_id="test")
            )
        )
        
        # Create the relation with ROI evidence
        relation_result = relation_controller.create_relation(
            inputs.RelationCreationPayload(
                kind="SYNAPSES_WITH",
                source_id=entity1_result.db_id,
                target_id=entity2_result.db_id,
                supporting_evidence=[
                    inputs.StructureReference(
                        identifier="@mikro/roi",
                        object=roi_obj,
                        measurements=[
                            inputs.MeasurementInput(key="overlap_score", value=0.85, timestamp=1000),
                            inputs.MeasurementInput(key="distance", value=2.5, unit="um", timestamp=1000),
                            inputs.MeasurementInput(key="confidence", value=0.9, timestamp=1000),
                        ]
                    )
                ],
                provenance=inputs.ProvenanceContext(
                    subject="user",
                    app_id="synapse_detector",
                    action_name="detect_synapse"
                )
            ),
            schema=relation_schema
        )
        
        assert relation_result is not None
        assert relation_result.graph_id is not None
        
    def test_create_relation_with_multiple_roi_evidence(self, relation_controller: GraphController, relation_schema):
        """
        Test creating a relation with multiple ROIs as evidence.
        Materialized properties should aggregate across all evidence.
        """
        neuron1_id = _uid("neuron1")
        neuron2_id = _uid("neuron2")
        roi1_obj = _uid("roi1")
        roi2_obj = _uid("roi2")
        roi3_obj = _uid("roi3")
        
        # Create entities
        entity1_result = relation_controller.create_entity(
            inputs.EntityCreationPayload(
                kind="Neuron",
                ref_id=neuron1_id,
                supporting_evidence=[],
                provenance=inputs.ProvenanceContext(subject="user", app_id="test")
            )
        )
        
        entity2_result = relation_controller.create_entity(
            inputs.EntityCreationPayload(
                kind="Neuron",
                ref_id=neuron2_id,
                supporting_evidence=[],
                provenance=inputs.ProvenanceContext(subject="user", app_id="test")
            )
        )
        
        # Create relation with multiple ROIs as evidence
        relation_result = relation_controller.create_relation(
            inputs.RelationCreationPayload(
                kind="SYNAPSES_WITH",
                source_id=entity1_result.db_id,
                target_id=entity2_result.db_id,
                supporting_evidence=[
                    inputs.StructureReference(
                        identifier="@mikro/roi",
                        object=roi1_obj,
                        measurements=[
                            inputs.MeasurementInput(key="overlap_score", value=0.8, timestamp=1000),
                            inputs.MeasurementInput(key="distance", value=3.0, unit="um", timestamp=1000),
                            inputs.MeasurementInput(key="confidence", value=0.7, timestamp=1000),
                        ]
                    ),
                    inputs.StructureReference(
                        identifier="@mikro/roi",
                        object=roi2_obj,
                        measurements=[
                            inputs.MeasurementInput(key="overlap_score", value=0.9, timestamp=1001),
                            inputs.MeasurementInput(key="distance", value=2.0, unit="um", timestamp=1001),
                            inputs.MeasurementInput(key="confidence", value=0.8, timestamp=1001),
                        ]
                    ),
                    inputs.StructureReference(
                        identifier="@mikro/roi",
                        object=roi3_obj,
                        measurements=[
                            inputs.MeasurementInput(key="overlap_score", value=0.7, timestamp=1002),
                            inputs.MeasurementInput(key="distance", value=4.0, unit="um", timestamp=1002),
                            inputs.MeasurementInput(key="confidence", value=0.6, timestamp=1002),
                        ]
                    )
                ],
                provenance=inputs.ProvenanceContext(
                    subject="user",
                    app_id="synapse_detector"
                )
            ),
            schema=relation_schema
        )
        
        assert relation_result is not None
        assert relation_result.graph_id is not None


class TestRelationMaterialization:
    """Tests for relation property materialization from evidence."""
    
    def test_mean_aggregation_materializes_correctly(self, relation_controller: GraphController, relation_schema):
        """
        Test that MEAN aggregation correctly averages measurements across ROIs.
        """
        neuron1_id = _uid("neuron1")
        neuron2_id = _uid("neuron2")
        
        # Create entities
        entity1 = relation_controller.create_entity(
            inputs.EntityCreationPayload(
                kind="Neuron", ref_id=neuron1_id,
                supporting_evidence=[],
                provenance=inputs.ProvenanceContext(subject="user", app_id="test")
            )
        )
        entity2 = relation_controller.create_entity(
            inputs.EntityCreationPayload(
                kind="Neuron", ref_id=neuron2_id,
                supporting_evidence=[],
                provenance=inputs.ProvenanceContext(subject="user", app_id="test")
            )
        )
        
        # Create relation with known overlap scores: 0.6, 0.8, 1.0
        # Expected average: (0.6 + 0.8 + 1.0) / 3 = 0.8
        relation_result = relation_controller.create_relation(
            inputs.RelationCreationPayload(
                kind="SYNAPSES_WITH",
                source_id=entity1.db_id,
                target_id=entity2.db_id,
                supporting_evidence=[
                    inputs.StructureReference(
                        identifier="@mikro/roi",
                        object=_uid("roi1"),
                        measurements=[
                            inputs.MeasurementInput(key="overlap_score", value=0.6, timestamp=1000),
                        ]
                    ),
                    inputs.StructureReference(
                        identifier="@mikro/roi",
                        object=_uid("roi2"),
                        measurements=[
                            inputs.MeasurementInput(key="overlap_score", value=0.8, timestamp=1000),
                        ]
                    ),
                    inputs.StructureReference(
                        identifier="@mikro/roi",
                        object=_uid("roi3"),
                        measurements=[
                            inputs.MeasurementInput(key="overlap_score", value=1.0, timestamp=1000),
                        ]
                    )
                ],
                provenance=inputs.ProvenanceContext(subject="user", app_id="test")
            ),
            schema=relation_schema
        )
        
        # Query the relation edge to verify the materialized property
        edge = relation_controller.get_relation_by_id(relation_result.graph_id)
        assert edge is not None
        # avg_overlap should be 0.8
        assert abs(edge.properties.get("avg_overlap", 0) - 0.8) < 0.001
        
    def test_sum_aggregation_materializes_correctly(self, relation_controller: GraphController, relation_schema):
        """
        Test that SUM aggregation correctly sums measurements across ROIs.
        """
        neuron1_id = _uid("neuron1")
        neuron2_id = _uid("neuron2")
        
        # Create entities
        entity1 = relation_controller.create_entity(
            inputs.EntityCreationPayload(
                kind="Neuron", ref_id=neuron1_id,
                supporting_evidence=[],
                provenance=inputs.ProvenanceContext(subject="user", app_id="test")
            )
        )
        entity2 = relation_controller.create_entity(
            inputs.EntityCreationPayload(
                kind="Neuron", ref_id=neuron2_id,
                supporting_evidence=[],
                provenance=inputs.ProvenanceContext(subject="user", app_id="test")
            )
        )
        
        # Create relation with known confidence: 0.3, 0.4, 0.3
        # Expected sum: 0.3 + 0.4 + 0.3 = 1.0
        relation_result = relation_controller.create_relation(
            inputs.RelationCreationPayload(
                kind="SYNAPSES_WITH",
                source_id=entity1.db_id,
                target_id=entity2.db_id,
                supporting_evidence=[
                    inputs.StructureReference(
                        identifier="@mikro/roi",
                        object=_uid("roi1"),
                        measurements=[
                            inputs.MeasurementInput(key="confidence", value=0.3, timestamp=1000),
                        ]
                    ),
                    inputs.StructureReference(
                        identifier="@mikro/roi",
                        object=_uid("roi2"),
                        measurements=[
                            inputs.MeasurementInput(key="confidence", value=0.4, timestamp=1000),
                        ]
                    ),
                    inputs.StructureReference(
                        identifier="@mikro/roi",
                        object=_uid("roi3"),
                        measurements=[
                            inputs.MeasurementInput(key="confidence", value=0.3, timestamp=1000),
                        ]
                    )
                ],
                provenance=inputs.ProvenanceContext(subject="user", app_id="test")
            ),
            schema=relation_schema
        )
        
        edge = relation_controller.get_relation_by_id(relation_result.graph_id)
        assert edge is not None
        # total_confidence should be 1.0
        assert abs(edge.properties.get("total_confidence", 0) - 1.0) < 0.001
    
    def test_min_aggregation_materializes_correctly(self, relation_controller: GraphController, relation_schema):
        """
        Test that MIN aggregation correctly finds minimum across ROIs.
        """
        neuron1_id = _uid("neuron1")
        neuron2_id = _uid("neuron2")
        
        # Create entities
        entity1 = relation_controller.create_entity(
            inputs.EntityCreationPayload(
                kind="Neuron", ref_id=neuron1_id,
                supporting_evidence=[],
                provenance=inputs.ProvenanceContext(subject="user", app_id="test")
            )
        )
        entity2 = relation_controller.create_entity(
            inputs.EntityCreationPayload(
                kind="Neuron", ref_id=neuron2_id,
                supporting_evidence=[],
                provenance=inputs.ProvenanceContext(subject="user", app_id="test")
            )
        )
        
        # Create relation with known distances: 5.0, 2.5, 8.0
        # Expected min: 2.5
        relation_result = relation_controller.create_relation(
            inputs.RelationCreationPayload(
                kind="SYNAPSES_WITH",
                source_id=entity1.db_id,
                target_id=entity2.db_id,
                supporting_evidence=[
                    inputs.StructureReference(
                        identifier="@mikro/roi",
                        object=_uid("roi1"),
                        measurements=[
                            inputs.MeasurementInput(key="distance", value=5.0, unit="um", timestamp=1000),
                        ]
                    ),
                    inputs.StructureReference(
                        identifier="@mikro/roi",
                        object=_uid("roi2"),
                        measurements=[
                            inputs.MeasurementInput(key="distance", value=2.5, unit="um", timestamp=1000),
                        ]
                    ),
                    inputs.StructureReference(
                        identifier="@mikro/roi",
                        object=_uid("roi3"),
                        measurements=[
                            inputs.MeasurementInput(key="distance", value=8.0, unit="um", timestamp=1000),
                        ]
                    )
                ],
                provenance=inputs.ProvenanceContext(subject="user", app_id="test")
            ),
            schema=relation_schema
        )
        
        edge = relation_controller.get_relation_by_id(relation_result.graph_id)
        assert edge is not None
        # min_distance should be 2.5
        assert abs(edge.properties.get("min_distance", 0) - 2.5) < 0.001
    
    def test_count_aggregation_materializes_correctly(self, relation_controller: GraphController, relation_schema):
        """
        Test that COUNT aggregation correctly counts measurements.
        """
        neuron1_id = _uid("neuron1")
        neuron2_id = _uid("neuron2")
        
        # Create entities
        entity1 = relation_controller.create_entity(
            inputs.EntityCreationPayload(
                kind="Neuron", ref_id=neuron1_id,
                supporting_evidence=[],
                provenance=inputs.ProvenanceContext(subject="user", app_id="test")
            )
        )
        entity2 = relation_controller.create_entity(
            inputs.EntityCreationPayload(
                kind="Neuron", ref_id=neuron2_id,
                supporting_evidence=[],
                provenance=inputs.ProvenanceContext(subject="user", app_id="test")
            )
        )
        
        # Create relation with 4 overlap_score measurements
        relation_result = relation_controller.create_relation(
            inputs.RelationCreationPayload(
                kind="SYNAPSES_WITH",
                source_id=entity1.db_id,
                target_id=entity2.db_id,
                supporting_evidence=[
                    inputs.StructureReference(
                        identifier="@mikro/roi",
                        object=_uid("roi1"),
                        measurements=[
                            inputs.MeasurementInput(key="overlap_score", value=0.5, timestamp=1000),
                        ]
                    ),
                    inputs.StructureReference(
                        identifier="@mikro/roi",
                        object=_uid("roi2"),
                        measurements=[
                            inputs.MeasurementInput(key="overlap_score", value=0.6, timestamp=1000),
                        ]
                    ),
                    inputs.StructureReference(
                        identifier="@mikro/roi",
                        object=_uid("roi3"),
                        measurements=[
                            inputs.MeasurementInput(key="overlap_score", value=0.7, timestamp=1000),
                        ]
                    ),
                    inputs.StructureReference(
                        identifier="@mikro/roi",
                        object=_uid("roi4"),
                        measurements=[
                            inputs.MeasurementInput(key="overlap_score", value=0.8, timestamp=1000),
                        ]
                    )
                ],
                provenance=inputs.ProvenanceContext(subject="user", app_id="test")
            ),
            schema=relation_schema
        )
        
        edge = relation_controller.get_relation_by_id(relation_result.graph_id)
        assert edge is not None
        # evidence_count should be 4
        assert edge.properties.get("evidence_count") == 4


class TestRelationEvidenceGraph:
    """Tests for the evidence graph structure (ShadowLink, INFORMS, etc.)."""
    
    def test_shadow_link_created_for_relation(self, relation_controller: GraphController, relation_schema):
        """
        Test that a ShadowLink node is created when creating a relation.
        """
        neuron1_id = _uid("neuron1")
        neuron2_id = _uid("neuron2")
        
        entity1 = relation_controller.create_entity(
            inputs.EntityCreationPayload(
                kind="Neuron", ref_id=neuron1_id,
                supporting_evidence=[],
                provenance=inputs.ProvenanceContext(subject="user", app_id="test")
            )
        )
        entity2 = relation_controller.create_entity(
            inputs.EntityCreationPayload(
                kind="Neuron", ref_id=neuron2_id,
                supporting_evidence=[],
                provenance=inputs.ProvenanceContext(subject="user", app_id="test")
            )
        )
        
        link_ref_id = _uid("link_ref")
        
        relation_result = relation_controller.create_relation(
            inputs.RelationCreationPayload(
                ref_id=link_ref_id,
                kind="SYNAPSES_WITH",
                source_id=entity1.db_id,
                target_id=entity2.db_id,
                supporting_evidence=[
                    inputs.StructureReference(
                        identifier="@mikro/roi",
                        object=_uid("roi"),
                        measurements=[
                            inputs.MeasurementInput(key="overlap_score", value=0.9, timestamp=1000),
                        ]
                    )
                ],
                provenance=inputs.ProvenanceContext(subject="user", app_id="test")
            ),
            schema=relation_schema
        )
        
        # Verify ShadowLink was created with the ref_id
        shadow_link = relation_controller.get_shadow_link(link_ref_id)
        assert shadow_link is not None
        
    def test_evidence_structures_informs_shadow_link(self, relation_controller: GraphController, relation_schema):
        """
        Test that evidence structures are connected to ShadowLink via INFORMS.
        """
        neuron1_id = _uid("neuron1")
        neuron2_id = _uid("neuron2")
        roi_obj = _uid("roi")
        
        entity1 = relation_controller.create_entity(
            inputs.EntityCreationPayload(
                kind="Neuron", ref_id=neuron1_id,
                supporting_evidence=[],
                provenance=inputs.ProvenanceContext(subject="user", app_id="test")
            )
        )
        entity2 = relation_controller.create_entity(
            inputs.EntityCreationPayload(
                kind="Neuron", ref_id=neuron2_id,
                supporting_evidence=[],
                provenance=inputs.ProvenanceContext(subject="user", app_id="test")
            )
        )
        
        link_ref_id = _uid("link")
        
        relation_controller.create_relation(
            inputs.RelationCreationPayload(
                ref_id=link_ref_id,
                kind="SYNAPSES_WITH",
                source_id=entity1.db_id,
                target_id=entity2.db_id,
                supporting_evidence=[
                    inputs.StructureReference(
                        identifier="@mikro/roi",
                        object=roi_obj,
                        measurements=[
                            inputs.MeasurementInput(key="overlap_score", value=0.9, timestamp=1000),
                        ]
                    )
                ],
                provenance=inputs.ProvenanceContext(subject="user", app_id="test")
            ),
            schema=relation_schema
        )
        
        # Query informing structures for the shadow link
        informing_structures = relation_controller.get_informing_structures_for_link(link_ref_id)
        assert len(informing_structures) == 1
        assert informing_structures[0].object == roi_obj
        
    def test_shadow_link_reifies_entities(self, relation_controller: GraphController, relation_schema):
        """
        Test that ShadowLink is connected to both source and target via REIFIES.
        """
        neuron1_id = _uid("neuron1")
        neuron2_id = _uid("neuron2")
        
        entity1 = relation_controller.create_entity(
            inputs.EntityCreationPayload(
                kind="Neuron", ref_id=neuron1_id,
                supporting_evidence=[],
                provenance=inputs.ProvenanceContext(subject="user", app_id="test")
            )
        )
        entity2 = relation_controller.create_entity(
            inputs.EntityCreationPayload(
                kind="Neuron", ref_id=neuron2_id,
                supporting_evidence=[],
                provenance=inputs.ProvenanceContext(subject="user", app_id="test")
            )
        )
        
        link_ref_id = _uid("link")
        
        relation_controller.create_relation(
            inputs.RelationCreationPayload(
                ref_id=link_ref_id,
                kind="SYNAPSES_WITH",
                source_id=entity1.db_id,
                target_id=entity2.db_id,
                supporting_evidence=[],
                provenance=inputs.ProvenanceContext(subject="user", app_id="test")
            ),
            schema=relation_schema
        )
        
        # Get reified entities for the shadow link
        reified_entities = relation_controller.get_reified_entities(link_ref_id)
        assert len(reified_entities) == 2
        reified_ids = {e.entity_id for e in reified_entities}
        assert entity1.db_id in reified_ids
        assert entity2.db_id in reified_ids


class TestRelationProvenance:
    """Tests for relation provenance tracking."""
    
    def test_relation_has_assertion_provenance(self, relation_controller: GraphController, relation_schema):
        """
        Test that relations are created with an Assertion tracking provenance.
        """
        neuron1_id = _uid("neuron1")
        neuron2_id = _uid("neuron2")
        
        entity1 = relation_controller.create_entity(
            inputs.EntityCreationPayload(
                kind="Neuron", ref_id=neuron1_id,
                supporting_evidence=[],
                provenance=inputs.ProvenanceContext(subject="user", app_id="test")
            )
        )
        entity2 = relation_controller.create_entity(
            inputs.EntityCreationPayload(
                kind="Neuron", ref_id=neuron2_id,
                supporting_evidence=[],
                provenance=inputs.ProvenanceContext(subject="user", app_id="test")
            )
        )
        
        relation_result = relation_controller.create_relation(
            inputs.RelationCreationPayload(
                kind="SYNAPSES_WITH",
                source_id=entity1.db_id,
                target_id=entity2.db_id,
                supporting_evidence=[],
                provenance=inputs.ProvenanceContext(
                    subject="alice",
                    app_id="synapse_detector",
                    action_name="auto_detect"
                )
            ),
            schema=relation_schema
        )
        
        # Get assertion for the relation
        assertion = relation_controller.get_assertion_for_relation(relation_result.graph_id)
        assert assertion is not None
        assert assertion.subject == "alice"
        assert assertion.app_id == "synapse_detector"
        assert assertion.action_name == "auto_detect"
