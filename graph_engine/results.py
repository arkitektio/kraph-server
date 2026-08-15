"""What a write hands back: the claim it recorded, and everywhere that claim stands.

Instance writes used to return a `RetrievedNode` — a **projection-shaped** object
for an operation whose result is not a projection. That forced two untruths, and
they are opposite in sign:

- **A claim no view draws** had to come back as a node anyway, so
  `RetrievedNode.from_row` borrowed a category from *some* graph — one that had
  not drawn it, chosen by an unordered `.first()`. Two identical writes could
  report different categories.
- **A claim several views draw** had to come back as *one* node, so
  `projected_node` returned the first graph that succeeded and discarded the
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
— `controller.archive_node` unprojects from every view declaring the word,
ignoring each view's selector — and reading the answer means this layer becomes
correct for free when that is fixed, instead of having to be fixed twice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Union

from core import models as core_models
from evidence import models as evidence_models
from graph_engine import retrieved


@dataclass(frozen=True)
class NodeDrawing:
    """One view that draws a claimed node, and how it draws it."""

    graph: core_models.Graph
    #: Non-null by construction: `projector.create_vertex` is the only writer of a
    #: vertex and takes a category to label it with, so "drawn under no category"
    #: is unreachable. This is the category the **vertex** carries, read back from
    #: its `category_id`, not the one a resolver thinks it should have.
    category: core_models.Category
    #: The node as *this* graph holds it — derived properties and all. Its
    #: `graph_name` and `label` are finally true, which they cannot be on a
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
    #: the subject: `Node.assertion` is the assertion that *first* claimed the
    #: node exists, so for an attestation or a retraction it names somebody else's
    #: act, possibly years earlier.
    assertion: evidence_models.Assertion
    #: What was claimed, in its API-facing form — a `Retrieved*` built from the
    #: evidence row, **not** from a projection. Row-backed on purpose: the claim
    #: is one thing, and the several ways views draw it are in `drawings`, each
    #: attached to the graph whose answer it is. A client wanting derived
    #: properties reads them from a drawing, because derived properties are
    #: per-graph and always were.
    #:
    #: A tuple because three writes are batches, and a batch is **one** assertion
    #: over many subjects rather than many assertions —
    #: `assert_participations`' own docstring says "one assertion covers the
    #: batch". Returning a list of results would have implied N acts where the
    #: caller performed one.
    subjects: tuple[Any, ...]
    drawings: tuple[Drawing, ...] = ()

    @property
    def subject(self) -> Any:
        """The single subject, for the writes that have exactly one."""
        if len(self.subjects) != 1:
            raise ValueError(f"This assertion has {len(self.subjects)} subjects; use `subjects`.")
        return self.subjects[0]

    @classmethod
    def of(
        cls,
        assertion: evidence_models.Assertion,
        subject: Any,
        drawings: tuple[Drawing, ...] = (),
    ) -> "Asserted":
        """Build a result for a write with one subject."""
        return cls(assertion=assertion, subjects=(subject,), drawings=drawings)
