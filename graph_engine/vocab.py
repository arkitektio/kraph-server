

# Measurement
DESCRIBES = "DESCRIBES" # Relationship indicating that an Measurement describes an Structure
INFORMS = "INFORMS"   # Relationship indicating that a Structure informs an Entity / Event
ASSERTED = "ASSERTED" # Relationship indicating that an Assertion supports a Measurment / Observation

# Provenance
GENERATED = "GENERATED"  # Relationship indicating that an Assertion generated a  Measurement / Observation


# Relation
REIFIES_AS_SOURCE = "REIFIES_AS_SOURCE"  # Relationship indicating that a Relation reifies a StructureRelation as source
REIFIES_AS_TARGET = "REIFIES_AS_TARGET"  # Relationship indicating that a Relation reifies a StructureRelation as target

ShadowLink = "ShadowLink"  # A link representing a shadow relationship between nodes

Measurement = "Measurement"
Structure = "Structure"

# 
Assertion = "Assertion"
# An assertion about what happend when to the graph, and who was responsible for it

# Entity / Event Types
Entity = "Entity"
ProtocolEvent = "ProtocolEvent"
NaturalEvent = "NaturalEvent"
