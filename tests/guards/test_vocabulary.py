"""The suite speaks the model's vocabulary, and none of the retired words.

A test named for a word the code no longer has pins a story rather than a
property. The retired words: the graph database that held the drawing before
RFC 0005, the view-level `selector` (RFC 0009), the `lifecycle` flag (C7), the
lowercase `rollup` (it is a derivation; `ROLLUP` the enum value stays),
`archive*` for a claim (a claim is `retract`ed; `archiveGraph` is product state
and stays), and the six in-place `update*` instance mutations (a correction is a
new claim: `supersede*` / `recordMetrics`).

Text from a line `History:` to the end of that docstring is exempt, because the
story of a bug is allowed to name what the bug was; so is a line ending in
`# retired`, for a test that asserts the word's absence.

No database, no docker stack.
"""

from __future__ import annotations

import pathlib
import re

TESTS = pathlib.Path(__file__).resolve().parent.parent

RETIRED = {
    "the graph database": re.compile(r"\bAGE\b|Apache AGE|agtype|cypher\("),
    "the view-level selector": re.compile(r"graph\.selector|\"selector\"|selector\w*Input|def test_\w*selector"),
    "the lifecycle flag": re.compile(r"\blifecycle\b|__lifecycle_state"),
    "a lowercase rollup": re.compile(r"(?<![A-Z_.\"])rollup"),
    "archiving a claim": re.compile(
        r"archiv(?:ed|ing|e|es)?(?:_an?|_the)?_(?:entity|structure|metric|relation|measurement|natural_?event|protocol_?event|link|node|claim|instance|participation|sameness|comment)"
        r"|ARCHIVE_\w*(?:ENTITY|STRUCTURE|METRIC|RELATION|EVENT)"
    ),
    "an in-place update": re.compile(r"update_?(?:Entity|Structure|Metric|Relation|NaturalEvent|ProtocolEvent|entity|structure|metric|relation|natural_event|protocol_event)(?![A-Za-z_])"),
}


def _checked_lines(text: str) -> list[tuple[int, str]]:
    """Every line the guard reads: history paragraphs and `# retired` lines are skipped."""
    lines: list[tuple[int, str]] = []
    in_history = False
    for number, line in enumerate(text.splitlines(), start=1):
        if line.rstrip().endswith("# retired"):
            continue
        if re.match(r"\s*History:", line):
            in_history = True
        if in_history:
            if '"""' in line:
                in_history = False
            continue
        lines.append((number, line))
    return lines


def test_no_test_speaks_a_retired_word() -> None:
    """Every `tests/**/*.py` but this one is free of the retired vocabulary."""
    offences: list[str] = []
    for path in sorted(TESTS.rglob("*.py")):
        if path.resolve() == pathlib.Path(__file__).resolve():
            continue
        for number, line in _checked_lines(path.read_text()):
            for word, pattern in RETIRED.items():
                if pattern.search(line):
                    offences.append(f"{path.relative_to(TESTS.parent)}:{number}: {word}: {line.strip()[:100]}")
    assert not offences, "retired vocabulary in the suite:\n" + "\n".join(offences)
