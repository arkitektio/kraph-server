"""What a write hands back: the claim it recorded, and everywhere that claim stands.

Three parts, and the middle one is an evidence row: the act (`Assertion`), the claim
(`Instance`, `Link`, `Structure`, `Metric`), and the drawings. The API serves the
claim as `Instance` / `Link` rather than as `Entity` / `Relation`, because those are
*drawing* shapes — a label, a category, derived properties, a schema version — and a
write's result may be drawn nowhere at all. Two of `Entity`'s fields could not answer
in that case: `schemaVersion` is non-null with nothing to give, and `richProperties`
asserted on a category that by definition does not exist.

Instance writes used to return a `RetrievedNode` — a **projection-shaped** object
for an operation whose result is not a projection. That forced two untruths, and
they are opposite in sign:

- **A claim no view draws** had to come back as a node anyway, so
  `RetrievedNode.from_row` borrowed a category from *some* graph — one that had
  not drawn it, chosen by an unordered `.first()`. Two identical writes could
  report different categories.
- **A claim several views draw** had to come back as *one* node, so
  `projected_instance` returned the first graph that succeeded and discarded the
  rest. The `order_by("pk")` that made this deterministic was damage control on a
  lossy shape, not a fix.

Both are the same mistake: a write is an act of claiming, and where the claim
materializes is a *list* — possibly empty, possibly long. So that is what it
returns.

**`drawings` means "where this stands, now, after this assertion."** One rule for
every write, with no per-mutation special case:

- asserting: every view whose rules admit the new claim;
- attesting: every view it was redrawn into;
- retracting: every view that still draws it — **usually empty, and not always.**
  Existence is folded under each graph's own selector
  (`projector.resolve_categories`), so a retraction by somebody a view does not
  listen to does not remove it there. Hardcoding `[]` for retraction would
  reintroduce exactly the dishonesty this module exists to remove.

Which is why every drawing is **read back from the projection** rather than
derived from what the write path intended. The two are not the same thing today
— `controller.retract_node` unprojects from every view declaring the word,
ignoring each view's selector — and reading the answer means this layer becomes
correct for free when that is fixed, instead of having to be fixed twice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from core import models as core_models
from evidence import models as evidence_models
from graph_engine import retrieved


@dataclass(frozen=True)
class NodeDrawing:
    """One view that draws a claimed node, and how it draws it."""

    graph: core_models.Graph
    #: Non-null by construction: `projector.create_vertex` is the only writer of a
    #: vertex and takes at least one category to label it with, so "drawn under
    #: no category" is unreachable. One drawing per category (RFC 0019): a view
    #: that draws a node under Pyramidal and Excitatory reports two drawings, on
    #: the same `graph` and the same `node`. This is the rule's answer
    #: (`resolve_categories`), checked against the `category_ids` the vertex
    #: carries.
    category: core_models.Category
    #: The node as *this* graph holds it — derived properties and all. Its
    #: `graph_name` and `labels` are finally true, which they cannot be on a
    #: result that has to stand for every view at once.
    node: retrieved.RetrievedNode


@dataclass(frozen=True)
class EdgeDrawing:
    """One view that draws a claimed edge, and how it draws it."""

    graph: core_models.Graph
    #: The base `Category`, deliberately not `EdgeCategory`. A participation
    #: claim names the **event's** category — a node category — because its edge
    #: label comes off `AGE_INPUT_EDGE` / `AGE_OUTPUT_EDGE`, which are constants
    #: of the event kind. Narrowing this field would make every participation
    #: drawing fail to resolve.
    category: core_models.Category
    edge: retrieved.RetrievedEdge


Drawing = Union[NodeDrawing, EdgeDrawing]


@dataclass(frozen=True)
class Asserted:
    """One act of claiming: what was recorded, what it was about, where it stands."""

    #: The assertion **this call** made. Carried explicitly and never derived from
    #: the subject: `Instance.assertion` is the assertion that *first* claimed the
    #: node exists, so for an attestation or a retraction it names somebody else's
    #: act, possibly years earlier.
    assertion: evidence_models.Assertion
    #: What was claimed: the **evidence row itself** — an `Instance`, a `Link`, a
    #: `Structure` or a `Metric`. Not a `Retrieved*` adapter, which is a *reading*
    #: of a row through some view and carries a label, a category and derived
    #: properties that a claim has not got. A client wanting those reads them from
    #: a drawing, where they are one graph's answer and true.
    #:
    #: That also removed the last `_category_for_term` call from the write paths.
    #: It answers "any view's category for this word, lowest id" — defensible for a
    #: drawing, which names its own graph, and never for a payload that stands for
    #: every view at once.
    #:
    #: A tuple because three writes are batches, and a batch is **one** assertion
    #: over many subjects rather than many assertions —
    #: `assert_participations`' own docstring says "one assertion covers the
    #: batch". Returning a list of results would have implied N acts where the
    #: caller performed one.
    #:
    #: `evidence_models.Claim` is the five tables an assertion can record into,
    #: named rather than left as `Any`: the API narrows each payload to one of
    #: them (`cast(Instance, …)`, `cast(Link, …)`), and a union is what makes
    #: those casts checkable.
    subjects: tuple[evidence_models.Claim, ...]
    drawings: tuple[Drawing, ...] = ()
    #: The act committed and was announced, but its drawing did not finish: the
    #: outbox row stands and `reproject --incremental` (the runner) owes it.
    #: `drawings` is still what was read back — possibly partial across views —
    #: never what the write intended. False is the ordinary case: the draw
    #: completes inside the request.
    pending: bool = False

    @property
    def subject(self) -> evidence_models.Claim:
        """The single subject, for the writes that have exactly one."""
        if len(self.subjects) != 1:
            raise ValueError(f"This assertion has {len(self.subjects)} subjects; use `subjects`.")
        return self.subjects[0]

    @classmethod
    def of(
        cls,
        assertion: evidence_models.Assertion,
        subject: evidence_models.Claim,
        drawings: tuple[Drawing, ...] = (),
        *,
        pending: bool = False,
    ) -> "Asserted":
        """Build a result for a write with one subject."""
        return cls(assertion=assertion, subjects=(subject,), drawings=drawings, pending=pending)
