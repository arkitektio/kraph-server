## The Evidence Graph: A Documentation for Biologists

From "Trust Me" to "Show Me"

Traditional databases store answers: "This cell is an AIS." "The length is 45µm."
But in science, an answer without context is just an opinion.

The Evidence Graph is different. It doesn't just store what we know; it stores how we know it. It treats every data point not as a static fact, but as a scientific assertion backed by proof.
1. The Core Concept: No Data Without Proof

In a standard spreadsheet or database, you might see this:
Cell ID	Type	Length (µm)
Cell_01	AIS	45.2

In the Evidence Graph, we refuse to store this row directly. Instead, we break it down into the scientific reality of Observation → Measurement → Conclusion.
The "Evidence Chain"

Every single value in the system—whether it's the shape of a cell or a connection between neurons—must be built from three layers:

    The Evidence (The Raw Data):

        What did we see?

        This is the raw material. It might be a region of interest (ROI) on an image, a manual annotation by a human, or a specific output from an AI model. We call these Structures.

    The Measurement (The Quantification):

        What values did we extract?

        We don't just say "length." We say: "This specific Evidence (ROI #123) has a vector_length of 45.2µm, measured with Confidence: 0.99."

    The Entity (The Scientific Conclusion):

        What is it biologically?

        The Entity (e.g., an AIS, a Soma, a Synapse) is just a Shell. It has no values of its own. It simply "listens" to the Evidence attached to it.

        If you attach a new ROI to an AIS entity, the AIS automatically updates its length.

2. How It Works: The "Lazy" Scientist

The most powerful feature of this system is that the Entity is lazy. It doesn't hard-code values. It calculates them on the fly based on what evidence is available right now.
Example: The Length of an Axon

Imagine you are defining an Axon Initial Segment (AIS).

    You create an Entity: "I assert there is an AIS here (ID: AIS_1)."

        Current State: AIS_1 exists, but has no length.

    You add Evidence: "Here is a hand-drawn line (ROI) that represents it."

    You add a Measurement: "This line is 120µm long."

    The System Reacts: The AIS_1 entity sees the new evidence. It looks at its definition (the Schema) which says: "An AIS's length is the average of all its supporting ROIs."

    The Result: The AIS_1 entity now reports: length = 120µm.

Why is this better?
If a colleague comes along later and says, "Actually, you missed a segment," they don't overwrite your data. They simply add a second piece of Evidence (another ROI). The Entity automatically recalculates the average or sum, blending both inputs transparently.
3. Provenance: "Who Said That?"

In science, who made a claim is as important as the claim itself. Was it a Nobel laureate or a buggy beta algorithm?

Every time data enters the Evidence Graph, it is wrapped in an Assertion.

    Subject: Who did it? (e.g., Dr. Smith or Algorithm_v2.1)

    App: Which tool were they using? (e.g., LabView_Custom or Web_Annotator)

    Timestamp: When did it happen?

When you ask the graph for a value, you don't just get 45.2. You get:

    "45.2µm (Confidence: 98%), derived from ROI #555, asserted by AI_Model_X on Jan 15th."

The confidence is not special to measurements. Any claim — "this is a Cell", "these two are the same cell", "this cell is gone" — can carry how sure the claimant was, and a graph's rules can say "count the model's classifications only when it was at least 90% sure" while counting a human's whether or not they gave a number.

4. Key Terminology (Cheat Sheet)
Term	Biological Analogy	Technical Role
Entity	The Specimen. (e.g., "The Cell")	A container for identity. It aggregates data.
Structure	The Observation. (e.g., "The Stain")	The raw geometry or evidence object (ROI).
Measurement	The Notebook Entry.	A single data point (key=value) describing a Structure.
Assertion	The Signature.	Links the data to the person/tool who created it.
Relation	The Interaction.	A connection between entities (e.g., CONNECTED_TO) backed by its own evidence.
5. Summary

The Evidence Graph protects scientific integrity by enforcing a simple rule: You cannot change the biological reality (the Entity) directly; you can only provide new evidence.

    Want to update a length? Add a new measurement.

    Want to correct a classification? Add a new label.

    Want to dispute a finding? Add conflicting evidence.

The system handles the math. You handle the science.